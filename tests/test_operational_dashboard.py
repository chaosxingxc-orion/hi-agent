"""Tests for operational dashboard payload helpers."""

from __future__ import annotations

from hi_agent.management.operational_dashboard import build_operational_dashboard_payload


def test_operational_dashboard_payload_green_when_ready_and_no_pressure() -> None:
    """Badge should be green when system is ready with no pressure signals."""
    payload = build_operational_dashboard_payload(
        readiness_report={"ready": True, "recent_error_count": 0},
        operational_signals={"overall_pressure": False, "has_temporal_risk": False},
    )
    assert payload["status_badge"] == "green"
    assert payload["summary"]["badge"] == "green"


def test_operational_dashboard_payload_yellow_when_pressure_present() -> None:
    """Badge should be yellow for pressure while still ready."""
    payload = build_operational_dashboard_payload(
        readiness_report={"ready": True},
        operational_signals={"overall_pressure": True, "has_temporal_risk": False},
        temporal_health={"state": "degraded"},
    )
    assert payload["status_badge"] == "yellow"


def test_operational_dashboard_payload_red_when_not_ready_or_temporal_risky() -> None:
    """Badge should be red if readiness fails or temporal health is risky."""
    payload = build_operational_dashboard_payload(
        readiness_report={"ready": False},
        operational_signals={"overall_pressure": True, "has_temporal_risk": True},
        temporal_health={"state": "unreachable"},
    )
    assert payload["status_badge"] == "red"


def test_operational_dashboard_payload_handles_missing_optional_sections() -> None:
    """Missing temporal/metadata should produce stable empty sections."""
    payload = build_operational_dashboard_payload(
        readiness_report={"ready": True},
        operational_signals={"overall_pressure": False, "has_temporal_risk": False},
    )
    assert payload["temporal"] == {}
    assert payload["metadata"] == {}

