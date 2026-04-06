"""Round-4 export surface tests."""

from __future__ import annotations


def test_management_round4_exports_available() -> None:
    """Management package should export snapshot and timeline commands."""
    from hi_agent import management as mgmt

    assert callable(mgmt.build_ops_timeline)
    assert callable(mgmt.cmd_ops_snapshot_put)
    assert callable(mgmt.cmd_ops_snapshot_latest)
    assert callable(mgmt.cmd_ops_snapshot_list)
    assert callable(mgmt.cmd_ops_timeline_build)
    assert callable(mgmt.cmd_ops_timeline_slice)
    assert mgmt.OpsSnapshotStore is not None


def test_route_and_runtime_round4_exports_available() -> None:
    """Route/runtime packages should export confidence and summary commands."""
    from hi_agent import route_engine, runtime_adapter

    assert callable(route_engine.should_escalate_route_decision)
    assert callable(runtime_adapter.cmd_event_summary_ingest)
    assert callable(runtime_adapter.cmd_event_summary_get)
    assert callable(runtime_adapter.cmd_event_summary_list_runs)
