"""Command helpers for route confidence evaluation."""

from __future__ import annotations

from hi_agent.route_engine.confidence_policy import should_escalate_route_decision


def cmd_route_confidence_check(
    confidence: float,
    *,
    threshold: float = 0.7,
    margin: float = 0.05,
) -> dict[str, object]:
    """Evaluate route confidence and return a normalized command payload."""
    policy_result = should_escalate_route_decision(
        confidence,
        threshold=threshold,
        margin=margin,
    )
    return {
        "command": "route_confidence_check",
        "confidence": float(confidence),
        "threshold": float(threshold),
        "margin": float(margin),
        "band": policy_result["band"],
        "escalate": policy_result["escalate"],
    }
