"""In-memory artifact registry for storing and querying typed artifacts."""

from __future__ import annotations

from hi_agent.artifacts.contracts import Artifact


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

    def store(self, artifact: Artifact) -> None:
        """Store an artifact (overwrites if same ID exists)."""
        self._store[artifact.artifact_id] = artifact

    def get(self, artifact_id: str) -> Artifact | None:
        """Retrieve an artifact by ID."""
        return self._store.get(artifact_id)

    def query(
        self,
        *,
        artifact_type: str | None = None,
        producer_action_id: str | None = None,
    ) -> list[Artifact]:
        """Query artifacts with optional type and producer filters."""
        results = list(self._store.values())
        if artifact_type is not None:
            results = [a for a in results if a.artifact_type == artifact_type]
        if producer_action_id is not None:
            results = [a for a in results if a.producer_action_id == producer_action_id]
        return results

    def query_by_source_ref(self, source_ref: str) -> list[Artifact]:
        """Return all artifacts that reference the given source artifact ID."""
        return [a for a in self._store.values() if source_ref in a.source_refs]

    def query_by_upstream(self, upstream_id: str) -> list[Artifact]:
        """Return all artifacts that list upstream_id in their upstream_artifact_ids."""
        return [a for a in self._store.values() if upstream_id in a.upstream_artifact_ids]

    def all(self) -> list[Artifact]:
        """Return all stored artifacts."""
        return list(self._store.values())

    def count(self) -> int:
        """Return the number of stored artifacts."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all artifacts."""
        self._store.clear()
