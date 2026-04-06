"""Integration flow for ops snapshot command composition."""

from __future__ import annotations

from hi_agent.management.ops_commands import cmd_ops_snapshot


def test_ops_snapshot_flow_contains_coherent_sections() -> None:
    """Composed snapshot should expose coherent dashboard/alerts/slo sections."""
    payload = cmd_ops_snapshot(
        dependencies={"runtime": True, "store": True},
        recent_error_count=0,
        reconcile_backlog=1,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        metrics={"run_success_rate": 0.999, "latency_p95_ms": 800},
        slo_objective={"success_target": 0.99, "latency_target_ms": 1500},
        temporal_health={"state": "healthy", "healthy": True},
        metadata={"env": "ci"},
    )

    assert payload["command"] == "ops_snapshot"
    assert payload["dashboard"]["summary"]["badge"] == payload["dashboard"]["status_badge"]
    assert payload["alerts"]["command"] == "alerts_from_signals"
    assert payload["slo"]["command"] == "slo_evaluate"
