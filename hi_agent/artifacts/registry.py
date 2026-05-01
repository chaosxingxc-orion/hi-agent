"""In-memory artifact registry for storing and querying typed artifacts."""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING

from hi_agent.artifacts.contracts import (
    Artifact,
    ArtifactConflictError,
    ArtifactIntegrityError,
    derive_artifact_id,
)

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext

_logger = logging.getLogger(__name__)


def _enforce_content_addressed_id(artifact: Artifact) -> None:
    """A-11 write-time guard for content-addressable artifacts.

    - Under research/prod posture: stored ``artifact_id`` MUST equal
      ``derive_artifact_id(content_hash)``; mismatch raises
      :class:`ArtifactIntegrityError`.
    - Under dev posture: if the caller supplied a non-derived ``artifact_id``,
      auto-derive (mutating the artifact) and emit a WARNING.

    Only applies when the artifact is content-addressable AND has a
    non-empty ``content_hash``.
    """
    if not artifact.is_content_addressable or not artifact.content_hash:
        return

    expected = derive_artifact_id(artifact.content_hash)
    if artifact.artifact_id == expected:
        return

    from hi_agent.config.posture import Posture
    posture = Posture.from_env()
    msg = (
        f"artifact_id must derive from content_hash for content-addressable "
        f"type {artifact.artifact_type!r}: stored={artifact.artifact_id!r} "
        f"expected={expected!r}"
    )
    if posture.is_strict:
        raise ArtifactIntegrityError(msg)
    # Dev posture: auto-derive, warn loudly so the drift is observable.
    _logger.warning("auto-deriving artifact_id under dev posture: %s", msg)
    object.__setattr__(artifact, "artifact_id", expected)


