"""Integration test for operational signals, dashboard payload, alerts, and SLO."""

from __future__ import annotations

from hi_agent.management.alerts import evaluate_operational_alerts
from hi_agent.management.operational_dashboard import build_operational_dashboard_payload
from hi_agent.management.operational_signals import build_operational_signals
from hi_agent.management.slo import build_slo_snapshot


def test_ops_signal_alert_slo_flow_for_pressured_system() -> None:
    """Pressured inputs should produce red/yellow dashboard and failing SLO."""
    signals = build_operational_signals(
        reconcile_backlog=30,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=2,
        pending_gate_count=3,
        has_stale_gates=True,
        temporal_health={"state": "degraded", "healthy": False},
    )
    dashboard = build_operational_dashboard_payload(
        readiness_report={"ready": False, "dependencies": {"runtime": True}},
        operational_signals=signals,
        temporal_health={"state": "degraded", "healthy": False},
        metadata={"env": "test"},
    )
    alerts = evaluate_operational_alerts(signals)
    slo = build_slo_snapshot(
        run_success_rate=0.92,
        latency_p95_ms=9000.0,
        success_target=0.99,
        latency_target_ms=5000.0,
    )

    assert dashboard["status_badge"] in {"red", "yellow"}
    assert dashboard["summary"]["badge"] in {"red", "yellow"}
    assert dashboard["metadata"]["env"] == "test"
    assert alerts
    assert any(row["severity"] in {"warning", "critical"} for row in alerts)
    assert slo.success_target_met is False
    assert slo.latency_target_met is False
