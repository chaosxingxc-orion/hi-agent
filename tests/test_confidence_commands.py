"""Unit tests for route confidence command helper."""

from __future__ import annotations

import pytest
from hi_agent.route_engine.confidence_commands import cmd_route_confidence_check


@pytest.mark.parametrize(
    ("confidence", "expected_band", "expected_escalate"),
    [
        (0.62, "low", True),
        (0.68, "borderline", True),
        (0.75, "ok", False),
    ],
)
def test_cmd_route_confidence_check_bands(
    confidence: float,
    expected_band: str,
    expected_escalate: bool,
) -> None:
    """Command output should match policy band classification."""
    payload = cmd_route_confidence_check(confidence, threshold=0.7, margin=0.05)
    assert payload["command"] == "route_confidence_check"
    assert payload["band"] == expected_band
    assert payload["escalate"] is expected_escalate


@pytest.mark.parametrize(
    ("confidence", "threshold", "margin"),
    [
        (-0.1, 0.7, 0.05),
        (1.1, 0.7, 0.05),
        (0.6, -0.1, 0.05),
        (0.6, 1.1, 0.05),
        (0.6, 0.7, -0.1),
        (0.6, 0.4, 0.5),
    ],
)
def test_cmd_route_confidence_check_invalid_inputs(
    confidence: float,
    threshold: float,
    margin: float,
) -> None:
    """Invalid ranges should bubble up as validation errors."""
    with pytest.raises((TypeError, ValueError)):
        cmd_route_confidence_check(
            confidence,
            threshold=threshold,
            margin=margin,
        )
