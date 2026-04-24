"""Boundary-focused tests for route confidence escalation policy."""

from __future__ import annotations

import pytest
from hi_agent.route_engine.confidence_policy import should_escalate_route_decision


def test_should_escalate_returns_low_when_below_lower_bound() -> None:
    """Confidence below threshold-margin should be low and escalated."""
    result = should_escalate_route_decision(0.64, threshold=0.7, margin=0.05)
    assert result == {"escalate": True, "band": "low"}


def test_should_escalate_returns_borderline_at_lower_bound() -> None:
    """Confidence exactly at threshold-margin should be borderline."""
    result = should_escalate_route_decision(0.65, threshold=0.7, margin=0.05)
    assert result == {"escalate": True, "band": "borderline"}


def test_should_escalate_returns_ok_at_threshold() -> None:
    """Confidence exactly at threshold should be accepted without escalation."""
    result = should_escalate_route_decision(0.7, threshold=0.7, margin=0.05)
    assert result == {"escalate": False, "band": "ok"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confidence": -0.01},
        {"confidence": 1.01},
        {"confidence": 0.5, "threshold": -0.1},
        {"confidence": 0.5, "threshold": 1.1},
    ],
)
def test_should_escalate_validates_unit_interval(kwargs: dict[str, float]) -> None:
    """Confidence/threshold must remain within [0, 1]."""
    with pytest.raises(ValueError):
        should_escalate_route_decision(**kwargs)


def test_should_escalate_rejects_negative_margin() -> None:
    """Margin must be non-negative."""
    with pytest.raises(ValueError, match="margin must be >= 0"):
        should_escalate_route_decision(0.5, margin=-0.01)


def test_should_escalate_rejects_margin_above_threshold() -> None:
    """Margin above threshold is invalid."""
    with pytest.raises(ValueError, match="margin must be <= threshold"):
        should_escalate_route_decision(0.5, threshold=0.2, margin=0.3)
