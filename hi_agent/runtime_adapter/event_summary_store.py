"""In-memory runtime event summary store."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class EventSummaryStore:
    """Store summarized runtime event payloads keyed by run ID."""

    def __init__(self) -> None:
        """Initialize empty in-memory summary index."""
        self._summaries: dict[str, dict[str, Any]] = {}

    def put_summary(self, run_id: str, summary: dict[str, Any]) -> None:
        """Store or replace one run summary using defensive copy-on-write."""
        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(summary, dict):
            raise ValueError("summary must be a dict")
        self._summaries[normalized_run_id] = deepcopy(summary)

    def get_summary(self, run_id: str) -> dict[str, Any] | None:
        """Return one run summary using defensive copy-on-read."""
        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id must be a non-empty string")
        summary = self._summaries.get(normalized_run_id)
        if summary is None:
            return None
        return deepcopy(summary)

    def list_runs(self) -> list[str]:
        """Return stored run IDs in deterministic sorted order."""
        return sorted(self._summaries.keys())
