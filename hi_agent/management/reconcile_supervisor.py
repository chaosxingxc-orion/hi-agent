"""Supervisor for periodic/manual consistency reconcile execution."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoop, ReconcileLoopReport


class _JournalLike(Protocol):
    """Minimal journal contract used by the supervisor."""

    def list_issues(self) -> list[object]:
        """Return a snapshot list of backlog issues."""


@dataclass(frozen=True)
class ReconcileSupervisorReport:
    """Deterministic execution report for manual or periodic reconcile triggers."""

    trigger: str
    executed: bool
    timestamp_seconds: float
    backlog_size: int
    max_rounds: int
    recent_reconcile_failures: int
    reconcile_report: ReconcileLoopReport | None


class ReconcileSupervisor:
    """Coordinate reconcile loop execution across manual and periodic triggers."""

    def __init__(
        self,
        reconcile_loop: ReconcileLoop,
        journal: _JournalLike,
        *,
        interval_seconds: float,
        periodic_max_rounds: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize supervisor runtime dependencies and trigger policies."""
        if interval_seconds <= 0:
            msg = "interval_seconds must be > 0"
            raise ValueError(msg)
        if periodic_max_rounds < 1:
            msg = "periodic_max_rounds must be >= 1"
            raise ValueError(msg)

        self._reconcile_loop = reconcile_loop
        self._journal = journal
        self._interval_seconds = interval_seconds
        self._periodic_max_rounds = periodic_max_rounds
        self._clock = clock
        self._last_tick_execution_seconds: float | None = None

        self.recent_reconcile_failures = 0
        self.last_report: ReconcileSupervisorReport | None = None

    def backlog_size(self) -> int:
        """Return current journal backlog size."""
        pending_count = getattr(self._reconcile_loop, "pending_issue_count", None)
        if callable(pending_count):
            return int(pending_count())
        return len(self._journal.list_issues())

    def dead_letter_count(self) -> int:
        """Return current dead-letter issue count."""
        dead_letters = getattr(self._reconcile_loop, "dead_letter_issues", None)
        if dead_letters is None:
            return 0
        return len(dead_letters)

    def run_manual(self, max_rounds: int) -> ReconcileSupervisorReport:
        """Run reconcile loop immediately with explicit max rounds."""
        if max_rounds < 1:
            msg = "max_rounds must be >= 1"
            raise ValueError(msg)

        return self._execute(
            trigger="manual",
            max_rounds=max_rounds,
            timestamp_seconds=self._clock(),
        )

    def tick(self) -> ReconcileSupervisorReport:
        """Run reconcile loop when interval threshold is met; otherwise skip."""
        now = self._clock()
        if self._should_execute_tick(now):
            self._last_tick_execution_seconds = now
            return self._execute(
                trigger="tick",
                max_rounds=self._periodic_max_rounds,
                timestamp_seconds=now,
            )

        report = ReconcileSupervisorReport(
            trigger="tick",
            executed=False,
            timestamp_seconds=now,
            backlog_size=self.backlog_size(),
            max_rounds=self._periodic_max_rounds,
            recent_reconcile_failures=self.recent_reconcile_failures,
            reconcile_report=None,
        )
        self.last_report = report
        return report

    def _should_execute_tick(self, now: float) -> bool:
        """Run _should_execute_tick."""
        if self._last_tick_execution_seconds is None:
            return True
        elapsed = now - self._last_tick_execution_seconds
        return elapsed >= self._interval_seconds

    def _execute(
        self,
        *,
        trigger: str,
        max_rounds: int,
        timestamp_seconds: float,
    ) -> ReconcileSupervisorReport:
        """Run _execute."""
        loop_report = self._reconcile_loop.run_until_clean(max_rounds=max_rounds)
        self.recent_reconcile_failures = loop_report.failed
        report = ReconcileSupervisorReport(
            trigger=trigger,
            executed=True,
            timestamp_seconds=timestamp_seconds,
            backlog_size=self.backlog_size(),
            max_rounds=max_rounds,
            recent_reconcile_failures=self.recent_reconcile_failures,
            reconcile_report=loop_report,
        )
        self.last_report = report
        return report
