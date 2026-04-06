"""Command-like helper functions for reconcile runtime operations."""

from __future__ import annotations

from hi_agent.management.reconcile_runtime import ReconcileRuntimeController


def _validate_int(name: str, value: object, *, minimum: int) -> int:
    """Validate a strict int (excluding bool) with a lower bound."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def cmd_reconcile_manual(
    controller: ReconcileRuntimeController,
    *,
    max_rounds: object,
) -> dict[str, object]:
    """Run manual reconcile through the runtime controller and return payload."""
    validated_rounds = _validate_int("max_rounds", max_rounds, minimum=1)
    report = controller.run_manual(max_rounds=validated_rounds)
    loop_report = report.reconcile_report

    return {
        "command": "reconcile_manual",
        "trigger": report.trigger,
        "executed": report.executed,
        "timestamp_seconds": report.timestamp_seconds,
        "backlog_size": report.backlog_size,
        "max_rounds": report.max_rounds,
        "recent_reconcile_failures": report.recent_reconcile_failures,
        "reconcile_rounds": (loop_report.rounds if loop_report is not None else None),
        "reconcile_applied": (loop_report.applied if loop_report is not None else None),
        "reconcile_failed": (loop_report.failed if loop_report is not None else None),
        "reconcile_skipped": (loop_report.skipped if loop_report is not None else None),
        "reconcile_dead_letter_count": (
            loop_report.dead_letter_count if loop_report is not None else None
        ),
    }


def cmd_reconcile_status(
    controller: ReconcileRuntimeController,
) -> dict[str, object]:
    """Return current reconcile runtime status as a primitive payload."""
    status = controller.status()
    return {
        "command": "reconcile_status",
        "backlog_size": status.backlog_size,
        "recent_reconcile_failures": status.recent_reconcile_failures,
        "dead_letter_count": status.dead_letter_count,
        "last_trigger": status.last_trigger,
        "last_executed": status.last_executed,
    }


def cmd_reconcile_readiness(
    controller: ReconcileRuntimeController,
    *,
    recent_error_count: object = 0,
) -> dict[str, object]:
    """Build reconcile operational readiness payload from runtime controller."""
    validated_recent_errors = _validate_int(
        "recent_error_count",
        recent_error_count,
        minimum=0,
    )
    report = controller.readiness(recent_error_count=validated_recent_errors)
    return {
        "command": "reconcile_readiness",
        "ready": report.ready,
        "dependencies": dict(report.dependencies),
        "recent_error_count": report.recent_error_count,
        "reconcile_backlog": report.reconcile_backlog,
        "recent_reconcile_failures": report.recent_reconcile_failures,
        "reconcile_backlog_threshold": report.reconcile_backlog_threshold,
    }
