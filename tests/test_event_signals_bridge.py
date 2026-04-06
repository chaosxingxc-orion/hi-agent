"""Tests for runtime event summary -> operational signals bridge."""

from __future__ import annotations

import pytest
from hi_agent.runtime_adapter.event_signals_bridge import build_signals_from_event_summary


def test_bridge_builds_non_pressure_signals() -> None:
    """Balanced execution without failures should produce non-pressure signals."""
    summary = {
        "counts_by_type": {
            "ActionPlanned": 3,
            "ActionExecuted": 3,
            "ActionExecutionFailed": 0,
            "RecoveryTriggered": 0,
            "HumanGateOpened": 1,
            "HumanGateResolved": 1,
        },
        "duration_ms": 1_200.0,
        "total_events": 9,
    }

    signals = build_signals_from_event_summary(summary, backlog_threshold=5)

    assert signals["reconcile_backlog"] == 0
    assert signals["recent_reconcile_failures"] == 0
    assert signals["pending_gate_count"] == 0
    assert signals["has_stale_gates"] is False
    assert signals["reconcile_backlog_threshold"] == 5


def test_bridge_builds_pressure_signals_for_backlog_failures_and_stale_gate() -> None:
    """Lagging execution and long-running pending gates should mark pressure."""
    summary = {
        "counts_by_type": {
            "ActionPlanned": 8,
            "ActionExecuted": 3,
            "ActionExecutionFailed": 2,
            "RecoveryTriggered": 1,
            "HumanGateOpened": 4,
            "HumanGateResolved": 1,
        },
        "duration_ms": 301_000.0,
        "total_events": 20,
    }

    signals = build_signals_from_event_summary(summary, backlog_threshold=2)

    assert signals["reconcile_backlog"] == 3
    assert signals["recent_reconcile_failures"] == 3
    assert signals["pending_gate_count"] == 3
    assert signals["has_stale_gates"] is True


@pytest.mark.parametrize(
    ("summary", "backlog_threshold"),
    [
        ({}, 1),
        ({"counts_by_type": {}, "duration_ms": -1, "total_events": 0}, 1),
        ({"counts_by_type": {}, "duration_ms": 1, "total_events": -1}, 1),
    ],
)
def test_bridge_validates_inputs(summary: dict[str, object], backlog_threshold: int) -> None:
    """Invalid summary payload should raise ValueError."""
    with pytest.raises(ValueError):
        build_signals_from_event_summary(summary, backlog_threshold=backlog_threshold)

