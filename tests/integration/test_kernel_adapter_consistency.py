"""Integration tests for KernelAdapter consistency compensation journal."""

import pytest
from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_adapter import KernelAdapter


class _OpenFailBackend:
    def open_stage(self, stage_id: str) -> None:
        raise RuntimeError(f"open failed: {stage_id}")


class _MarkFailBackend:
    def open_stage(self, stage_id: str) -> None:
        _ = stage_id

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        raise RuntimeError(f"mark failed: {stage_id}:{target}")


class _TaskViewFailBackend:
    def record_task_view(self, task_view_id: str, content: dict[str, object]) -> str:
        _ = content
        raise RuntimeError(f"task view failed: {task_view_id}")


def test_open_stage_backend_failure_records_consistency_issue() -> None:
    """Open-stage backend failure should be journaled for compensation."""
    journal = InMemoryConsistencyJournal()
    adapter = KernelAdapter(
        strict_mode=True,
        backend=_OpenFailBackend(),
        consistency_journal=journal,
    )

    with pytest.raises(RuntimeAdapterBackendError):
        adapter.open_stage("S1_understand")

    issues = journal.list_issues()
    assert len(issues) == 1
    assert issues[0].operation == "open_stage"
    assert issues[0].context["stage_id"] == "S1_understand"
    assert "RuntimeError" in issues[0].error


def test_mark_stage_state_backend_failure_records_consistency_issue() -> None:
    """Stage-state backend failure should be journaled with stage context."""
    journal = InMemoryConsistencyJournal()
    adapter = KernelAdapter(
        strict_mode=True,
        backend=_MarkFailBackend(),
        consistency_journal=journal,
    )
    adapter.open_stage("S1_understand")

    with pytest.raises(RuntimeAdapterBackendError):
        adapter.mark_stage_state("S1_understand", StageState.ACTIVE)

    issues = journal.list_issues()
    assert len(issues) == 1
    assert issues[0].operation == "mark_stage_state"
    assert issues[0].context["stage_id"] == "S1_understand"
    assert issues[0].context["target_state"] == "active"
    assert "RuntimeError" in issues[0].error


def test_record_task_view_backend_failure_records_consistency_issue() -> None:
    """Task-view backend failure should be journaled with payload context."""
    journal = InMemoryConsistencyJournal()
    adapter = KernelAdapter(
        strict_mode=True,
        backend=_TaskViewFailBackend(),
        consistency_journal=journal,
    )

    with pytest.raises(RuntimeAdapterBackendError):
        adapter.record_task_view("tv-1", {"run_id": "run-1", "stage_id": "S1_understand"})

    issues = journal.list_issues()
    assert len(issues) == 1
    assert issues[0].operation == "record_task_view"
    assert issues[0].context["task_view_id"] == "tv-1"
    assert issues[0].context["run_id"] == "run-1"
    assert issues[0].context["stage_id"] == "S1_understand"
    assert "RuntimeError" in issues[0].error
