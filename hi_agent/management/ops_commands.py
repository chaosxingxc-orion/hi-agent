"""High-level operations command wrappers."""

from __future__ import annotations

from typing import Any

from hi_agent.management.alerts_commands import cmd_alerts_from_signals
from hi_agent.management.operational_dashboard import build_operational_dashboard_payload
from hi_agent.management.operational_signals import build_operational_signals
from hi_agent.management.slo_commands import cmd_slo_evaluate


def cmd_ops_snapshot(
    *,
    dependencies: dict[str, bool],
    recent_error_count: int,
    reconcile_backlog: int,
    reconcile_backlog_threshold: int,
    recent_reconcile_failures: int,
    pending_gate_count: int,
    has_stale_gates: bool,
    metrics: dict[str, Any],
    slo_objective: dict[str, Any],
    temporal_health: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a one-shot operations snapshot payload for command surfaces."""
    readiness_report = {
        "ready": bool(all(dependencies.values()) and recent_error_count == 0),
        "dependencies": dict(dependencies),
        "recent_error_count": int(recent_error_count),
    }
    signals = build_operational_signals(
        reconcile_backlog=reconcile_backlog,
        reconcile_backlog_threshold=reconcile_backlog_threshold,
        recent_reconcile_failures=recent_reconcile_failures,
        pending_gate_count=pending_gate_count,
        has_stale_gates=has_stale_gates,
        temporal_health=temporal_health,
    )
    dashboard = build_operational_dashboard_payload(
        readiness_report=readiness_report,
        operational_signals=signals,
        temporal_health=temporal_health,
        metadata=metadata,
    )
    alerts = cmd_alerts_from_signals(signals)
    slo = cmd_slo_evaluate(metrics, objective=slo_objective)
    return {
        "command": "ops_snapshot",
        "dashboard": dashboard,
        "alerts": alerts,
        "slo": slo,
    }
