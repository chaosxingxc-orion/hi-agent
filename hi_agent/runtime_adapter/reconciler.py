"""Consistency reconciler that replays journaled backend issues."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.consistency import ConsistencyIssue


class _ConsistencyJournal(Protocol):
    """Journal contract needed by reconciler."""

    def list_issues(self) -> list[ConsistencyIssue]:
        """Return consistency issues to reconcile."""


@dataclass(frozen=True, slots=True)
class ConsistencyIssueStatus:
    """Per-issue reconciliation status."""

    operation: str
    status: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ConsistencyReconcileReport:
    """Aggregated reconciliation result."""

    total: int
    applied: int
    failed: int
    skipped: int
    issue_statuses: list[ConsistencyIssueStatus]


class ConsistencyReconciler:
    """Replay consistency journal issues against backend hooks."""

    def __init__(self, backend: object) -> None:
        """Store backend hook provider used for reconciliation."""
        self._backend = backend

    def reconcile(self, journal: _ConsistencyJournal) -> ConsistencyReconcileReport:
        """Replay all issues from ``journal`` and return a status report."""
        issue_statuses: list[ConsistencyIssueStatus] = []
        applied = 0
        failed = 0
        skipped = 0

        for issue in journal.list_issues():
            status = self._reconcile_issue(issue)
            issue_statuses.append(status)
            if status.status == "applied":
                applied += 1
            elif status.status == "failed":
                failed += 1
            else:
                skipped += 1

        return ConsistencyReconcileReport(
            total=len(issue_statuses),
            applied=applied,
            failed=failed,
            skipped=skipped,
            issue_statuses=issue_statuses,
        )

    def _reconcile_issue(self, issue: ConsistencyIssue) -> ConsistencyIssueStatus:
        """Apply one issue safely, returning ``applied``/``failed``/``skipped``."""
        if issue.operation == "open_stage":
            stage_id = issue.context.get("stage_id")
            if not isinstance(stage_id, str):
                return ConsistencyIssueStatus(
                    operation=issue.operation,
                    status="failed",
                    detail="malformed context: stage_id must be str",
                )
            return self._invoke(issue.operation, stage_id)

        if issue.operation == "mark_stage_state":
            stage_id = issue.context.get("stage_id")
            target_state = issue.context.get("target_state")
            if not isinstance(stage_id, str) or not isinstance(target_state, str):
                return ConsistencyIssueStatus(
                    operation=issue.operation,
                    status="failed",
                    detail="malformed context: stage_id/target_state must be str",
                )
            try:
                target = StageState(target_state)
            except ValueError:
                return ConsistencyIssueStatus(
                    operation=issue.operation,
                    status="failed",
                    detail=f"malformed context: unsupported target_state={target_state}",
                )
            return self._invoke(issue.operation, stage_id, target)

        if issue.operation == "record_task_view":
            task_view_id = issue.context.get("task_view_id")
            if not isinstance(task_view_id, str):
                return ConsistencyIssueStatus(
                    operation=issue.operation,
                    status="failed",
                    detail="malformed context: task_view_id must be str",
                )

            content = {k: v for k, v in issue.context.items() if k != "task_view_id"}
            return self._invoke(issue.operation, task_view_id, content)

        return ConsistencyIssueStatus(
            operation=issue.operation,
            status="skipped",
            detail=f"unknown operation: {issue.operation}",
        )

    def _invoke(self, operation: str, *args: Any) -> ConsistencyIssueStatus:
        hook = getattr(self._backend, operation, None)
        if not callable(hook):
            return ConsistencyIssueStatus(
                operation=operation,
                status="skipped",
                detail=f"backend hook unavailable: {operation}",
            )
        try:
            hook(*args)
        except Exception as exc:
            return ConsistencyIssueStatus(
                operation=operation,
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
        return ConsistencyIssueStatus(operation=operation, status="applied")
