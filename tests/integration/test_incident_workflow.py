"""Integration flow for incident report and command helpers."""

from __future__ import annotations

from hi_agent.management import build_incident_report, cmd_incident_close, cmd_incident_create


def test_incident_report_to_open_and_close_commands_flow() -> None:
    """Incident report should produce open/close command payloads."""
    report = build_incident_report(
        signals={
            "has_temporal_risk": True,
            "has_reconcile_pressure": False,
            "has_gate_pressure": False,
        },
        alerts=[{"severity": "critical", "message": "runtime down"}],
        slo_snapshot={"success_target_met": False, "latency_target_met": False},
        now_ts=100.0,
        service="hi-agent",
    )
    open_payload = cmd_incident_create(report, actor="ops", channel="pager")
    close_payload = cmd_incident_close(open_payload["incident_id"], actor="ops", reason="mitigated")

    assert open_payload["status"] == "open"
    assert close_payload["status"] == "closed"
    assert close_payload["incident_id"] == open_payload["incident_id"]
