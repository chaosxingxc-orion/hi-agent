"""In-memory append-only store for operational snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class OpsSnapshotStore:
    """Append-only operational snapshot store."""

    def __init__(self) -> None:
        """Initialize empty snapshot list."""
        self._entries: list[dict[str, Any]] = []

    def append(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Append one snapshot and return a defensive copy of stored payload."""
        normalized = self._normalize_snapshot(snapshot)
        self._entries.append(normalized)
        return deepcopy(normalized)

    def latest(self, run_id: str) -> dict[str, Any] | None:
        """Return latest snapshot by timestamp for one run."""
        normalized_run_id = self._normalize_run_id(run_id)
        best: dict[str, Any] | None = None
        best_ts = float("-inf")
        for item in self._entries:
            if item["run_id"] != normalized_run_id:
                continue
            ts = float(item["timestamp"])
            if ts >= best_ts:
                best = item
                best_ts = ts
        return None if best is None else deepcopy(best)

    def list_run(self, run_id: str) -> list[dict[str, Any]]:
        """List snapshots for one run sorted by timestamp ascending."""
        normalized_run_id = self._normalize_run_id(run_id)
        matched = [item for item in self._entries if item["run_id"] == normalized_run_id]
        matched.sort(key=lambda item: float(item["timestamp"]))
        return deepcopy(matched)

    def list_all(self, limit: int | None = None) -> list[dict[str, Any]]:
        """List all snapshots sorted by timestamp descending with optional limit."""
        if limit is not None and limit <= 0:
            raise ValueError("limit must be > 0 when provided")
        ordered = sorted(self._entries, key=lambda item: float(item["timestamp"]), reverse=True)
        if limit is not None:
            ordered = ordered[:limit]
        return deepcopy(ordered)

    def _normalize_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot must be a dict")
        run_id = self._normalize_run_id(snapshot.get("run_id", ""))
        timestamp_raw = snapshot.get("timestamp")
        if not isinstance(timestamp_raw, int | float):
            raise ValueError("snapshot.timestamp must be int or float")
        normalized = deepcopy(snapshot)
        normalized["run_id"] = run_id
        normalized["timestamp"] = float(timestamp_raw)
        return normalized

    def _normalize_run_id(self, run_id: str) -> str:
        if not isinstance(run_id, str):
            raise ValueError("run_id must be a string")
        normalized = run_id.strip()
        if not normalized:
            raise ValueError("run_id must be a non-empty string")
        return normalized
