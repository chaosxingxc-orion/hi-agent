"""In-memory artifact registry for storing and querying typed artifacts."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from hi_agent.artifacts.contracts import Artifact

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
        """
        if exec_ctx is not None:
            for field_name, ctx_value in (
                ("tenant_id", exec_ctx.tenant_id),
                ("run_id", exec_ctx.run_id),
                ("project_id", exec_ctx.project_id),
            ):
                if ctx_value and not getattr(artifact, field_name, ""):
                    with contextlib.suppress(AttributeError, TypeError):
                        object.__setattr__(artifact, field_name, ctx_value)
        self._store[artifact.artifact_id] = artifact

    def get(self, artifact_id: str, tenant_id: str | None = None) -> Artifact | None:
        """Retrieve an artifact by ID, optionally filtered by tenant."""
        artifact = self._store.get(artifact_id)
        if artifact is None:
            return None
        if tenant_id is not None and tenant_id != "":
            art_tenant = getattr(artifact, "tenant_id", "")
            if art_tenant not in ("", None, tenant_id):
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
            results = [
                a for a in results
                if getattr(a, "tenant_id", "") in ("", None, tenant_id)
            ]
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
            results = [
                a for a in results
                if getattr(a, "tenant_id", "") in ("", None, tenant_id)
            ]
        return results

    def query_by_upstream(
        self, upstream_id: str, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts that list upstream_id in their upstream_artifact_ids."""
        results = [
            a for a in self._store.values() if upstream_id in a.upstream_artifact_ids
        ]
        if tenant_id is not None and tenant_id != "":
            results = [
                a for a in results
                if getattr(a, "tenant_id", "") in ("", None, tenant_id)
            ]
        return results

    def all(self, tenant_id: str | None = None) -> list[Artifact]:
        """Return all stored artifacts, optionally filtered by tenant."""
        if tenant_id is None or tenant_id == "":
            return list(self._store.values())
        return [
            a for a in self._store.values()
            if getattr(a, "tenant_id", "") in ("", None, tenant_id)
        ]

    def count(self, tenant_id: str | None = None) -> int:
        """Return the number of stored artifacts, optionally filtered by tenant."""
        return len(self.all(tenant_id=tenant_id))

    def clear(self) -> None:
        """Remove all artifacts."""
        self._store.clear()
