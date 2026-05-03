"""In-memory append-only store for operational snapshots.

W32 Track B Gap 2: snapshots are keyed by ``(tenant_id, run_id)`` to prevent
cross-tenant collisions when two tenants happen to issue identical run_ids.
``latest()`` and ``list_run()`` filter by both fields.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class OpsSnapshotStore:
    """Append-only operational snapshot store.

    W32 Track B Gap 2: ``latest`` and ``list_run`` require ``tenant_id`` so
    snapshots are scoped per ``(tenant_id, run_id)`` instead of just by
    ``run_id``. Without this filter two tenants registering the same run_id
    would observe each other's snapshots.
    """

    def __init__(self) -> None:
        """Initialize empty snapshot list."""
        self._entries: list[dict[str, Any]] = []

    def append(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Append one snapshot and return a defensive copy of stored payload.

        The snapshot dict MUST carry both ``run_id`` and ``tenant_id`` keys.
        Missing or empty ``tenant_id`` raises ``ValueError`` so cross-tenant
        ambiguity cannot enter the store.
        """
        normalized = self._normalize_snapshot(snapshot)
        self._entries.append(normalized)
        return deepcopy(normalized)

    def latest(self, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        """Return latest snapshot by timestamp for one ``(tenant_id, run_id)`` pair.

        Args:
            run_id: Run identifier (non-empty).
            tenant_id: Tenant identifier (non-empty); enforced to prevent
                cross-tenant snapshot leakage.
        """
        normalized_run_id = self._normalize_run_id(run_id)
        normalized_tenant_id = self._normalize_tenant_id(tenant_id)
        best: dict[str, Any] | None = None
        best_ts = float("-inf")
        for item in self._entries:
            if item["run_id"] != normalized_run_id:
                continue
            if item.get("tenant_id", "") != normalized_tenant_id:
                continue
            ts = float(item["timestamp"])
            if ts >= best_ts:
                best = item
                best_ts = ts
        return None if best is None else deepcopy(best)

    def list_run(self, run_id: str, tenant_id: str) -> list[dict[str, Any]]:
        """List snapshots for one ``(tenant_id, run_id)`` pair, sorted ascending.

        Args:
            run_id: Run identifier (non-empty).
            tenant_id: Tenant identifier (non-empty); enforced to prevent
                cross-tenant snapshot leakage.
        """
        normalized_run_id = self._normalize_run_id(run_id)
        normalized_tenant_id = self._normalize_tenant_id(tenant_id)
        matched = [
            item for item in self._entries
            if item["run_id"] == normalized_run_id
            and item.get("tenant_id", "") == normalized_tenant_id
        ]
        matched.sort(key=lambda item: float(item["timestamp"]))
        return deepcopy(matched)

    def list_all(self, limit: int | None = None) -> list[dict[str, Any]]:
        """List all snapshots sorted by timestamp descending with optional limit.

        Note: this is an admin-only escape hatch — it does NOT filter by
        tenant_id. It must not appear on tenant-scoped public paths.
        """
        if limit is not None and limit <= 0:
            raise ValueError("limit must be > 0 when provided")
        ordered = sorted(self._entries, key=lambda item: float(item["timestamp"]), reverse=True)
        if limit is not None:
            ordered = ordered[:limit]
        return deepcopy(ordered)

    def _normalize_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Run _normalize_snapshot."""
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot must be a dict")
        run_id = self._normalize_run_id(snapshot.get("run_id", ""))
        tenant_id = self._normalize_tenant_id(snapshot.get("tenant_id", ""))
        timestamp_raw = snapshot.get("timestamp")
        if not isinstance(timestamp_raw, int | float):
            raise ValueError("snapshot.timestamp must be int or float")
        normalized = deepcopy(snapshot)
        normalized["run_id"] = run_id
        normalized["tenant_id"] = tenant_id
        normalized["timestamp"] = float(timestamp_raw)
        return normalized

    def _normalize_run_id(self, run_id: str) -> str:
        """Run _normalize_run_id."""
        if not isinstance(run_id, str):
            raise ValueError("run_id must be a string")
        normalized = run_id.strip()
        if not normalized:
            raise ValueError("run_id must be a non-empty string")
        return normalized

    def _normalize_tenant_id(self, tenant_id: str) -> str:
        """Run _normalize_tenant_id."""
        if not isinstance(tenant_id, str):
            raise ValueError("tenant_id must be a string")
        normalized = tenant_id.strip()
        if not normalized:
            raise ValueError("tenant_id must be a non-empty string")
        return normalized
