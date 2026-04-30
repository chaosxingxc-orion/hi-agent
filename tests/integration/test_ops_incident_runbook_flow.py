"""Integration test for ops signals -> incident report -> runbook flow."""

from __future__ import annotations

from hi_agent.management.alerts import evaluate_operational_alerts
from hi_agent.management.incident_report import build_incident_report
from hi_agent.management.operational_signals import build_operational_signals
from hi_agent.management.runbook import build_incident_runbook
from hi_agent.management.slo import build_slo_snapshot


def test_ops_incident_runbook_flow_builds_actionable_plan() -> None:
    """Pressured ops state should produce high/medium incident and non-empty steps."""
    signals = build_operational_signals(
        reconcile_backlog=40,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=2,
        pending_gate_count=2,
        has_stale_gates=True,
        temporal_health={"state": "degraded", "healthy": False},
    )
    alerts = evaluate_operational_alerts(signals)
    slo = build_slo_snapshot(
        run_success_rate=0.90,
        latency_p95_ms=8000.0,
        success_target=0.99,
        latency_target_ms=5000.0,
    )
    report = build_incident_report(
        signals=signals,
        alerts=alerts,
        slo_snapshot={
            "success_target_met": slo.success_target_met,
            "latency_target_met": slo.latency_target_met,
        },
        now_ts=1710000000.0,
        service="hi-agent",
    )
    runbook = build_incident_runbook(report, max_steps=6)

    assert report["severity"] == "high"
    assert runbook["severity"] == report["severity"]
    assert runbook["steps"]
    assert runbook["title"].startswith("hi-agent")
