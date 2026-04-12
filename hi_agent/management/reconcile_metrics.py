"""Helpers for reconcile runtime metrics snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.management.health import OperationalReadinessReport
from hi_agent.management.reconcile_runtime import (
    ReconcileRuntimeController,
    ReconcileRuntimeStatus,
)


@dataclass(frozen=True)
class ReconcileMetricsSnapshot:
    """Compact reconcile metrics view for status/reporting surfaces."""

    backlog_size: int
    dead_letter_count: int
    recent_reconcile_failures: int
    readiness: bool
    last_trigger: str | None


def build_reconcile_metrics_snapshot(
    *,
    status: ReconcileRuntimeStatus,
    readiness: OperationalReadinessReport,
) -> ReconcileMetricsSnapshot:
    """Build reconcile metrics snapshot from controller status/readiness outputs."""
    return ReconcileMetricsSnapshot(
        backlog_size=status.backlog_size,
        dead_letter_count=status.dead_letter_count,
        recent_reconcile_failures=status.recent_reconcile_failures,
        readiness=readiness.ready,
        last_trigger=status.last_trigger,
    )


def build_reconcile_metrics_snapshot_from_controller(
    controller: ReconcileRuntimeController,
    *,
    recent_error_count: int = 0,
) -> ReconcileMetricsSnapshot:
    """Build reconcile metrics snapshot directly from a runtime controller."""
    return build_reconcile_metrics_snapshot(
        status=controller.status(),
        readiness=controller.readiness(recent_error_count=recent_error_count),
    )
