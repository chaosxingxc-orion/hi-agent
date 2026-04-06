"""Unit tests for ops health command bridge helpers."""

from __future__ import annotations

import pytest
from hi_agent.management.ops_health_commands import (
    cmd_ops_health_badge,
    cmd_ops_health_snapshot,
)


def _base_signals() -> dict[str, object]:
    return {
        "reconcile_backlog": 0,
        "reconcile_backlog_threshold": 10,
        "recent_reconcile_failures": 0,
        "pending_gate_count": 0,
        "has_stale_gates": False,
        "has_reconcile_pressure": False,
        "has_gate_pressure": False,
        "has_temporal_risk": False,
    }


def test_cmd_ops_health_snapshot_and_green_badge_when_ready() -> None:
    """Ready snapshot should map to a green badge."""
    snapshot = cmd_ops_health_snapshot(
        dependencies={"runtime": True, "kernel": True},
        errors=0,
        signals=_base_signals(),
    )
    assert snapshot["command"] == "ops_health_snapshot"
    assert snapshot["ready"] is True
    assert cmd_ops_health_badge(snapshot) == "green"


def test_cmd_ops_health_badge_turns_red_on_errors_or_failures() -> None:
    """Red badge should be used for not-ready snapshots with error signals."""
    signals = _base_signals()
    signals["recent_reconcile_failures"] = 1
    signals["has_reconcile_pressure"] = True
    snapshot = cmd_ops_health_snapshot(
        dependencies={"runtime": True},
        errors=0,
        signals=signals,
    )
    assert snapshot["ready"] is False
    assert cmd_ops_health_badge(snapshot) == "red"


def test_cmd_ops_health_badge_turns_yellow_when_not_ready_without_errors() -> None:
    """Yellow badge should represent degraded but non-error not-ready state."""
    signals = _base_signals()
    signals["has_temporal_risk"] = True
    snapshot = cmd_ops_health_snapshot(
        dependencies={"runtime": True},
        errors=0,
        signals=signals,
    )
    assert snapshot["ready"] is False
    assert cmd_ops_health_badge(snapshot) == "yellow"


def test_cmd_ops_health_badge_validates_required_fields() -> None:
    """Badge helper should reject invalid snapshot payloads."""
    with pytest.raises(ValueError, match="snapshot must include"):
        cmd_ops_health_badge({"ready": True})
