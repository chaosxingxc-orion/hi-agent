"""Command helper that chains incident report, ticket creation, and runbook."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from hi_agent.management.incident_commands import cmd_incident_create
from hi_agent.management.incident_report import build_incident_report
from hi_agent.management.runbook import build_incident_runbook


def cmd_incident_generate_and_runbook(
    *,
    signals: dict[str, Any],
    alerts: Sequence[dict[str, Any]],
    slo: dict[str, Any] | object,
    actor: str,
    now_ts: float,
    service: str = "hi-agent",
) -> dict[str, Any]:
    """Build report, create incident, and generate runbook in one call."""
    if isinstance(slo, dict):
        slo_snapshot = dict(slo)
    elif is_dataclass(slo):
        slo_snapshot = asdict(slo)
    elif hasattr(slo, "__dict__"):
        slo_snapshot = dict(vars(slo))
    else:
        raise TypeError("slo must be a mapping or dataclass-like object")

    report = build_incident_report(
        signals=dict(signals),
        alerts=list(alerts),
        slo_snapshot=slo_snapshot,
        now_ts=float(now_ts),
        service=service,
    )
    incident = cmd_incident_create(report, actor=actor, channel="ops")
    runbook = build_incident_runbook(report)
    return {
        "command": "incident_generate_and_runbook",
        "report": report,
        "incident": incident,
        "runbook": runbook,
    }
