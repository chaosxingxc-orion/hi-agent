"""In-memory store for route decision audit records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class InMemoryDecisionAuditStore:
    """Append-only in-memory store for route decision audits.

    The store keeps insertion order stable to guarantee deterministic replay in
    tests and local workflows.
    """

    def __init__(self) -> None:
        """Initialize an empty append-only audit list."""
        self._items: list[dict[str, Any]] = []

    def append(self, audit: Mapping[str, Any]) -> dict[str, Any]:
        """Append one normalized audit record and return a defensive copy."""
        if not isinstance(audit, Mapping):
            raise TypeError("audit must be a mapping")
        run_id = self._normalize_required_str(audit.get("run_id"), "run_id")
        stage_id = self._normalize_required_str(audit.get("stage_id"), "stage_id")

        normalized = dict(audit)
        normalized["run_id"] = run_id
        normalized["stage_id"] = stage_id
        self._items.append(normalized)
        return dict(normalized)

    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return audits for one run in insertion order."""
        normalized_run_id = self._normalize_required_str(run_id, "run_id")
        return [dict(item) for item in self._items if item["run_id"] == normalized_run_id]

    def latest_by_stage(self, run_id: str, stage_id: str) -> dict[str, Any] | None:
        """Return latest audit for (run_id, stage_id), or ``None`` if missing."""
        normalized_run_id = self._normalize_required_str(run_id, "run_id")
        normalized_stage_id = self._normalize_required_str(stage_id, "stage_id")
        for item in reversed(self._items):
            if item["run_id"] == normalized_run_id and item["stage_id"] == normalized_stage_id:
                return dict(item)
        return None

    def _normalize_required_str(self, value: object, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a non-empty string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} must be a non-empty string")
        return normalized

