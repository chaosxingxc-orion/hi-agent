"""Unit tests for _make_subrun_done_callback (J6-1 fix).

Verifies that asyncio-level task failures are stored into the results dict
so that await_subrun() callers never hang or get a KeyError.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.runner import SubRunResult, _make_subrun_done_callback


def _make_failed_task(exc: Exception) -> MagicMock:
    """Create a mock asyncio.Task that raised exc."""
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = exc
    return task


def _make_cancelled_task() -> MagicMock:
    """Create a mock asyncio.Task that was cancelled."""
    task = MagicMock()
    task.cancelled.return_value = True
    return task


def _make_success_task() -> MagicMock:
    """Create a mock asyncio.Task that completed normally."""
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = None
    return task


class TestMakeSubrunDoneCallback:
    """Tests for the _make_subrun_done_callback factory."""

    def test_failed_task_stores_error_result(self) -> None:
        """Task that raised an exception should populate results_dict with failure."""
        results: dict[str, object] = {}
        task_id = "run-abc-123"
        cb = _make_subrun_done_callback(results, task_id)

        task = _make_failed_task(ValueError("boom"))
        cb(task)

        assert task_id in results
        result = results[task_id]
        assert isinstance(result, SubRunResult)
        assert result.success is False
        assert "boom" in result.output

    def test_cancelled_task_stores_cancelled_result(self) -> None:
        """Cancelled task should populate results_dict with cancelled failure."""
        results: dict[str, object] = {}
        task_id = "run-xyz-999"
        cb = _make_subrun_done_callback(results, task_id)

        task = _make_cancelled_task()
        cb(task)

        assert task_id in results
        result = results[task_id]
        assert isinstance(result, SubRunResult)
        assert result.success is False
        assert result.output == "cancelled"

    def test_successful_task_does_not_overwrite_results(self) -> None:
        """Successful task completion should not write to results_dict.

        The normal-completion result is handled by await_subrun via the future,
        not by this callback.
        """
        results: dict[str, object] = {}
        task_id = "run-ok-001"
        cb = _make_subrun_done_callback(results, task_id)

        task = _make_success_task()
        cb(task)

        assert task_id not in results

    def test_factory_creates_independent_callbacks(self) -> None:
        """Each call to _make_subrun_done_callback binds its own task_id."""
        results: dict[str, object] = {}
        cb1 = _make_subrun_done_callback(results, "id-1")
        cb2 = _make_subrun_done_callback(results, "id-2")

        cb1(_make_failed_task(RuntimeError("err1")))
        cb2(_make_cancelled_task())

        assert "id-1" in results
        assert "id-2" in results
        assert results["id-1"].success is False  # type: ignore[union-attr]
        assert results["id-2"].output == "cancelled"  # type: ignore[union-attr]
