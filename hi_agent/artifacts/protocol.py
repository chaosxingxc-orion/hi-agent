"""Structural protocol for artifact stores (C1 — interface compatibility).

Any class satisfying this protocol can be used wherever an artifact store is
expected — both ArtifactRegistry (in-memory) and ArtifactLedger (durable) must
conform so that routes_artifacts.py can hold a typed reference without duck-typing.
"""
from __future__ import annotations

from typing import Protocol

from hi_agent.artifacts.contracts import Artifact


class ArtifactStore(Protocol):
    """Structural interface implemented by ArtifactRegistry and ArtifactLedger."""

    def get(self, artifact_id: str, *, tenant_id: str | None = None) -> Artifact | None:
        """Retrieve an artifact by ID, optionally filtered by tenant."""
        ...

    def query(
        self,
        *,
        artifact_type: str | None = None,
        producer_action_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[Artifact]:
        """Query artifacts with optional type, producer, and tenant filters."""
        ...

    def all(self, *, tenant_id: str | None = None) -> list[Artifact]:
        """Return all stored artifacts, optionally filtered by tenant."""
        ...

    def query_by_source_ref(
        self, source_ref: str, *, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts referencing the given source ref."""
        ...

    def query_by_upstream(
        self, upstream_id: str, *, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts that list upstream_id in upstream_artifact_ids."""
        ...

    def store(self, artifact: Artifact) -> None:
        """Persist an artifact."""
        ...

    def register(self, artifact: Artifact) -> None:
        """Alias for store() used by some callers."""
        ...
