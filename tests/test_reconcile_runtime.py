"""Unit tests for reconcile runtime operational controller."""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.management import ReconcileRuntimeController, ReconcileSupervisor
from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoopReport


class _FakeJournal:
    def __init__(self, issue_count: int) -> None:
        self._issues = [object() for _ in range(issue_count)]

    def list_issues(self) -> list[object]:
        return list(self._issues)


@dataclass
class _FakeReconcileLoop:
    reports: list[ReconcileLoopReport]

    def __post_init__(self) -> None:
        self.calls: list[int] = []
        self._dead_letters: list[object] = []

    @property
    def dead_letter_issues(self) -> list[object]:
        return list(self._dead_letters)

    def pending_issue_count(self) -> int:
        return 1 if not self.calls else 0

    def run_until_clean(self, max_rounds: int) -> ReconcileLoopReport:
        self.calls.append(max_rounds)
        report = self.reports[min(len(self.calls) - 1, len(self.reports) - 1)]
        if report.dead_letter_count > 0:
            self._dead_letters = [object() for _ in range(report.dead_letter_count)]
        return report


def _build_controller(*, report: ReconcileLoopReport) -> ReconcileRuntimeController:
    loop = _FakeReconcileLoop(reports=[report])
    supervisor = ReconcileSupervisor(
        reconcile_loop=loop,
        journal=_FakeJournal(issue_count=1),
        interval_seconds=10.0,
        periodic_max_rounds=1,
        clock=lambda: 1.0,
    )
    return ReconcileRuntimeController(
        supervisor,
        dependencies={"runtime": True, "kernel": True},
        reconcile_backlog_threshold=2,
    )


def test_reconcile_runtime_manual_and_status() -> None:
    """Manual trigger should update status and expose runtime metrics."""
    controller = _build_controller(
        report=ReconcileLoopReport(
            rounds=1,
            applied=1,
            failed=0,
            skipped=0,
            dead_letter_count=0,
        )
    )

    report = controller.run_manual(max_rounds=3)
    status = controller.status()

    assert report.executed is True
    assert report.max_rounds == 3
    assert status.backlog_size == 0
    assert status.recent_reconcile_failures == 0
    assert status.dead_letter_count == 0
    assert status.last_trigger == "manual"
    assert status.last_executed is True


def test_reconcile_runtime_readiness_reflects_failures() -> None:
    """Readiness should turn false when reconcile failures remain."""
    controller = _build_controller(
        report=ReconcileLoopReport(
            rounds=1,
            applied=0,
            failed=1,
            skipped=0,
            dead_letter_count=0,
        )
    )
    controller.run_manual(max_rounds=1)

    readiness = controller.readiness(recent_error_count=0)

    assert readiness.ready is False
    assert readiness.recent_reconcile_failures == 1
