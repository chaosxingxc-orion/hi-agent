"""Tests for ops report command helpers."""

from __future__ import annotations

import pytest
from hi_agent.management.ops_report_commands import (
    cmd_ops_build_report,
    cmd_ops_build_runbook,
)


def test_cmd_ops_build_report_returns_stable_payload() -> None:
    """Report command should include dashboard + incident sections."""
    readiness = {"ready": False}
    signals = {
        "overall_pressure": True,
        "has_temporal_risk": True,
        "has_reconcile_pressure": True,
        "has_gate_pressure": False,
    }
    alerts = [{"severity": "critical", "code": "temporal_risk"}]
    slo = {"success_target_met": False, "latency_target_met": True}

    payload = cmd_ops_build_report(readiness, signals, alerts, slo, now_ts=123.0)

    assert payload["command"] == "ops_build_report"
    assert payload["generated_at"] == 123.0
    assert payload["dashboard"]["status_badge"] == "red"
    assert payload["incident"]["severity"] == "high"


def test_cmd_ops_build_runbook_returns_steps() -> None:
    """Runbook command should derive non-empty action steps."""
    report = {
        "summary_title": "incident-x",
        "severity": "medium",
        "recommendations": ["Investigate backlog.", "Check temporal health."],
    }

    payload = cmd_ops_build_runbook(report)
    runbook = payload["runbook"]
    assert payload["command"] == "ops_build_runbook"
    assert runbook["severity"] == "medium"
    assert runbook["owner_hint"] == "oncall-engineer"
    assert len(runbook["steps"]) >= 2


def test_cmd_ops_build_report_validates_input_types() -> None:
    """Invalid input types should raise deterministic TypeError."""
    with pytest.raises(TypeError):
        cmd_ops_build_report(  # type: ignore[arg-type]  expiry_wave: Wave 29
            readiness=[],
            signals={},
            alerts=[],
            slo={},
            now_ts=1.0,
        )
    with pytest.raises(TypeError):
        cmd_ops_build_runbook([])  # type: ignore[arg-type]  expiry_wave: Wave 29
