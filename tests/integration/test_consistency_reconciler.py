"""Integration tests for consistency issue reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hi_agent.runtime_adapter import (
    ConsistencyIssue,
    ConsistencyReconciler,
    FileBackedConsistencyJournal,
    InMemoryConsistencyJournal,
)


class _BackendRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def open_stage(self, stage_id: str) -> None:
        self.calls.append(("open_stage", (stage_id,)))

    def mark_stage_state(self, stage_id: str, target: str) -> None:
        self.calls.append(("mark_stage_state", (stage_id, target)))

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> str:
        self.calls.append(("record_task_view", (task_view_id, content)))
        return task_view_id


class _BackendWithMarkFailure(_BackendRecorder):
    def mark_stage_state(self, stage_id: str, target: str) -> None:
        self.calls.append(("mark_stage_state", (stage_id, target)))
        raise RuntimeError("backend mark failed")


def test_reconciler_replays_supported_operations_from_in_memory_journal() -> None:
    """Supported operations should replay from in-memory journal contexts."""
    journal = InMemoryConsistencyJournal()
    journal.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S1_understand"},
            error="RuntimeError: open failed",
        )
    )
    journal.append(
        ConsistencyIssue(
            operation="mark_stage_state",
            context={"stage_id": "S1_understand", "target_state": "active"},
            error="RuntimeError: mark failed",
        )
    )
    journal.append(
        ConsistencyIssue(
            operation="record_task_view",
            context={
                "task_view_id": "tv-1",
                "run_id": "run-1",
                "stage_id": "S1_understand",
            },
            error="RuntimeError: task view failed",
        )
    )
    backend = _BackendRecorder()
    reconciler = ConsistencyReconciler(backend)

    report = reconciler.reconcile(journal)

    assert [status.status for status in report.issue_statuses] == ["applied"] * 3
    assert report.total == 3
    assert report.applied == 3
    assert report.failed == 0
    assert report.skipped == 0
    assert backend.calls == [
        ("open_stage", ("S1_understand",)),
        ("mark_stage_state", ("S1_understand", "active")),
        (
            "record_task_view",
            ("tv-1", {"run_id": "run-1", "stage_id": "S1_understand"}),
        ),
    ]


def test_reconciler_handles_unknown_or_malformed_issues_and_continues() -> None:
    """Unknown or malformed issues should not block remaining reconciliations."""
    journal = InMemoryConsistencyJournal()
    journal.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S1_understand"},
            error="RuntimeError: open failed",
        )
    )
    journal.append(
        ConsistencyIssue(
            operation="unknown_operation",
            context={},
            error="RuntimeError: unknown",
        )
    )
    journal.append(
        ConsistencyIssue(
            operation="mark_stage_state",
            context={"stage_id": "S1_understand"},
            error="RuntimeError: malformed mark",
        )
    )
    journal.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S2_plan"},
            error="RuntimeError: open failed",
        )
    )
    backend = _BackendRecorder()
    reconciler = ConsistencyReconciler(backend)

    report = reconciler.reconcile(journal)

    assert [status.status for status in report.issue_statuses] == [
        "applied",
        "skipped",
        "failed",
        "applied",
    ]
    assert report.total == 4
    assert report.applied == 2
    assert report.failed == 1
    assert report.skipped == 1
    assert backend.calls == [
        ("open_stage", ("S1_understand",)),
        ("open_stage", ("S2_plan",)),
    ]


def test_reconciler_marks_backend_exceptions_as_failed_and_continues() -> None:
    """Backend exceptions should be marked failed and reconciliation should continue."""
    journal = InMemoryConsistencyJournal()
    journal.append(
        ConsistencyIssue(
            operation="mark_stage_state",
            context={"stage_id": "S1_understand", "target_state": "active"},
            error="RuntimeError: mark failed",
        )
    )
    journal.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S2_plan"},
            error="RuntimeError: open failed",
        )
    )
    backend = _BackendWithMarkFailure()
    reconciler = ConsistencyReconciler(backend)

    report = reconciler.reconcile(journal)

    assert [status.status for status in report.issue_statuses] == ["failed", "applied"]
    assert report.total == 2
    assert report.applied == 1
    assert report.failed == 1
    assert report.skipped == 0
    assert backend.calls == [
        ("mark_stage_state", ("S1_understand", "active")),
        ("open_stage", ("S2_plan",)),
    ]


def test_reconciler_supports_file_backed_consistency_journal(tmp_path: Path) -> None:
    """Reconciler should work with file-backed journals through list_issues()."""
    journal = FileBackedConsistencyJournal(tmp_path / "consistency.journal")
    journal.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S1_understand"},
            error="RuntimeError: open failed",
        )
    )
    backend = _BackendRecorder()
    reconciler = ConsistencyReconciler(backend)

    report = reconciler.reconcile(journal)

    assert report.total == 1
    assert report.applied == 1
    assert report.failed == 0
    assert report.skipped == 0
    assert [status.status for status in report.issue_statuses] == ["applied"]
    assert backend.calls == [("open_stage", ("S1_understand",))]
