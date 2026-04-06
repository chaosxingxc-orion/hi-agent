"""Failure collector for aggregating and analyzing failures during a run."""

from typing import Any

from hi_agent.failures.taxonomy import (
    FailureCode,
    FailureRecord,
    FAILURE_GATE_MAP,
)


class FailureCollector:
    """Collects failures during run execution for analysis and evolve feedback."""

    def __init__(self) -> None:
        self._records: list[FailureRecord] = []

    def record(self, failure: FailureRecord) -> None:
        """Add a failure record to the collection."""
        self._records.append(failure)

    def get_all(self) -> list[FailureRecord]:
        """Return all collected failure records."""
        return list(self._records)

    def get_by_code(self, code: FailureCode) -> list[FailureRecord]:
        """Return failures matching a specific failure code."""
        return [r for r in self._records if r.failure_code == code]

    def get_by_stage(self, stage_id: str) -> list[FailureRecord]:
        """Return failures from a specific stage."""
        return [r for r in self._records if r.stage_id == stage_id]

    def get_unresolved(self) -> list[FailureRecord]:
        """Return all unresolved failure records."""
        return [r for r in self._records if not r.resolved]

    def mark_resolved(self, index: int) -> None:
        """Mark a failure record as resolved by its index."""
        if 0 <= index < len(self._records):
            self._records[index].resolved = True

    def get_failure_codes(self) -> list[str]:
        """Return unique failure code strings (for postmortem)."""
        seen: set[str] = set()
        result: list[str] = []
        for r in self._records:
            code_val = r.failure_code.value
            if code_val not in seen:
                seen.add(code_val)
                result.append(code_val)
        return result

    def get_summary(self) -> dict[str, Any]:
        """Return failure summary: counts by code, stage distribution, resolution rate."""
        total = len(self._records)
        resolved = sum(1 for r in self._records if r.resolved)

        counts_by_code: dict[str, int] = {}
        for r in self._records:
            key = r.failure_code.value
            counts_by_code[key] = counts_by_code.get(key, 0) + 1

        stage_distribution: dict[str, int] = {}
        for r in self._records:
            if r.stage_id:
                stage_distribution[r.stage_id] = stage_distribution.get(r.stage_id, 0) + 1

        return {
            "total": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "resolution_rate": resolved / total if total > 0 else 0.0,
            "counts_by_code": counts_by_code,
            "stage_distribution": stage_distribution,
        }

    def suggests_gate(self) -> str | None:
        """Check if any unresolved failure suggests a Human Gate.

        Returns gate type or None.
        """
        for r in self._records:
            if not r.resolved:
                gate = FAILURE_GATE_MAP.get(r.failure_code)
                if gate is not None:
                    return gate
        return None
