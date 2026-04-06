"""Tests for operational signal aggregation helpers."""

from __future__ import annotations

import pytest
from hi_agent.management.operational_signals import build_operational_signals


def test_build_operational_signals_reports_reconcile_pressure() -> None:
    """Backlog over threshold should mark reconcile and overall pressure."""
    signals = build_operational_signals(
        reconcile_backlog=10,
        reconcile_backlog_threshold=8,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
    )
    assert signals["has_reconcile_pressure"] is True
    assert signals["has_gate_pressure"] is False
    assert signals["has_temporal_risk"] is False
    assert signals["overall_pressure"] is True


def test_build_operational_signals_reports_gate_pressure() -> None:
    """Pending or stale gates should mark gate and overall pressure."""
    signals = build_operational_signals(
        reconcile_backlog=1,
        reconcile_backlog_threshold=8,
        recent_reconcile_failures=0,
        pending_gate_count=2,
        has_stale_gates=False,
    )
    assert signals["has_reconcile_pressure"] is False
    assert signals["has_gate_pressure"] is True
    assert signals["overall_pressure"] is True


def test_build_operational_signals_reports_temporal_risk() -> None:
    """Degraded temporal state should be surfaced as temporal risk."""
    signals = build_operational_signals(
        reconcile_backlog=1,
        reconcile_backlog_threshold=8,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        temporal_health={"state": "degraded", "healthy": False},
    )
    assert signals["has_temporal_risk"] is True
    assert signals["overall_pressure"] is True


def test_build_operational_signals_combined_happy_path() -> None:
    """Healthy/low-pressure inputs should produce no pressure flags."""
    signals = build_operational_signals(
        reconcile_backlog=1,
        reconcile_backlog_threshold=8,
        recent_reconcile_failures=0,
        pending_gate_count=0,
        has_stale_gates=False,
        temporal_health={"state": "healthy", "healthy": True},
    )
    assert signals["has_reconcile_pressure"] is False
    assert signals["has_gate_pressure"] is False
    assert signals["has_temporal_risk"] is False
    assert signals["overall_pressure"] is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"reconcile_backlog": -1}, "reconcile_backlog"),
        ({"reconcile_backlog_threshold": -1}, "reconcile_backlog_threshold"),
        ({"recent_reconcile_failures": -1}, "recent_reconcile_failures"),
        ({"pending_gate_count": -1}, "pending_gate_count"),
    ],
)
def test_build_operational_signals_validates_non_negative_inputs(
    kwargs: dict[str, int],
    message: str,
) -> None:
    """Negative counters should fail fast with clear errors."""
    base = {
        "reconcile_backlog": 0,
        "reconcile_backlog_threshold": 1,
        "recent_reconcile_failures": 0,
        "pending_gate_count": 0,
        "has_stale_gates": False,
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        build_operational_signals(**base)
