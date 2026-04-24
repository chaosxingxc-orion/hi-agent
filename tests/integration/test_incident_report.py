"""Tests for incident report severity and payload composition."""

from __future__ import annotations

from hi_agent.management.incident_report import build_incident_report


def test_build_incident_report_low_severity_when_system_is_healthy() -> None:
    """Healthy signals and SLO should produce low severity report."""
    report = build_incident_report(
        signals={
            "has_temporal_risk": False,
            "has_reconcile_pressure": False,
            "has_gate_pressure": False,
        },
        alerts=[],
        slo_snapshot={
            "success_target_met": True,
            "latency_target_met": True,
        },
        now_ts=100.0,
    )

    assert report["severity"] == "low"
    assert "low" in report["summary_title"]
    assert report["recommendations"] == [
        "No immediate action required; continue routine monitoring."
    ]


def test_build_incident_report_medium_severity_for_warning_pressure() -> None:
    """Warning pressure with no critical conditions should produce medium severity."""
    report = build_incident_report(
        signals={
            "has_temporal_risk": False,
            "has_reconcile_pressure": True,
            "has_gate_pressure": False,
        },
        alerts=[{"severity": "warning", "code": "reconcile_pressure"}],
        slo_snapshot={
            "success_target_met": True,
            "latency_target_met": False,
        },
        now_ts=101.0,
        service="trace-worker",
    )

    assert report["severity"] == "medium"
    assert report["service"] == "trace-worker"
    assert any("reconcile" in item for item in report["recommendations"])


def test_build_incident_report_high_severity_for_critical_or_temporal_risk() -> None:
    """Temporal risk or critical alerts should escalate severity to high."""
    report = build_incident_report(
        signals={
            "has_temporal_risk": True,
            "has_reconcile_pressure": True,
            "has_gate_pressure": True,
        },
        alerts=[{"severity": "critical", "code": "temporal_risk"}],
        slo_snapshot={
            "success_target_met": False,
            "latency_target_met": False,
        },
        now_ts=102.0,
    )

    assert report["severity"] == "high"
    assert any("connectivity" in item.lower() for item in report["recommendations"])
    assert "critical_alerts=1" in report["key_facts"]
