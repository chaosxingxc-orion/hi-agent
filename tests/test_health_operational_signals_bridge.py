"""Tests for readiness bridge using operational signals payloads."""

from __future__ import annotations

import pytest
from hi_agent.management.health import build_operational_readiness_from_signals


def test_build_operational_readiness_from_signals_ready_when_no_pressure() -> None:
    """No pressure signals should keep readiness true when dependencies are healthy."""
    report = build_operational_readiness_from_signals(
        dependencies={"runtime": True},
        recent_error_count=0,
        signals={
            "reconcile_backlog": 0,
            "reconcile_backlog_threshold": 10,
            "recent_reconcile_failures": 0,
            "pending_gate_count": 0,
            "has_stale_gates": False,
            "has_reconcile_pressure": False,
            "has_gate_pressure": False,
            "has_temporal_risk": False,
            "stale_gate_threshold_seconds": 120.0,
            "oldest_pending_gate_age_seconds": None,
        },
    )
    assert report.ready is True


def test_build_operational_readiness_from_signals_not_ready_on_pressure() -> None:
    """Any pressure signal should force readiness false."""
    report = build_operational_readiness_from_signals(
        dependencies={"runtime": True},
        recent_error_count=0,
        signals={
            "reconcile_backlog": 5,
            "reconcile_backlog_threshold": 10,
            "recent_reconcile_failures": 0,
            "pending_gate_count": 1,
            "has_stale_gates": False,
            "has_reconcile_pressure": False,
            "has_gate_pressure": True,
            "has_temporal_risk": False,
            "stale_gate_threshold_seconds": 120.0,
            "oldest_pending_gate_age_seconds": 10.0,
        },
    )
    assert report.ready is False


def test_build_operational_readiness_from_signals_requires_expected_keys() -> None:
    """Bridge should fail fast on missing required signal keys."""
    with pytest.raises(ValueError, match="signals missing required key"):
        build_operational_readiness_from_signals(
            dependencies={"runtime": True},
            recent_error_count=0,
            signals={},
        )
