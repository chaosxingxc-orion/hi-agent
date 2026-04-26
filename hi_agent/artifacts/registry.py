"""In-memory artifact registry for storing and querying typed artifacts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.metrics import (
    legacy_tenantless_denied_total,
    legacy_tenantless_visible_total,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext


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
        exec_ctx: RunExecutionContext | None = None,
        **kwargs: Any,
    ) -> Artifact:
        """Create and store an Artifact, optionally enriching from exec_ctx.

        Args:
            exec_ctx: Optional RunExecutionContext; when provided, ``run_id``
                and ``project_id`` (and tenant/user/session spine) are sourced
                from it unless already set in *kwargs*.
            **kwargs: Additional keyword arguments forwarded to ``Artifact()``.

        Returns:
            The newly created and stored Artifact.
        """
        if exec_ctx is not None:
            kwargs.setdefault("run_id", exec_ctx.run_id)
            kwargs.setdefault("project_id", exec_ctx.project_id)
            kwargs.setdefault("tenant_id", exec_ctx.tenant_id)
            kwargs.setdefault("user_id", exec_ctx.user_id)
            kwargs.setdefault("session_id", exec_ctx.session_id)
        artifact = Artifact(**kwargs)
        self._store[artifact.artifact_id] = artifact
        return artifact

    def store(self, artifact: Artifact) -> None:
        """Store an artifact (overwrites if same ID exists)."""
        self._store[artifact.artifact_id] = artifact

    def register(self, artifact: Artifact) -> None:
        """Alias for store() — satisfies ArtifactStore protocol."""
        self.store(artifact)

    def get(self, artifact_id: str, *, tenant_id: str | None = None) -> Artifact | None:
        """Retrieve an artifact by ID, optionally filtered by tenant."""
        artifact = self._store.get(artifact_id)
        if artifact is None:
            return None
        if tenant_id is not None and tenant_id != "":
            art_tenant = getattr(artifact, "tenant_id", "")
            if art_tenant in (None, ""):
                if not self._legacy_allowed(artifact.artifact_id, tenant_id):
                    return None
            elif art_tenant != tenant_id:
                return None
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
            results = [a for a in results if self._tenant_visible(a, tenant_id)]
        if artifact_type is not None:
            results = [a for a in results if a.artifact_type == artifact_type]
        if producer_action_id is not None:
            results = [a for a in results if a.producer_action_id == producer_action_id]
        return results

    def query_by_source_ref(
        self, source_ref: str, *, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts that reference the given source artifact ID."""
        results = [a for a in self._store.values() if source_ref in a.source_refs]
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_visible(a, tenant_id)]
        return results

    def query_by_upstream(
        self, upstream_id: str, *, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts that list upstream_id in their upstream_artifact_ids."""
        results = [
            a for a in self._store.values() if upstream_id in a.upstream_artifact_ids
        ]
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_visible(a, tenant_id)]
        return results

    def all(self, *, tenant_id: str | None = None) -> list[Artifact]:
        """Return all stored artifacts, optionally filtered by tenant."""
        if tenant_id is None or tenant_id == "":
            return list(self._store.values())
        return [a for a in self._store.values() if self._tenant_visible(a, tenant_id)]

    def _legacy_allowed(self, artifact_id: str, requested_tenant: str) -> bool:
        """Posture-aware policy for a single legacy tenantless artifact (get path)."""
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if posture.is_strict:
            _logger.warning(
                "legacy tenantless artifact denied in strict posture: "
                "artifact_id=%s tenant_requested=%s",
                artifact_id,
                requested_tenant,
            )
            legacy_tenantless_denied_total.inc(posture=posture.value)
            return False
        _logger.debug(
            "legacy tenantless artifact visible in dev posture: artifact_id=%s",
            artifact_id,
        )
        legacy_tenantless_visible_total.inc(posture=posture.value)
        return True

    def _tenant_visible(self, artifact: Artifact, tenant_id: str) -> bool:
        """Return True if artifact is visible to the requesting tenant."""
        art_tenant = getattr(artifact, "tenant_id", "")
        if art_tenant in (None, ""):
            return self._legacy_allowed(artifact.artifact_id, tenant_id)
        return art_tenant == tenant_id

    def count(self, tenant_id: str | None = None) -> int:
        """Return the number of stored artifacts, optionally filtered by tenant."""
        return len(self.all(tenant_id=tenant_id))

    def clear(self) -> None:
        """Remove all artifacts."""
        self._store.clear()
