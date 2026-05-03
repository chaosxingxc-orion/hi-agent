"""Command wrappers around operational snapshot store.

W32 Track B Gap 2: ``cmd_ops_snapshot_latest`` and ``cmd_ops_snapshot_list``
now require ``tenant_id`` so the underlying store filters per
``(tenant_id, run_id)`` and cannot leak snapshots across tenants.
"""

from __future__ import annotations

from typing import Any

from hi_agent.management.ops_snapshot_store import OpsSnapshotStore


def cmd_ops_snapshot_put(store: OpsSnapshotStore, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Insert one snapshot and return command payload.

    The ``snapshot`` dict must carry both ``run_id`` and ``tenant_id``.
    """
    _validate_store(store)
    stored = store.append(snapshot)
    return {"command": "ops_snapshot_put", "snapshot": stored}


def cmd_ops_snapshot_latest(
    store: OpsSnapshotStore, run_id: str, tenant_id: str
) -> dict[str, Any]:
    """Return latest snapshot for a ``(tenant_id, run_id)`` pair.

    Args:
        store: Snapshot store.
        run_id: Run identifier.
        tenant_id: Tenant identifier — required to prevent cross-tenant
            snapshot leakage (W32 Track B Gap 2).
    """
    _validate_store(store)
    latest = store.latest(run_id, tenant_id)
    return {
        "command": "ops_snapshot_latest",
        "run_id": run_id,
        "tenant_id": tenant_id,
        "found": latest is not None,
        "snapshot": latest,
    }


def cmd_ops_snapshot_list(
    store: OpsSnapshotStore, run_id: str, tenant_id: str
) -> dict[str, Any]:
    """Return all snapshots for a ``(tenant_id, run_id)`` pair.

    Args:
        store: Snapshot store.
        run_id: Run identifier.
        tenant_id: Tenant identifier — required to prevent cross-tenant
            snapshot leakage (W32 Track B Gap 2).
    """
    _validate_store(store)
    snapshots = store.list_run(run_id, tenant_id)
    return {
        "command": "ops_snapshot_list",
        "run_id": run_id,
        "tenant_id": tenant_id,
        "count": len(snapshots),
        "snapshots": snapshots,
    }


def _validate_store(store: object) -> None:
    """Run _validate_store."""
    if not isinstance(store, OpsSnapshotStore):
        raise TypeError("store must be an OpsSnapshotStore")
