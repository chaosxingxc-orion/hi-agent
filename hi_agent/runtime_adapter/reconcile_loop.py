"""Automatic reconcile loop utility for consistency issue recovery."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from hi_agent.runtime_adapter.consistency import ConsistencyIssue
from hi_agent.runtime_adapter.reconciler import ConsistencyReconciler


@dataclass(frozen=True, slots=True)
class ReconcileLoopReport:
    """Aggregated result for one or many reconcile rounds."""

    rounds: int
    applied: int
    failed: int
    skipped: int
    dead_letter_count: int


class _IssueListJournal:
    """In-memory journal adapter backed by an issue list snapshot."""

    def __init__(self, issues: list[ConsistencyIssue]) -> None:
        self._issues = issues

    def list_issues(self) -> list[ConsistencyIssue]:
        return list(self._issues)


class ReconcileLoop:
    """Run consistency reconciliation in rounds until clean or exhausted."""

    def __init__(
        self,
        backend: object,
        journal: object,
        *,
        max_issue_retries: int = 3,
        backoff_base_seconds: float = 0.5,
        backoff_multiplier: float = 2.0,
        max_backoff_seconds: float | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize reconcile loop policies and runtime dependencies."""
        if max_issue_retries < 1:
            raise ValueError("max_issue_retries must be >= 1")
        if backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds must be >= 0")
        if backoff_multiplier <= 0:
            raise ValueError("backoff_multiplier must be > 0")
        if max_backoff_seconds is not None and max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be >= 0")

        self._journal = journal
        self._reconciler = ConsistencyReconciler(backend)
        self._max_issue_retries = max_issue_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_multiplier = backoff_multiplier
        self._max_backoff_seconds = max_backoff_seconds
        self._sleep_fn = sleep_fn

        self._retry_counts: dict[str, int] = {}
        self._dead_letter: dict[str, ConsistencyIssue] = {}
        self._resolved_keys: set[str] = set()

    @property
    def dead_letter_issues(self) -> list[ConsistencyIssue]:
        """Return issues that exceeded retry limit."""
        return list(self._dead_letter.values())

    def pending_issue_count(self) -> int:
        """Return unresolved and non-dead-letter issue count."""
        return len(self._actionable_issues())

    def run_once(self) -> ReconcileLoopReport:
        """Run one reconciliation round for currently actionable issues."""
        issues = self._actionable_issues()
        if not issues:
            return ReconcileLoopReport(
                rounds=1,
                applied=0,
                failed=0,
                skipped=0,
                dead_letter_count=len(self._dead_letter),
            )

        round_result = self._reconciler.reconcile(_IssueListJournal(issues))
        applied = 0
        failed = 0
        skipped = 0

        for issue, status in zip(issues, round_result.issue_statuses, strict=True):
            issue_key = self._issue_key(issue)
            if status.status == "applied":
                applied += 1
                self._resolved_keys.add(issue_key)
                self._retry_counts.pop(issue_key, None)
                continue

            if status.status == "failed":
                attempts = self._retry_counts.get(issue_key, 0) + 1
                self._retry_counts[issue_key] = attempts
                if attempts >= self._max_issue_retries:
                    self._dead_letter.setdefault(issue_key, issue)
                    self._retry_counts.pop(issue_key, None)
                    skipped += 1
                else:
                    failed += 1
                continue

            skipped += 1

        return ReconcileLoopReport(
            rounds=1,
            applied=applied,
            failed=failed,
            skipped=skipped,
            dead_letter_count=len(self._dead_letter),
        )

    def run_until_clean(self, max_rounds: int) -> ReconcileLoopReport:
        """Run reconciliation rounds until no retryable failures remain."""
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")

        total_applied = 0
        total_skipped = 0
        rounds = 0
        remaining_failed = 0

        for _ in range(max_rounds):
            round_report = self.run_once()
            rounds += 1
            total_applied += round_report.applied
            total_skipped += round_report.skipped
            remaining_failed = round_report.failed

            if round_report.failed == 0:
                break

            if rounds < max_rounds:
                self._sleep_fn(self._backoff_for_round(rounds))

        return ReconcileLoopReport(
            rounds=rounds,
            applied=total_applied,
            failed=remaining_failed,
            skipped=total_skipped,
            dead_letter_count=len(self._dead_letter),
        )

    def _backoff_for_round(self, round_index: int) -> float:
        delay = self._backoff_base_seconds * (self._backoff_multiplier ** (round_index - 1))
        if self._max_backoff_seconds is not None:
            return min(delay, self._max_backoff_seconds)
        return delay

    def _actionable_issues(self) -> list[ConsistencyIssue]:
        issues = self._journal.list_issues()
        actionable: list[ConsistencyIssue] = []
        for issue in issues:
            issue_key = self._issue_key(issue)
            if issue_key in self._resolved_keys:
                continue
            if issue_key in self._dead_letter:
                continue
            actionable.append(issue)
        return actionable

    @staticmethod
    def _issue_key(issue: ConsistencyIssue) -> str:
        context = json.dumps(issue.context, sort_keys=True, separators=(",", ":"))
        return f"{issue.operation}|{context}|{issue.error}"
