"""Round-3 package export coverage tests."""

from __future__ import annotations

from hi_agent.management import (
    build_incident_report,
    cmd_incident_close,
    cmd_incident_create,
    cmd_slo_burn_rate,
    cmd_slo_evaluate,
)
from hi_agent.route_engine import InMemoryDecisionAuditStore
from hi_agent.runtime_adapter import EventSummaryStore, summarize_runtime_events


def test_management_exports_slo_commands() -> None:
    """Management package should export SLO command helpers."""
    payload = cmd_slo_burn_rate(0.9, 2.0)
    assert payload["command"] == "slo_burn_rate"
    assert callable(cmd_slo_evaluate)
    assert callable(build_incident_report)
    assert callable(cmd_incident_create)
    assert callable(cmd_incident_close)


def test_route_engine_exports_decision_audit_store() -> None:
    """Route engine package should export audit store."""
    store = InMemoryDecisionAuditStore()
    store.append({"run_id": "r1", "stage_id": "S1", "engine": "rule"})
    assert store.latest_by_stage("r1", "S1") is not None


def test_runtime_adapter_exports_event_summary_store() -> None:
    """Runtime adapter package should export summary store and summarizer."""
    store = EventSummaryStore()
    store.put_summary("r1", {"total_events": 1})
    assert store.get_summary("r1") == {"total_events": 1}
    assert callable(summarize_runtime_events)
