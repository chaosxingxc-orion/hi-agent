"""Operational governance decision helpers."""

from __future__ import annotations

from typing import Any


def evaluate_ops_governance(
    *,
    readiness: dict[str, Any],
    signals: dict[str, Any],
    slo_snapshot: dict[str, Any],
    alert_count: int = 0,
) -> dict[str, Any]:
    """Evaluate governance decision from readiness/signals/SLO signals."""
    if alert_count < 0:
        raise ValueError("alert_count must be >= 0")

    ready = bool(readiness.get("ready", False))
    has_pressure = bool(signals.get("overall_pressure", False))
    success_target_met = bool(slo_snapshot.get("success_target_met", True))
    latency_target_met = bool(slo_snapshot.get("latency_target_met", True))

    require_incident = (
        (not ready)
        or has_pressure
        or (not success_target_met)
        or (not latency_target_met)
        or alert_count > 0
    )
    allow_deploy = ready and not require_incident

    if not ready or alert_count > 0:
        escalation_level = "high"
    elif has_pressure or (not success_target_met) or (not latency_target_met):
        escalation_level = "medium"
    else:
        escalation_level = "low"

    return {
        "allow_deploy": allow_deploy,
        "require_incident": require_incident,
        "escalation_level": escalation_level,
        "inputs": {
            "ready": ready,
            "overall_pressure": has_pressure,
            "success_target_met": success_target_met,
            "latency_target_met": latency_target_met,
            "alert_count": alert_count,
        },
    }
