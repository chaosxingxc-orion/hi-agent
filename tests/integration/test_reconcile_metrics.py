"""Unit tests for reconcile metrics snapshot helper."""

from __future__ import annotations

from hi_agent.management.health import OperationalReadinessReport
from hi_agent.management.reconcile_metrics import build_reconcile_metrics_snapshot
from hi_agent.management.reconcile_runtime import ReconcileRuntimeStatus


def test_build_reconcile_metrics_snapshot_normal_case() -> None:
    """Snapshot should expose stable healthy reconcile metrics."""
    status = ReconcileRuntimeStatus(
        backlog_size=0,
        recent_reconcile_failures=0,
        dead_letter_count=0,
        last_trigger="periodic",
        last_executed=True,
    )
    readiness = OperationalReadinessReport(
        ready=True,
        dependencies={"runtime": True, "kernel": True},
        recent_error_count=0,
        reconcile_backlog=0,
        recent_reconcile_failures=0,
        reconcile_backlog_threshold=2,
    )

    snapshot = build_reconcile_metrics_snapshot(status=status, readiness=readiness)

    assert snapshot.backlog_size == 0
    assert snapshot.dead_letter_count == 0
    assert snapshot.recent_reconcile_failures == 0
    assert snapshot.readiness is True
    assert snapshot.last_trigger == "periodic"


def test_build_reconcile_metrics_snapshot_degraded_case() -> None:
    """Snapshot should preserve degraded reconcile signals for operators."""
    status = ReconcileRuntimeStatus(
        backlog_size=5,
        recent_reconcile_failures=2,
        dead_letter_count=3,
        last_trigger="manual",
        last_executed=False,
    )
    readiness = OperationalReadinessReport(
        ready=False,
        dependencies={"runtime": True, "kernel": True},
        recent_error_count=0,
        reconcile_backlog=5,
        recent_reconcile_failures=2,
        reconcile_backlog_threshold=2,
    )

    snapshot = build_reconcile_metrics_snapshot(status=status, readiness=readiness)

    assert snapshot.backlog_size == 5
    assert snapshot.dead_letter_count == 3
    assert snapshot.recent_reconcile_failures == 2
    assert snapshot.readiness is False
    assert snapshot.last_trigger == "manual"
