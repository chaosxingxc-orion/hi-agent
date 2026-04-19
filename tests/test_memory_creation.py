"""Tests for automatic short-term memory creation after run execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.memory.short_term import ShortTermMemoryStore
from hi_agent.runner import RunExecutor
from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_executor(
    tmp_path: Path,
    *,
    task_id: str = "stm-test-001",
    goal: str = "test short-term memory creation",
    short_term_store: ShortTermMemoryStore | None = None,
) -> RunExecutor:
    """Helper: build a RunExecutor wired with a ShortTermMemoryStore."""
    contract = TaskContract(
        task_id=task_id,
        goal=goal,
        task_family="quick_task",
    )
    kernel = MockKernel(strict_mode=False)
    store = short_term_store or ShortTermMemoryStore(
        storage_dir=str(tmp_path / "stm")
    )
    return RunExecutor(contract, kernel, short_term_store=store)


# All five stage actions must fail for the run to be "failed".
_ALL_FAIL_CONSTRAINTS = [
    "fail_action:analyze_goal",
    "fail_action:search_evidence",
    "fail_action:build_draft",
    "fail_action:synthesize",
    "fail_action:evaluate_acceptance",
]


def _make_failing_executor(
    tmp_path: Path,
    *,
    task_id: str = "stm-fail-001",
    goal: str = "test STM on failure",
    short_term_store: ShortTermMemoryStore | None = None,
) -> RunExecutor:
    """Helper: build a RunExecutor that will fail during execution."""
    contract = TaskContract(
        task_id=task_id,
        goal=goal,
        task_family="quick_task",
        constraints=_ALL_FAIL_CONSTRAINTS,
    )
    kernel = MockKernel(strict_mode=False)
    store = short_term_store or ShortTermMemoryStore(
        storage_dir=str(tmp_path / "stm")
    )
    return RunExecutor(contract, kernel, short_term_store=store)


class TestSTMAfterSuccessfulRun:
    """Short-term memory is built and saved after a successful run."""

    def test_stm_built_after_completed_run(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        result = executor.execute()

        assert result == "completed"
        store = executor.short_term_store
        assert store is not None
        memories = store.list_recent(limit=5)
        assert len(memories) == 1
        assert memories[0].outcome == "completed"

    def test_stm_contains_correct_run_id(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path, task_id="stm-runid-check")
        executor.execute()

        store = executor.short_term_store
        assert store is not None
        memories = store.list_recent(limit=5)
        assert len(memories) == 1
        assert memories[0].run_id == executor.run_id

    def test_stm_contains_goal(self, tmp_path: Path) -> None:
        executor = _make_executor(
            tmp_path, goal="analyze quarterly revenue data"
        )
        executor.execute()

        store = executor.short_term_store
        assert store is not None
        memories = store.list_recent(limit=5)
        assert "quarterly revenue" in memories[0].task_goal

    def test_stm_contains_stages(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        executor.execute()

        store = executor.short_term_store
        assert store is not None
        memories = store.list_recent(limit=5)
        # Successful run should have completed stages
        assert len(memories[0].stages_completed) > 0


class TestSTMAfterFailedRun:
    """Short-term memory is built and saved after a failed run."""

    def test_stm_built_after_failed_run(self, tmp_path: Path) -> None:
        executor = _make_failing_executor(tmp_path)
        result = executor.execute()

        assert result == "failed"
        store = executor.short_term_store
        assert store is not None
        memories = store.list_recent(limit=5)
        assert len(memories) == 1

    def test_stm_outcome_reflects_failure(self, tmp_path: Path) -> None:
        executor = _make_failing_executor(tmp_path)
        executor.execute()

        store = executor.short_term_store
        assert store is not None
        memories = store.list_recent(limit=5)
        assert len(memories) == 1
        # The outcome should reflect the failed state
        mem = memories[0]
        assert mem.run_id == executor.run_id


class TestSTMFileOnDisk:
    """Short-term memory file is persisted to disk."""

    def test_stm_file_exists_after_run(self, tmp_path: Path) -> None:
        stm_dir = tmp_path / "stm"
        store = ShortTermMemoryStore(storage_dir=str(stm_dir))
        executor = _make_executor(tmp_path, short_term_store=store)
        executor.execute()

        # The STM directory should now exist with a JSON file
        assert stm_dir.exists()
        json_files = [f for f in stm_dir.glob("*.json") if f.name != "_manifest.json"]
        assert len(json_files) == 1

    def test_stm_file_contains_valid_json(self, tmp_path: Path) -> None:
        stm_dir = tmp_path / "stm"
        store = ShortTermMemoryStore(storage_dir=str(stm_dir))
        executor = _make_executor(tmp_path, short_term_store=store)
        executor.execute()

        json_files = [f for f in stm_dir.glob("*.json") if f.name != "_manifest.json"]
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert "session_id" in data
        assert "run_id" in data
        assert "task_goal" in data
        assert "outcome" in data

    def test_stm_loadable_from_store(self, tmp_path: Path) -> None:
        stm_dir = tmp_path / "stm"
        store = ShortTermMemoryStore(storage_dir=str(stm_dir))
        executor = _make_executor(tmp_path, short_term_store=store)
        executor.execute()

        # Load via the store API
        memories = store.list_recent(limit=5)
        assert len(memories) == 1
        loaded = store.load(memories[0].session_id)
        assert loaded is not None
        assert loaded.run_id == executor.run_id


class TestBackwardCompatibility:
    """short_term_store=None preserves existing behavior."""

    def test_no_store_no_error(self) -> None:
        contract = TaskContract(
            task_id="compat-001", goal="backward compat test"
        )
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel)
        assert executor.short_term_store is None

        result = executor.execute()
        assert result == "completed"

    def test_no_store_failed_run_no_error(self) -> None:
        contract = TaskContract(
            task_id="compat-002",
            goal="backward compat fail test",
            constraints=_ALL_FAIL_CONSTRAINTS,
        )
        kernel = MockKernel(strict_mode=False)
        executor = RunExecutor(contract, kernel)
        assert executor.short_term_store is None

        result = executor.execute()
        assert result == "failed"
