"""Unit tests for incident+runbook chained command helper."""

from __future__ import annotations

from hi_agent.management.incident_runbook_commands import (
    cmd_incident_generate_and_runbook,
)


def test_cmd_incident_generate_and_runbook_returns_all_sections() -> None:
    """Chained command should include report/incident/runbook sections."""
    payload = cmd_incident_generate_and_runbook(
        signals={
            "has_temporal_risk": True,
            "has_reconcile_pressure": True,
            "has_gate_pressure": False,
        },
        alerts=[{"severity": "critical", "message": "runtime degraded"}],
        slo={"success_target_met": False, "latency_target_met": False},
        actor="ops-user",
        now_ts=1000.0,
    )

    assert payload["command"] == "incident_generate_and_runbook"
    assert payload["report"]["severity"] == "high"
    assert payload["incident"]["status"] == "open"
    assert payload["runbook"]["steps"]
