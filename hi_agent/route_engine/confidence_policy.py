"""Route confidence escalation policy helpers."""

from __future__ import annotations


def should_escalate_route_decision(
    confidence: float,
    *,
    threshold: float = 0.7,
    margin: float = 0.05,
) -> dict[str, object]:
    """Classify confidence and decide whether escalation is required.

    Bands:
      - ``low``: confidence < threshold - margin
      - ``borderline``: threshold - margin <= confidence < threshold
      - ``ok``: confidence >= threshold
    """
    numeric_confidence = _validate_unit_interval(value=confidence, name="confidence")
    numeric_threshold = _validate_unit_interval(value=threshold, name="threshold")
    if margin < 0:
        raise ValueError("margin must be >= 0")
    if margin > numeric_threshold:
        raise ValueError("margin must be <= threshold")

    lower_bound = numeric_threshold - margin
    if numeric_confidence < lower_bound:
        return {"escalate": True, "band": "low"}
    if numeric_confidence < numeric_threshold:
        return {"escalate": True, "band": "borderline"}
    return {"escalate": False, "band": "ok"}


def _validate_unit_interval(*, value: float, name: str) -> float:
    """Validate a value is a number in [0, 1]."""
    if not isinstance(value, int | float):
        raise TypeError(f"{name} must be a number")
    numeric = float(value)
    if numeric < 0 or numeric > 1:
        raise ValueError(f"{name} must be in [0, 1]")
    return numeric
