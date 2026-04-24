"""Tests for high-level ops command wrapper."""

from __future__ import annotations

from hi_agent.management.ops_commands import cmd_ops_snapshot


def test_cmd_ops_snapshot_builds_dashboard_alerts_and_slo() -> None:
    """Snapshot command should return composed sections consistently."""
    payload = cmd_ops_snapshot(
        dependencies={"runtime": True, "db": True},
        recent_error_count=0,
        reconcile_backlog=3,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        metrics={"run_success_rate": 0.995, "latency_p95_ms": 1200},
        slo_objective={"success_target": 0.99, "latency_target_ms": 2000},
        temporal_health={"state": "healthy", "healthy": True},
        metadata={"cluster": "test"},
    )

    assert payload["command"] == "ops_snapshot"
    assert payload["dashboard"]["status_badge"] == "green"
    assert payload["alerts"]["count"] == 0
    assert payload["slo"]["passed"] is True


def test_cmd_ops_snapshot_reports_pressure_for_bad_inputs() -> None:
    """Pressure inputs should produce non-green dashboard and failing slo."""
    payload = cmd_ops_snapshot(
        dependencies={"runtime": False},
        recent_error_count=2,
        reconcile_backlog=50,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=2,
        pending_gate_count=1,
        has_stale_gates=True,
        metrics={"run_success_rate": 0.80, "latency_p95_ms": 9000},
        slo_objective={"success_target": 0.99, "latency_target_ms": 2000},
        temporal_health={"state": "unreachable", "healthy": False},
    )

    assert payload["dashboard"]["status_badge"] == "red"
    assert payload["alerts"]["count"] >= 1
    assert payload["slo"]["passed"] is False