class ArtifactRegistry:
    """Store and query artifacts by ID, type, or producer.

    ArtifactRegistry is always in-memory.  Under research/prod posture it
    should not be used as the primary registry — use ArtifactLedger instead.
    Constructing an ArtifactRegistry under research/prod raises ``ValueError``
    to surface accidental in-memory usage early (TE-2).
    """

    def __init__(self) -> None:
        # TE-2: posture gate — block in-memory registry under research/prod.
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if posture.requires_durable_registry:
            raise ValueError(
                "ArtifactRegistry is in-memory and cannot be used under "
                f"{posture.value!r} posture; use ArtifactLedger with a "
                "durable file path instead"
            )
        self._store: dict[str, Artifact] = {}

    def create(
        self,
        *,
        exec_ctx: RunExecutionContext | None = None,
        artifact_type: str = "base",
        **kwargs: object,
    ) -> Artifact:
        """Create, register, and return a new Artifact.

        Spine fields from exec_ctx are applied only when the caller has not
        already supplied the same key in kwargs (explicit kwargs win per Rule 12).
        """
        if exec_ctx is not None:
            for field in ("tenant_id", "user_id", "session_id", "project_id", "run_id"):
                if field not in kwargs and getattr(exec_ctx, field, ""):
                    kwargs[field] = getattr(exec_ctx, field)
        artifact = Artifact(artifact_type=artifact_type, **kwargs)  # type: ignore[arg-type]
        # A-11: when caller did not pin artifact_id and the type is
        # content-addressable, derive id from hash before storing so subsequent
        # idempotent registrations of the same content map to the same id.
        if (
            "artifact_id" not in kwargs
            and artifact.is_content_addressable
            and artifact.content_hash
        ):
            object.__setattr__(
                artifact, "artifact_id", derive_artifact_id(artifact.content_hash)
            )
        self.store(artifact)
        return artifact

    def store(self, artifact: Artifact, *, exec_ctx: RunExecutionContext | None = None) -> None:
        """Store an artifact (overwrites if same ID exists).

        Args:
            artifact: The Artifact to persist.
            exec_ctx: Optional RunExecutionContext; when provided, spine fields
                (tenant_id, run_id, project_id) are set on the artifact via
                setattr when the artifact's own fields are empty and the
                artifact supports dynamic attribute setting.

        Raises:
            OSError: When ``HI_AGENT_ARTIFACT_FAULT=oserror`` is set in the
                environment (chaos fault injection for disk-full simulation).
            ArtifactIntegrityError: A-11 — when posture is research/prod and
                the artifact is content-addressable but ``artifact_id`` does
                not derive from ``content_hash``.
            ArtifactConflictError: A-11 — when an existing ``artifact_id``
                already maps to a different ``content_hash``.  Maps to HTTP
                409 at the route layer.
        """
        if os.environ.get("HI_AGENT_ARTIFACT_FAULT") == "oserror":
            raise OSError("Simulated disk full fault — HI_AGENT_ARTIFACT_FAULT=oserror")
        from hi_agent.server.fault_injection import get_fault_injector
        get_fault_injector().maybe_raise_disk_full()
        if exec_ctx is not None:
            for field_name, ctx_value in (
                ("tenant_id", exec_ctx.tenant_id),
                ("run_id", exec_ctx.run_id),
                ("project_id", exec_ctx.project_id),
            ):
                if ctx_value and not getattr(artifact, field_name, ""):
                    with contextlib.suppress(AttributeError, TypeError):
                        object.__setattr__(artifact, field_name, ctx_value)

        # A-11: content-addressed identity enforcement (may mutate artifact_id
        # under dev posture; raises under research/prod on mismatch).
        _enforce_content_addressed_id(artifact)

        # A-11: 409 — same artifact_id, different content_hash is a conflict.
        existing = self._store.get(artifact.artifact_id)
        if (
            existing is not None
            and existing.content_hash
            and artifact.content_hash
            and existing.content_hash != artifact.content_hash
        ):
            raise ArtifactConflictError(
                f"artifact_id={artifact.artifact_id!r} already exists with a "
                f"different content_hash (existing={existing.content_hash[:16]}... "
                f"new={artifact.content_hash[:16]}...)"
            )

        self._store[artifact.artifact_id] = artifact

    def _tenant_match(self, art: Artifact, tenant_id: str) -> bool:
        """HD-4: posture-aware tenant filter.

        Under research/prod posture, an artifact matches *only* when its
        ``tenant_id`` exactly equals the requested ``tenant_id`` — a legacy
        tenantless artifact (tenant_id == "") is excluded so it cannot leak
        across tenants. The denial is countable via
        :data:`legacy_tenantless_denied_total` and emits a WARNING.

        Under dev posture, the legacy lenient match is retained so that
        existing pre-CO-5 corpora keep working; the admission is countable
        via :data:`legacy_tenantless_visible_total` and emits a debug log.
        """
        from hi_agent.artifacts.metrics import (
            legacy_tenantless_denied_total,
            legacy_tenantless_visible_total,
        )
        from hi_agent.config.posture import Posture

        art_tenant = getattr(art, "tenant_id", "")
        posture = Posture.from_env()
        if art_tenant in ("", None) and tenant_id != "":
            # legacy tenantless path — observable under both postures
            if posture.is_strict:
                legacy_tenantless_denied_total.inc(posture.value)
                _logger.warning(
                    "ArtifactRegistry: denying access to legacy tenantless "
                    "artifact %r for tenant_id=%r under %s posture (HD-4)",
                    getattr(art, "artifact_id", "<no-id>"),
                    tenant_id,
                    posture.value,
                )
                return False
            legacy_tenantless_visible_total.inc(posture.value)
            _logger.debug(
                "ArtifactRegistry: admitting legacy tenantless artifact %r "
                "to tenant_id=%r under %s posture (HD-4)",
                getattr(art, "artifact_id", "<no-id>"),
                tenant_id,
                posture.value,
            )
            return True
        if posture.is_strict:
            return art_tenant == tenant_id and tenant_id != ""
        return art_tenant in ("", None, tenant_id)

    def get(self, artifact_id: str, tenant_id: str | None = None) -> Artifact | None:
        """Retrieve an artifact by ID, optionally filtered by tenant."""
        artifact = self._store.get(artifact_id)
        if artifact is None:
            return None
        if tenant_id is not None and tenant_id != "" and not self._tenant_match(
            artifact, tenant_id
        ):
            return None  # not owned by this tenant
        return artifact

    def query(
        self,
        *,
        artifact_type: str | None = None,
        producer_action_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[Artifact]:
        """Query artifacts with optional type, producer, and tenant filters."""
        results = list(self._store.values())
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_match(a, tenant_id)]
        if artifact_type is not None:
            results = [a for a in results if a.artifact_type == artifact_type]
        if producer_action_id is not None:
            results = [a for a in results if a.producer_action_id == producer_action_id]
        return results

    def query_by_source_ref(
        self, source_ref: str, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts that reference the given source artifact ID."""
        results = [a for a in self._store.values() if source_ref in a.source_refs]
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_match(a, tenant_id)]
        return results

    def query_by_upstream(
        self, upstream_id: str, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts that list upstream_id in their upstream_artifact_ids."""
        results = [
            a for a in self._store.values() if upstream_id in a.upstream_artifact_ids
        ]
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_match(a, tenant_id)]
        return results

    def all(self, tenant_id: str | None = None) -> list[Artifact]:
        """Return all stored artifacts, optionally filtered by tenant."""
        if tenant_id is None or tenant_id == "":
            return list(self._store.values())
        return [a for a in self._store.values() if self._tenant_match(a, tenant_id)]

    def count(self, tenant_id: str | None = None) -> int:
        """Return the number of stored artifacts, optionally filtered by tenant."""
        return len(self.all(tenant_id=tenant_id))

    def register_artifact(
        self,
        *,
        tenant_id: str,
        run_id: str,
        artifact_type: str,
        content: object,
        metadata: dict,
    ) -> str:
        """Create and store a new artifact; return its artifact_id.

        This is the write path for the POST /v1/artifacts route (W10-M.2).
        Rule 12: tenant_id and run_id are required and stamped on the record.
        """
        if not tenant_id:
            raise ValueError("register_artifact requires a non-empty tenant_id")
        if not run_id:
            raise ValueError("register_artifact requires a non-empty run_id")
        artifact = self.create(
            artifact_type=artifact_type,
            content=content,
            metadata=dict(metadata),
            tenant_id=tenant_id,
            run_id=run_id,
        )
        return artifact.artifact_id

    def clear(self) -> None:
        """Remove all artifacts."""
        self._store.clear()
