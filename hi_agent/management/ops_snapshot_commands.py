"""Command wrappers around operational snapshot store."""

from __future__ import annotations

from typing import Any

from hi_agent.management.ops_snapshot_store import OpsSnapshotStore


def cmd_ops_snapshot_put(store: OpsSnapshotStore, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Insert one snapshot and return command payload."""
    _validate_store(store)
    stored = store.append(snapshot)
    return {"command": "ops_snapshot_put", "snapshot": stored}


def cmd_ops_snapshot_latest(store: OpsSnapshotStore, run_id: str) -> dict[str, Any]:
    """Return latest snapshot for a run."""
    _validate_store(store)
    latest = store.latest(run_id)
    return {
        "command": "ops_snapshot_latest",
        "run_id": run_id,
        "found": latest is not None,
        "snapshot": latest,
    }


def cmd_ops_snapshot_list(store: OpsSnapshotStore, run_id: str) -> dict[str, Any]:
    """Return all snapshots for a run."""
    _validate_store(store)
    snapshots = store.list_run(run_id)
    return {
        "command": "ops_snapshot_list",
        "run_id": run_id,
        "count": len(snapshots),
        "snapshots": snapshots,
    }


def _validate_store(store: object) -> None:
    if not isinstance(store, OpsSnapshotStore):
        raise TypeError("store must be an OpsSnapshotStore")
