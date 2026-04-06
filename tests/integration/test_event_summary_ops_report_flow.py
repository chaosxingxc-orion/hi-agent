"""Integration flow for runtime event summary feeding ops report generation."""

from __future__ import annotations

from hi_agent.management.operational_signals import build_operational_signals
from hi_agent.management.ops_report_commands import cmd_ops_build_report
from hi_agent.runtime_adapter.event_summary_commands import (
    cmd_event_summary_get,
    cmd_event_summary_ingest,
)
from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore


def test_event_summary_can_drive_ops_report_severity_transitions() -> None:
    """Event summaries should produce stable low/high severity report outcomes."""
    store = EventSummaryStore()

    # Scenario A: healthy runtime events -> low severity.
    low_events = [
        {"type": "StageStateChanged", "timestamp": 1.0, "run_id": "run-low"},
        {"type": "ActionExecuted", "timestamp": 2.0, "run_id": "run-low"},
        {"type": "StageStateChanged", "timestamp": 3.0, "run_id": "run-low"},
    ]
    cmd_event_summary_ingest(store, "run-low", low_events)
    low_summary = cmd_event_summary_get(store, "run-low")["summary"]
    low_signals = build_operational_signals(
        reconcile_backlog=low_summary["counts_by_type"].get("ActionExecutionFailed", 0),
        reconcile_backlog_threshold=1,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        temporal_health={"state": "healthy", "healthy": True},
    )
    low_report = cmd_ops_build_report(
        readiness={"ready": True},
        signals=low_signals,
        alerts=[],
        slo={"success_target_met": True, "latency_target_met": True},
        now_ts=100.0,
    )
    assert low_report["dashboard"]["status_badge"] == "green"
    assert low_report["incident"]["severity"] == "low"

    # Scenario B: failed runtime events + temporal risk + critical alert -> high severity.
    high_events = [
        {"type": "ActionExecutionFailed", "timestamp": 10.0, "run_id": "run-high"},
        {"type": "ActionExecutionFailed", "timestamp": 12.0, "run_id": "run-high"},
        {"type": "RecoveryTriggered", "timestamp": 13.0, "run_id": "run-high"},
    ]
    cmd_event_summary_ingest(store, "run-high", high_events)
    high_summary = cmd_event_summary_get(store, "run-high")["summary"]
    high_signals = build_operational_signals(
        reconcile_backlog=high_summary["counts_by_type"].get("ActionExecutionFailed", 0),
        reconcile_backlog_threshold=1,
        recent_reconcile_failures=1,
        pending_gate_count=1,
        has_stale_gates=True,
        temporal_health={"state": "unreachable", "healthy": False},
    )
    high_report = cmd_ops_build_report(
        readiness={"ready": False},
        signals=high_signals,
        alerts=[{"severity": "critical", "code": "runtime_failure"}],
        slo={"success_target_met": False, "latency_target_met": False},
        now_ts=200.0,
    )
    assert high_report["dashboard"]["status_badge"] == "red"
    assert high_report["incident"]["severity"] == "high"
    assert high_report["incident"]["service"] == "hi-agent"
