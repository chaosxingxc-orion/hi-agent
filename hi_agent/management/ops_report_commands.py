"""Command helpers for building ops reports and runbooks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hi_agent.management.incident_report import build_incident_report
from hi_agent.management.operational_dashboard import build_operational_dashboard_payload
from hi_agent.management.runbook import build_incident_runbook


def _validate_mapping(name: str, value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def cmd_ops_build_report(
    readiness: Mapping[str, object],
    signals: Mapping[str, object],
    alerts: list[dict[str, Any]],
    slo: Mapping[str, object],
    *,
    now_ts: float,
) -> dict[str, object]:
    """Build a normalized ops report payload from readiness/signal inputs."""
    readiness_map = _validate_mapping("readiness", readiness)
    signals_map = _validate_mapping("signals", signals)
    slo_map = _validate_mapping("slo", slo)
    if not isinstance(alerts, list):
        raise TypeError("alerts must be a list")

    dashboard = build_operational_dashboard_payload(
        readiness_report=readiness_map,
        operational_signals=signals_map,
        metadata={"generated_at": float(now_ts)},
    )
    incident = build_incident_report(
        dict(signals_map),
        alerts,
        dict(slo_map),
        now_ts=float(now_ts),
    )
    return {
        "command": "ops_build_report",
        "generated_at": float(now_ts),
        "dashboard": dashboard,
        "incident": incident,
        "alerts": list(alerts),
        "slo": dict(slo_map),
    }


def cmd_ops_build_runbook(report: Mapping[str, object]) -> dict[str, object]:
    """Build an action runbook payload from incident report."""
    report_map = _validate_mapping("report", report)
    runbook = build_incident_runbook(dict(report_map))
    return {"command": "ops_build_runbook", "runbook": runbook}
