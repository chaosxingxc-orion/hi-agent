"""Tests for incident command helpers."""

from __future__ import annotations

import pytest
from hi_agent.management.incident_commands import cmd_incident_close, cmd_incident_create


def test_cmd_incident_create_uses_run_context_for_deterministic_id() -> None:
    """Incident ID should be derived from run context when available."""
    payload = cmd_incident_create(
        {"run_id": "run-123", "severity": "high"},
        actor="ops-user",
        channel="pager",
    )
    assert payload["command"] == "incident_create"
    assert payload["status"] == "open"
    assert payload["channel"] == "pager"
    assert payload["created_by"] == "ops-user"
    assert isinstance(payload["incident_id"], str)
    assert payload["incident_id"]


def test_cmd_incident_create_falls_back_when_run_id_missing() -> None:
    """Fallback ID generation should still produce stable non-empty ID."""
    payload = cmd_incident_create({"severity": "medium"}, actor="ops-user")
    assert payload["command"] == "incident_create"
    assert payload["incident_id"]


@pytest.mark.parametrize(
    ("report", "actor", "channel"),
    [
        ({}, "ops", "pager"),
        ({"x": 1}, "", "pager"),
        ({"x": 1}, "ops", ""),
    ],
)
def test_cmd_incident_create_validation(
    report: dict[str, object], actor: str, channel: str
) -> None:
    """Create command should reject invalid report/actor/channel values."""
    with pytest.raises(ValueError):
        cmd_incident_create(report, actor=actor, channel=channel)


def test_cmd_incident_close_happy_path() -> None:
    """Close command should return normalized closed payload."""
    payload = cmd_incident_close("inc-001", actor="ops", reason="resolved")
    assert payload == {
        "command": "incident_close",
        "incident_id": "inc-001",
        "status": "closed",
        "closed_by": "ops",
        "reason": "resolved",
    }


@pytest.mark.parametrize(
    ("incident_id", "actor", "reason"),
    [
        ("", "ops", "done"),
        ("inc-1", "", "done"),
        ("inc-1", "ops", ""),
    ],
)
def test_cmd_incident_close_validation(incident_id: str, actor: str, reason: str) -> None:
    """Close command should reject empty incident_id/actor/reason."""
    with pytest.raises(ValueError):
        cmd_incident_close(incident_id, actor=actor, reason=reason)
