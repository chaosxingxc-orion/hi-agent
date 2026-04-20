"""Operational signal aggregation helpers."""

from __future__ import annotations

from typing import Any


def build_operational_signals(
    *,
    reconcile_backlog: int,
    reconcile_backlog_threshold: int,
    recent_reconcile_failures: int,
    pending_gate_count: int,
    has_stale_gates: bool,
    temporal_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate reconcile/gate/temporal inputs into dashboard-friendly signals.

    Args:
      reconcile_backlog: Current reconcile queue size.
      reconcile_backlog_threshold: Backlog pressure threshold.
      recent_reconcile_failures: Count of recent reconcile failures.
      pending_gate_count: Number of unresolved human gates.
      has_stale_gates: Whether pending gates include stale entries.
      temporal_health: Optional temporal health snapshot dictionary.

    Returns:
      A dictionary containing normalized raw values and derived pressure booleans.
    """
    if reconcile_backlog < 0:
        raise ValueError("reconcile_backlog must be >= 0")
    if reconcile_backlog_threshold < 0:
        raise ValueError("reconcile_backlog_threshold must be >= 0")
    if recent_reconcile_failures < 0:
        raise ValueError("recent_reconcile_failures must be >= 0")
    if pending_gate_count < 0:
        raise ValueError("pending_gate_count must be >= 0")

    temporal_state = None
    temporal_healthy = None
    if temporal_health is not None:
        temporal_state = str(temporal_health.get("state", "") or "")
        temporal_healthy_raw = temporal_health.get("healthy")
        temporal_healthy = bool(temporal_healthy_raw) if temporal_healthy_raw is not None else None

    has_reconcile_pressure = (
        reconcile_backlog >= reconcile_backlog_threshold or recent_reconcile_failures > 0
    )
    has_gate_pressure = pending_gate_count > 0 or bool(has_stale_gates)
    has_temporal_risk = temporal_health is not None and (
        temporal_healthy is False or temporal_state in {"degraded", "unreachable"}
    )

    return {
        "reconcile_backlog": reconcile_backlog,
        "reconcile_backlog_threshold": reconcile_backlog_threshold,
        "recent_reconcile_failures": recent_reconcile_failures,
        "pending_gate_count": pending_gate_count,
        "has_stale_gates": bool(has_stale_gates),
        "temporal_state": temporal_state,
        "temporal_healthy": temporal_healthy,
        "has_reconcile_pressure": has_reconcile_pressure,
        "has_gate_pressure": has_gate_pressure,
        "has_temporal_risk": has_temporal_risk,
        "overall_pressure": (has_reconcile_pressure or has_gate_pressure or has_temporal_risk),
    }
