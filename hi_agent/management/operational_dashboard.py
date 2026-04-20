"""Operational dashboard payload assembly helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _as_dict(value: object | None) -> dict[str, Any]:
    """Normalize mapping/dataclass-like input into a dictionary."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise TypeError("input must be a mapping, object with __dict__, or None")


def build_operational_dashboard_payload(
    *,
    readiness_report: object,
    operational_signals: Mapping[str, object],
    temporal_health: Mapping[str, object] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build a normalized dashboard payload from readiness/signal inputs."""
    readiness = _as_dict(readiness_report)
    signals = dict(operational_signals)
    temporal = dict(temporal_health or {})
    meta = dict(metadata or {})

    ready = bool(readiness.get("ready", False))
    overall_pressure = bool(signals.get("overall_pressure", False))
    has_temporal_risk = bool(signals.get("has_temporal_risk", False))
    temporal_state = str(temporal.get("state", signals.get("temporal_state", "")))

    if not ready or temporal_state == "unreachable" or has_temporal_risk:
        badge = "red"
    elif overall_pressure or temporal_state == "degraded":
        badge = "yellow"
    else:
        badge = "green"

    summary = {
        "badge": badge,
        "ready": ready,
        "overall_pressure": overall_pressure,
    }
    return {
        "summary": summary,
        "readiness": readiness,
        "signals": signals,
        "temporal": temporal,
        "metadata": meta,
        "status_badge": badge,
    }
