"""Unit tests for ops governance command wrapper."""

from __future__ import annotations

from hi_agent.management.ops_governance_commands import cmd_ops_governance_check


def test_cmd_ops_governance_check_returns_command_payload() -> None:
    """Command wrapper should expose governance decision payload."""
    payload = cmd_ops_governance_check(
        readiness={"ready": False},
        signals={"overall_pressure": True},
        slo_snapshot={"success_target_met": True, "latency_target_met": True},
        alert_count=1,
    )
    assert payload["command"] == "ops_governance_check"
    assert payload["decision"]["require_incident"] is True
