"""Operational alert evaluation helpers."""

from __future__ import annotations

from typing import Any


def evaluate_operational_alerts(signals: dict[str, Any]) -> list[dict[str, str]]:
    """Translate operational signals to normalized alert rows."""
    alerts: list[dict[str, str]] = []

    if bool(signals.get("has_temporal_risk", False)):
        alerts.append(
            {
                "severity": "critical",
                "code": "temporal_risk",
                "message": "Temporal connectivity risk detected.",
            }
        )
    if bool(signals.get("has_reconcile_pressure", False)):
        alerts.append(
            {
                "severity": "warning",
                "code": "reconcile_pressure",
                "message": "Reconcile backlog/failures exceed safe range.",
            }
        )
    if bool(signals.get("has_gate_pressure", False)):
        alerts.append(
            {
                "severity": "warning",
                "code": "gate_pressure",
                "message": "Pending or stale human gates detected.",
            }
        )
    return alerts
