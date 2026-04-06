"""Tests for operational alert command wrappers."""

from __future__ import annotations

import pytest
from hi_agent.management.alerts_commands import cmd_alerts_ack, cmd_alerts_from_signals


def test_cmd_alerts_from_signals_builds_open_alert_rows() -> None:
    """Command should convert active signal flags into open alert payload rows."""
    payload = cmd_alerts_from_signals(
        {
            "has_temporal_risk": True,
            "has_reconcile_pressure": True,
            "has_gate_pressure": False,
        }
    )
    assert payload["command"] == "alerts_from_signals"
    assert payload["count"] == 2
    assert payload["alerts"][0]["id"] == "temporal_risk:1"
    assert payload["alerts"][1]["id"] == "reconcile_pressure:2"
    assert all(row["status"] == "open" for row in payload["alerts"])


def test_cmd_alerts_from_signals_applies_optional_severity_map() -> None:
    """Caller-provided severity map should override default severity per code."""
    payload = cmd_alerts_from_signals(
        {"has_temporal_risk": True},
        severity_map={"temporal_risk": "warning"},
    )
    assert payload["alerts"][0]["severity"] == "warning"


def test_cmd_alerts_ack_returns_ack_payload_and_validates_inputs() -> None:
    """Ack command should include deterministic timestamp and validate strings."""
    ack = cmd_alerts_ack(" temporal_risk:1 ", " ops ", now_fn=lambda: 123.0)
    assert ack == {
        "command": "alerts_ack",
        "alert_id": "temporal_risk:1",
        "actor": "ops",
        "acked_at": 123.0,
        "status": "acknowledged",
    }

    with pytest.raises(ValueError, match="alert_id must be a non-empty string"):
        cmd_alerts_ack("  ", "ops")
    with pytest.raises(ValueError, match="actor must be a non-empty string"):
        cmd_alerts_ack("a-1", "  ")
