"""Integration flow for ops snapshot store and timeline commands."""

from __future__ import annotations

from hi_agent.management.ops_snapshot_commands import (
    cmd_ops_snapshot_latest,
    cmd_ops_snapshot_list,
    cmd_ops_snapshot_put,
)
from hi_agent.management.ops_snapshot_store import OpsSnapshotStore
from hi_agent.management.ops_timeline_commands import (
    cmd_ops_timeline_build,
    cmd_ops_timeline_slice,
)


def test_ops_snapshot_and_timeline_commands_flow() -> None:
    """Commands should compose into stable snapshot/timeline flow."""
    store = OpsSnapshotStore()
    cmd_ops_snapshot_put(store, {"run_id": "run-1", "timestamp": 10.0, "state": "ok"})
    cmd_ops_snapshot_put(store, {"run_id": "run-1", "timestamp": 20.0, "state": "warn"})

    latest = cmd_ops_snapshot_latest(store, "run-1")
    assert latest["found"] is True
    assert latest["snapshot"]["state"] == "warn"

    listed = cmd_ops_snapshot_list(store, "run-1")
    assert listed["count"] == 2

    timeline_payload = cmd_ops_timeline_build(
        events=[{"timestamp": 5.0, "type": "boot"}],
        audits=[{"timestamp": 15.0, "type": "audit"}],
        incidents=[{"timestamp": 25.0, "type": "incident"}],
    )
    assert timeline_payload["count"] == 3

    sliced = cmd_ops_timeline_slice(timeline_payload["timeline"], start_ts=10.0, end_ts=25.0)
    assert sliced["count"] == 2
    assert [row["ts"] for row in sliced["timeline"]] == [15.0, 25.0]
