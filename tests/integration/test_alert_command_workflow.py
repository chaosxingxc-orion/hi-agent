"""Integration workflow for alert command helpers."""

from __future__ import annotations

from hi_agent.management import cmd_alerts_ack, cmd_alerts_from_signals


def test_alert_command_workflow_builds_and_acks_alert() -> None:
    """Signals should produce alert rows and support deterministic ack."""
    payload = cmd_alerts_from_signals(
        {
            "has_temporal_risk": True,
            "has_reconcile_pressure": False,
            "has_gate_pressure": True,
        },
        severity_map={"gate_pressure": "info"},
    )
    assert payload["count"] == 2
    assert payload["alerts"][0]["code"] == "temporal_risk"
    assert payload["alerts"][1]["severity"] == "info"

    ack = cmd_alerts_ack(payload["alerts"][0]["id"], "ops", now_fn=lambda: 456.0)
    assert ack["status"] == "acknowledged"
    assert ack["acked_at"] == 456.0
