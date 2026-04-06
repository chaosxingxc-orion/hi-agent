"""End-to-end integration test for consistency issue generation and reconcile cleanup."""

from __future__ import annotations

import pytest
from hi_agent.contracts import StageState
from hi_agent.runtime_adapter import (
    ConsistencyReconciler,
    FileBackedConsistencyJournal,
    KernelAdapter,
    RuntimeAdapterBackendError,
)


class _FailingOpenBackend:
    """Backend that always fails open_stage to trigger consistency issue logging."""

    def open_stage(self, stage_id: str) -> None:
        raise RuntimeError(f"backend open_stage failed for {stage_id}")


class _HealthyOpenBackend:
    """Backend that records open_stage replay calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def open_stage(self, stage_id: str) -> None:
        self.calls.append(("open_stage", stage_id))


def test_e2e_consistency_issue_generation_to_reconcile_loop_cleanup(tmp_path) -> None:
    """Recoverable backend failures should reconcile cleanly with no dead letters."""
    stage_id = "S1_understand"
    journal = FileBackedConsistencyJournal(tmp_path / "consistency.journal")

    failing_adapter = KernelAdapter(
        strict_mode=True,
        backend=_FailingOpenBackend(),
        consistency_journal=journal,
    )

    with pytest.raises(RuntimeAdapterBackendError):
        failing_adapter.open_stage(stage_id)

    # Local mutation remains committed while backend write failure is journaled.
    assert failing_adapter.stages[stage_id] == StageState.PENDING
    issues = journal.list_issues()
    assert len(issues) == 1
    assert issues[0].operation == "open_stage"
    assert issues[0].context == {"stage_id": stage_id}

    healthy_backend = _HealthyOpenBackend()
    report = ConsistencyReconciler(healthy_backend).reconcile(journal)

    assert report.total == 1
    assert report.applied == 1
    assert report.failed == 0
    assert report.skipped == 0
    assert [status.status for status in report.issue_statuses] == ["applied"]
    assert healthy_backend.calls == [("open_stage", stage_id)]

    # Reconcile-loop cleanup model: applied issues are removed from retry/dead-letter sets.
    remaining_for_retry = [
        issue
        for issue, status in zip(journal.list_issues(), report.issue_statuses, strict=True)
        if status.status != "applied"
    ]
    dead_letters = [
        issue
        for issue, status in zip(journal.list_issues(), report.issue_statuses, strict=True)
        if status.status == "failed"
    ]
    assert remaining_for_retry == []
    assert dead_letters == []
