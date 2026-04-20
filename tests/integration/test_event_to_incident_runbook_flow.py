"""End-to-end flow from runtime events to incident + runbook."""

from __future__ import annotations

import hi_agent.management.incident_runbook_commands as incident_commands
import hi_agent.runtime_adapter.event_signals_bridge as event_bridge
from hi_agent.management.alerts import evaluate_operational_alerts
from hi_agent.management.slo import build_slo_snapshot
from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events


def test_event_to_incident_runbook_flow() -> None:
    """Runtime events should propagate to incident payload and runbook steps."""
    events = [
        {"type": "ActionExecuted", "timestamp": 1000.0, "run_id": "run-ops-1"},
        {"type": "ActionExecutionFailed", "timestamp": 1001.0, "run_id": "run-ops-1"},
        {"type": "RecoveryTriggered", "timestamp": 1002.0, "run_id": "run-ops-1"},
        {"type": "RecoveryCompleted", "timestamp": 1003.0, "run_id": "run-ops-1"},
    ]
    summary = summarize_runtime_events(events)
    signals = event_bridge.build_signals_from_event_summary(summary, backlog_threshold=1)
    alerts = evaluate_operational_alerts(signals)
    slo = build_slo_snapshot(
        run_success_rate=0.6,
        latency_p95_ms=1800.0,
        success_target=0.95,
        latency_target_ms=1200.0,
    )

    payload = incident_commands.cmd_incident_generate_and_runbook(
        signals=signals,
        alerts=alerts,
        slo=slo,
        actor="ops-user",
        now_ts=2000.0,
    )

    assert payload["incident"]["incident_id"]
    assert payload["incident"]["status"] == "open"
    assert payload["runbook"]["steps"]
    assert payload["report"]["severity"] in {"medium", "high"}
