"""Tests for P-4 StageDirective / replan_hook and P-7 FeedbackStore."""

from __future__ import annotations

from pathlib import Path

from hi_agent.contracts import TaskContract
from hi_agent.contracts.directives import StageDirective
from hi_agent.evolve.feedback_store import FeedbackStore, RunFeedback
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# StageDirective unit tests
# ---------------------------------------------------------------------------


def test_stage_directive_default() -> None:
    """StageDirective() defaults to action='continue'."""
    d = StageDirective()
    assert d.action == "continue"
    assert d.target_stage_id == ""
    assert d.new_stage_specs == []
    assert d.reason == ""


# ---------------------------------------------------------------------------
# FeedbackStore unit tests
# ---------------------------------------------------------------------------


def test_feedback_store_submit_get() -> None:
    """Submit then get returns the same record."""
    store = FeedbackStore()
    fb = RunFeedback(run_id="run-001", rating=0.9, notes="great")
    store.submit(fb)
    result = store.get("run-001")
    assert result is not None
    assert result.run_id == "run-001"
    assert result.rating == 0.9
    assert result.notes == "great"


def test_feedback_store_get_missing() -> None:
    """get() returns None for an unknown run_id."""
    store = FeedbackStore()
    assert store.get("no-such-run") is None


def test_feedback_store_list_recent() -> None:
    """list_recent returns records sorted by submitted_at descending."""
    store = FeedbackStore()
    store.submit(RunFeedback(run_id="run-a", rating=0.3, submitted_at="2026-01-01T00:00:00+00:00"))
    store.submit(RunFeedback(run_id="run-b", rating=0.7, submitted_at="2026-01-03T00:00:00+00:00"))
    store.submit(RunFeedback(run_id="run-c", rating=0.5, submitted_at="2026-01-02T00:00:00+00:00"))
    records = store.list_recent()
    assert [r.run_id for r in records[:3]] == ["run-b", "run-c", "run-a"]


def test_feedback_store_list_recent_limit() -> None:
    """list_recent respects the limit parameter."""
    store = FeedbackStore()
    for i in range(10):
        store.submit(RunFeedback(run_id=f"run-{i:02d}", rating=0.5))
    assert len(store.list_recent(limit=3)) == 3


def test_feedback_store_overwrite() -> None:
    """Submitting again for the same run_id overwrites the prior record."""
    store = FeedbackStore()
    store.submit(RunFeedback(run_id="run-x", rating=0.2))
    store.submit(RunFeedback(run_id="run-x", rating=0.8, notes="updated"))
    result = store.get("run-x")
    assert result is not None
    assert result.rating == 0.8
    assert result.notes == "updated"


def test_feedback_store_persist_load(tmp_path: Path) -> None:
    """FeedbackStore persists to disk and reloads correctly."""
    store_path = tmp_path / "feedback.json"
    store = FeedbackStore(storage_path=store_path)
    store.submit(RunFeedback(run_id="run-persist", rating=0.75, notes="persisted"))

    store2 = FeedbackStore(storage_path=store_path)
    result = store2.get("run-persist")
    assert result is not None
    assert result.rating == 0.75


# ---------------------------------------------------------------------------
# RunExecutor replan_hook integration tests
# ---------------------------------------------------------------------------


def test_replan_hook_called() -> None:
    """replan_hook is invoked after each stage completes."""
    contract = TaskContract(task_id="replan-001", goal="hook test")
    kernel = MockKernel()
    called_stages: list[str] = []

    def my_hook(stage_id: str, result: dict) -> StageDirective | None:
        called_stages.append(stage_id)
        return StageDirective(action="continue")

    executor = RunExecutor(contract, kernel, replan_hook=my_hook)
    result = executor.execute()

    assert result == "completed"
    assert len(called_stages) > 0


def test_replan_hook_skip() -> None:
    """replan_hook with action='skip' removes target stage from remaining."""
    contract = TaskContract(task_id="replan-002", goal="skip test")
    kernel = MockKernel()

    stages_executed: list[str] = []
    hook_calls = 0

    def my_hook(stage_id: str, result: dict) -> StageDirective | None:
        nonlocal hook_calls
        hook_calls += 1
        stages_executed.append(stage_id)
        # After first stage, skip S3_evaluate
        if hook_calls == 1:
            return StageDirective(action="skip", target_stage_id="S3_evaluate", reason="test skip")
        return None

    executor = RunExecutor(contract, kernel, replan_hook=my_hook)
    executor.execute()

    assert "S3_evaluate" not in executor.stage_summaries


def test_replan_hook_none_action_continues() -> None:
    """replan_hook returning None does not disrupt execution."""
    contract = TaskContract(task_id="replan-003", goal="none hook")
    kernel = MockKernel()

    def my_hook(stage_id: str, result: dict) -> StageDirective | None:
        return None

    executor = RunExecutor(contract, kernel, replan_hook=my_hook)
    result = executor.execute()
    assert result == "completed"


# ---------------------------------------------------------------------------
# feedback_store wired into _finalize_run
# ---------------------------------------------------------------------------


def test_feedback_store_auto_submit_on_finalize() -> None:
    """FeedbackStore receives a neutral record when run completes."""
    contract = TaskContract(task_id="fb-001", goal="feedback auto submit")
    kernel = MockKernel()
    store = FeedbackStore()

    executor = RunExecutor(contract, kernel, feedback_store=store)
    executor.execute()

    record = store.get(executor.run_id)
    assert record is not None
    assert record.rating == 0.5
