"""Command-style helpers for ops health snapshots."""

from __future__ import annotations

from hi_agent.management.health import build_operational_readiness_from_signals


def cmd_ops_health_snapshot(
    *,
    dependencies: dict[str, bool],
    errors: int,
    signals: dict[str, object],
) -> dict[str, object]:
    """Build a normalized ops health snapshot payload."""
    report = build_operational_readiness_from_signals(
        dependencies=dependencies,
        recent_error_count=errors,
        signals=signals,
    )
    return {
        "command": "ops_health_snapshot",
        "ready": report.ready,
        "dependencies": dict(report.dependencies),
        "recent_error_count": report.recent_error_count,
        "reconcile_backlog": report.reconcile_backlog,
        "recent_reconcile_failures": report.recent_reconcile_failures,
        "pending_gate_count": report.pending_gate_count,
        "has_stale_gates": report.has_stale_gates,
        "stale_gate_threshold_seconds": report.stale_gate_threshold_seconds,
        "oldest_pending_gate_age_seconds": report.oldest_pending_gate_age_seconds,
    }


def cmd_ops_health_badge(snapshot: dict[str, object]) -> str:
    """Map snapshot payload into `green`/`yellow`/`red` badge."""
    if "ready" not in snapshot or "recent_error_count" not in snapshot:
        raise ValueError("snapshot must include 'ready' and 'recent_error_count'")

    ready = bool(snapshot["ready"])
    errors = int(snapshot["recent_error_count"])
    has_stale_gates = bool(snapshot.get("has_stale_gates", False))
    reconcile_failures = int(snapshot.get("recent_reconcile_failures", 0))

    if not ready and (errors > 0 or reconcile_failures > 0 or has_stale_gates):
        return "red"
    if not ready:
        return "yellow"
    return "green"
