"""Evidence collection and storage for Harness actions."""

from __future__ import annotations

from hi_agent.harness.contracts import EvidenceRecord


class EvidenceStore:
    """In-memory evidence store with ref-based retrieval.

    Stores evidence records keyed by evidence_ref, with secondary
    indexing by action_id for efficient per-action lookups.
    """

    def __init__(self) -> None:
        """Initialize empty evidence store."""
        self._records: dict[str, EvidenceRecord] = {}
        self._by_action: dict[str, list[str]] = {}

    def store(self, record: EvidenceRecord) -> str:
        """Store an evidence record.

        Args:
            record: The evidence record to store.

        Returns:
            The evidence_ref of the stored record.

        Raises:
            ValueError: If evidence_ref is empty.
        """
        if not record.evidence_ref:
            raise ValueError("evidence_ref must not be empty")
        self._records[record.evidence_ref] = record
        self._by_action.setdefault(record.action_id, []).append(
            record.evidence_ref
        )
        return record.evidence_ref

    def get(self, evidence_ref: str) -> EvidenceRecord | None:
        """Retrieve a single evidence record by ref.

        Args:
            evidence_ref: The unique evidence reference.

        Returns:
            The evidence record, or None if not found.
        """
        return self._records.get(evidence_ref)

    def get_by_action(self, action_id: str) -> list[EvidenceRecord]:
        """Retrieve all evidence records for an action.

        Args:
            action_id: The action identifier.

        Returns:
            List of evidence records, possibly empty.
        """
        refs = self._by_action.get(action_id, [])
        return [self._records[r] for r in refs if r in self._records]

    def count(self) -> int:
        """Return total number of stored evidence records."""
        return len(self._records)
