"""Integration test for operational dashboard assembly flow."""

from __future__ import annotations

from hi_agent.management.health import build_operational_readiness_report
from hi_agent.management.operational_dashboard import build_operational_dashboard_payload
from hi_agent.management.operational_signals import build_operational_signals


def test_operational_dashboard_flow_from_signals_and_readiness() -> None:
    """Signals + readiness should produce a consistent dashboard payload."""
    signals = build_operational_signals(
        reconcile_backlog=2,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        temporal_health={"state": "healthy", "healthy": True},
    )
    readiness = build_operational_readiness_report(
        dependencies={"runtime": True},
        recent_error_count=0,
        reconcile_backlog=2,
        recent_reconcile_failures=0,
        reconcile_backlog_threshold=10,
    )
    payload = build_operational_dashboard_payload(
        readiness_report=readiness,
        operational_signals=signals,
    )

    assert payload["summary"]["ready"] is True
    assert payload["status_badge"] == "green"


def test_operational_dashboard_badge_transitions_and_metadata_propagation() -> None:
    """Dashboard badge should transition green->yellow->red and preserve metadata."""
    readiness_ready = build_operational_readiness_report(
        dependencies={"runtime": True},
        recent_error_count=0,
        reconcile_backlog=1,
        recent_reconcile_failures=0,
        reconcile_backlog_threshold=10,
    )

    green_signals = build_operational_signals(
        reconcile_backlog=1,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        temporal_health={"state": "healthy", "healthy": True},
    )
    green_payload = build_operational_dashboard_payload(
        readiness_report=readiness_ready,
        operational_signals=green_signals,
        metadata={"cluster": "cn-sh-1", "env": "staging"},
    )
    assert green_payload["status_badge"] == "green"
    assert green_payload["metadata"] == {"cluster": "cn-sh-1", "env": "staging"}

    yellow_signals = build_operational_signals(
        reconcile_backlog=10,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        temporal_health={"state": "healthy", "healthy": True},
    )
    yellow_payload = build_operational_dashboard_payload(
        readiness_report=readiness_ready,
        operational_signals=yellow_signals,
        temporal_health={"state": "degraded", "healthy": True},
    )
    assert yellow_payload["status_badge"] == "yellow"

    red_signals = build_operational_signals(
        reconcile_backlog=2,
        reconcile_backlog_threshold=10,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        temporal_health={"state": "unreachable", "healthy": False},
    )
    red_payload = build_operational_dashboard_payload(
        readiness_report=readiness_ready,
        operational_signals=red_signals,
        temporal_health={"state": "unreachable", "healthy": False},
        metadata={"ticket": "INC-42"},
    )
    assert red_payload["status_badge"] == "red"
    assert red_payload["signals"]["has_temporal_risk"] is True
    assert red_payload["metadata"]["ticket"] == "INC-42"
