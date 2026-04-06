"""Integration test for reconcile supervisor periodic tick behavior."""

from __future__ import annotations

from hi_agent.management import ReconcileSupervisor
from hi_agent.runtime_adapter import (
    ConsistencyIssue,
    InMemoryConsistencyJournal,
    ReconcileLoop,
)


class _AlwaysFailBackend:
    """Backend stub that always fails open_stage reconciliation."""

    def open_stage(self, stage_id: str) -> None:
        raise RuntimeError(f"planned failure: {stage_id}")


def test_reconcile_supervisor_tick_interval_and_failure_metrics() -> None:
    """Tick should skip before interval and update failure metric after due run."""
    clock_values = iter([0.0, 0.5, 1.1])
    journal = InMemoryConsistencyJournal()
    loop = ReconcileLoop(backend=_AlwaysFailBackend(), journal=journal)
    supervisor = ReconcileSupervisor(
        reconcile_loop=loop,
        journal=journal,
        interval_seconds=1.0,
        periodic_max_rounds=1,
        clock=lambda: next(clock_values),
    )

    first = supervisor.tick()
    assert first.executed is True
    assert first.recent_reconcile_failures == 0

    journal.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S1_understand"},
            error="RuntimeError: open failed",
        )
    )

    second = supervisor.tick()
    assert second.executed is False
    assert second.recent_reconcile_failures == 0

    third = supervisor.tick()
    assert third.executed is True
    assert third.reconcile_report is not None
    assert third.reconcile_report.failed == 1
    assert third.recent_reconcile_failures == 1
    assert supervisor.recent_reconcile_failures == 1
