"""Unit tests for management reconcile supervisor behavior."""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.management.reconcile_supervisor import ReconcileSupervisor
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

    def run_until_clean(self, max_rounds: int) -> ReconcileLoopReport:
        self.calls.append(max_rounds)
        index = len(self.calls) - 1
        if index < len(self.reports):
            return self.reports[index]
        return self.reports[-1]


def test_backlog_size_counts_journal_snapshot() -> None:
    """Supervisor should expose current issue backlog size from journal."""
    supervisor = ReconcileSupervisor(
        reconcile_loop=_FakeReconcileLoop(
            reports=[
                ReconcileLoopReport(
                    rounds=1,
                    applied=0,
                    failed=0,
                    skipped=0,
                    dead_letter_count=0,
                )
            ]
        ),
        journal=_FakeJournal(issue_count=3),
        interval_seconds=30.0,
        clock=lambda: 100.0,
    )

    assert supervisor.backlog_size() == 3


def test_run_manual_returns_deterministic_report_and_updates_tracking() -> None:
    """Manual trigger should always execute and update failure/last report state."""
    loop = _FakeReconcileLoop(
        reports=[
            ReconcileLoopReport(
                rounds=2,
                applied=4,
                failed=1,
                skipped=0,
                dead_letter_count=0,
            )
        ]
    )
    supervisor = ReconcileSupervisor(
        reconcile_loop=loop,
        journal=_FakeJournal(issue_count=2),
        interval_seconds=30.0,
        clock=lambda: 42.0,
    )

    report = supervisor.run_manual(max_rounds=5)

    assert report.trigger == "manual"
    assert report.executed is True
    assert report.timestamp_seconds == 42.0
    assert report.backlog_size == 2
    assert report.max_rounds == 5
    assert report.reconcile_report == ReconcileLoopReport(
        rounds=2,
        applied=4,
        failed=1,
        skipped=0,
        dead_letter_count=0,
    )
    assert report.recent_reconcile_failures == 1
    assert supervisor.recent_reconcile_failures == 1
    assert supervisor.last_report == report
    assert loop.calls == [5]


def test_tick_respects_interval_and_uses_injected_clock() -> None:
    """Periodic tick should run only when due and produce deterministic reports."""
    clock_values = iter([10.0, 15.0, 21.0])
    loop = _FakeReconcileLoop(
        reports=[
            ReconcileLoopReport(
                rounds=1,
                applied=1,
                failed=0,
                skipped=0,
                dead_letter_count=0,
            ),
            ReconcileLoopReport(
                rounds=1,
                applied=0,
                failed=2,
                skipped=0,
                dead_letter_count=0,
            ),
        ]
    )
    supervisor = ReconcileSupervisor(
        reconcile_loop=loop,
        journal=_FakeJournal(issue_count=1),
        interval_seconds=5.0,
        periodic_max_rounds=3,
        clock=lambda: next(clock_values),
    )

    first = supervisor.tick()
    second = supervisor.tick()
    third = supervisor.tick()

    assert first.trigger == "tick"
    assert first.executed is True
    assert first.timestamp_seconds == 10.0
    assert first.max_rounds == 3
    assert first.recent_reconcile_failures == 0

    assert second.trigger == "tick"
    assert second.executed is True
    assert second.timestamp_seconds == 15.0
    assert second.max_rounds == 3
    assert second.recent_reconcile_failures == 2

    assert third.trigger == "tick"
    assert third.executed is True
    assert third.timestamp_seconds == 21.0
    assert third.max_rounds == 3

    assert loop.calls == [3, 3, 3]
    assert supervisor.recent_reconcile_failures == 2
    assert supervisor.last_report == third


def test_tick_skips_when_not_due() -> None:
    """Tick should skip reconcile execution until interval has elapsed."""
    clock_values = iter([100.0, 103.0])
    loop = _FakeReconcileLoop(
        reports=[
            ReconcileLoopReport(
                rounds=1,
                applied=1,
                failed=0,
                skipped=0,
                dead_letter_count=0,
            )
        ]
    )
    supervisor = ReconcileSupervisor(
        reconcile_loop=loop,
        journal=_FakeJournal(issue_count=4),
        interval_seconds=5.0,
        periodic_max_rounds=2,
        clock=lambda: next(clock_values),
    )

    first = supervisor.tick()
    second = supervisor.tick()

    assert first.executed is True
    assert second.executed is False
    assert second.reconcile_report is None
    assert second.timestamp_seconds == 103.0
    assert second.backlog_size == 4
    assert second.max_rounds == 2
    assert second.recent_reconcile_failures == 0
    assert loop.calls == [2]


def test_invalid_constructor_and_manual_inputs_raise() -> None:
    """Supervisor should validate non-positive interval and max_rounds."""
    loop = _FakeReconcileLoop(
        reports=[
            ReconcileLoopReport(
                rounds=1,
                applied=0,
                failed=0,
                skipped=0,
                dead_letter_count=0,
            )
        ]
    )

    try:
        ReconcileSupervisor(
            reconcile_loop=loop,
            journal=_FakeJournal(issue_count=0),
            interval_seconds=0.0,
            clock=lambda: 0.0,
        )
    except ValueError as error:
        assert str(error) == "interval_seconds must be > 0"
    else:
        raise AssertionError("Expected ValueError for interval_seconds")

    supervisor = ReconcileSupervisor(
        reconcile_loop=loop,
        journal=_FakeJournal(issue_count=0),
        interval_seconds=1.0,
        clock=lambda: 0.0,
    )

    try:
        supervisor.run_manual(max_rounds=0)
    except ValueError as error:
        assert str(error) == "max_rounds must be >= 1"
    else:
        raise AssertionError("Expected ValueError for max_rounds")
