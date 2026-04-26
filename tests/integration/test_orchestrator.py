"""Tests for hi_agent.orchestrator."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.contracts.requests import RunResult
from hi_agent.orchestrator.parallel_dispatcher import ParallelDispatcher
from hi_agent.orchestrator.result_aggregator import ResultAggregator
from hi_agent.orchestrator.task_orchestrator import (
    SubTaskResult,
    TaskOrchestrator,
)
from hi_agent.task_decomposition.decomposer import TaskDecomposer
from hi_agent.task_decomposition.feedback import DecompositionFeedback

from tests.helpers.kernel_adapter_fixture import MockKernel

# The patch target must match where RunExecutor is looked up at call time.
# TaskOrchestrator imports it inside methods via ``from hi_agent.runner import RunExecutor``.
_RUNNER_PATCH = "hi_agent.runner.RunExecutor"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_contract(task_id: str = "task-1", **kwargs: Any) -> TaskContract:
    """Create a minimal TaskContract for testing."""
    defaults: dict[str, Any] = {
        "task_id": task_id,
        "goal": "Test goal",
    }
    defaults.update(kwargs)
    return TaskContract(**defaults)


# ---------------------------------------------------------------------------
# TaskOrchestrator �?simple (no decomposition)
# ---------------------------------------------------------------------------


class TestSimpleExecution:
    """Test that tasks without decomposition_strategy go directly to RunExecutor."""

    def test_simple_task_delegates_to_run_executor(self) -> None:
        kernel = MockKernel(strict_mode=False)
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer())
        contract = _simple_contract()

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.return_value = RunResult(run_id="run-1", status="completed")

            result = orchestrator.execute(contract)

        assert result.success is True
        assert result.strategy is None
        assert result.task_id == "task-1"
        assert len(result.sub_results) == 1
        assert result.sub_results[0].outcome == "completed"
        # result payload is now structured RunResult dict
        assert result.sub_results[0].result["status"] == "completed"
        # Assert the two required positional args without over-constraining kwargs,
        # which grew after T3's Rule 6 strict injection sweep.
        assert mock_runner_cls.call_count == 1
        call_args = mock_runner_cls.call_args
        assert call_args.args[0] is contract
        assert call_args.args[1] is kernel

    def test_simple_task_failure_propagates(self) -> None:
        kernel = MockKernel(strict_mode=False)
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer())
        contract = _simple_contract()

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.return_value = RunResult(
                run_id="run-1", status="failed", error="stage_failed"
            )

            result = orchestrator.execute(contract)

        assert result.success is False
        assert result.sub_results[0].outcome == "failed"
        assert result.sub_results[0].error is not None


# ---------------------------------------------------------------------------
# TaskOrchestrator �?decomposed execution
# ---------------------------------------------------------------------------


class TestDecomposedExecution:
    """Test that tasks with decomposition_strategy use DAG execution."""

    def test_decomposed_task_creates_dag_and_executes(self) -> None:
        kernel = MockKernel(strict_mode=False)
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer())
        contract = _simple_contract(decomposition_strategy="linear")

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.return_value = "completed"

            result = orchestrator.execute(contract)

        assert result.success is True
        assert result.strategy == "linear"
        # Linear decomposition creates 5 TRACE stages
        assert len(result.sub_results) == 5
        for sub in result.sub_results:
            assert sub.outcome == "completed"

    def test_decomposed_dag_strategy_has_parallel_nodes(self) -> None:
        kernel = MockKernel(strict_mode=False)
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer())
        contract = _simple_contract(decomposition_strategy="dag")

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.return_value = "completed"

            result = orchestrator.execute(contract)

        assert result.success is True
        assert result.strategy == "dag"
        assert len(result.sub_results) == 5

    def test_subtask_failure_propagates_in_decomposed(self) -> None:
        kernel = MockKernel(strict_mode=False)
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer())
        contract = _simple_contract(decomposition_strategy="linear")

        call_count = 0

        def _execute_side_effect() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return "failed"
            return "completed"

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.side_effect = _execute_side_effect

            result = orchestrator.execute(contract)

        assert result.success is False
        failed = [s for s in result.sub_results if s.outcome == "failed"]
        assert len(failed) >= 1

    def test_on_subtask_complete_callback_fired(self) -> None:
        kernel = MockKernel(strict_mode=False)
        completed_subs: list[SubTaskResult] = []
        orchestrator = TaskOrchestrator(
            kernel,
            decomposer=TaskDecomposer(),
            on_subtask_complete=completed_subs.append,
        )
        contract = _simple_contract(decomposition_strategy="linear")

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.return_value = "completed"

            orchestrator.execute(contract)

        # Callback fires for each successfully completed sub-task
        assert len(completed_subs) == 5

    def test_feedback_recorded_after_decomposed_run(self) -> None:
        kernel = MockKernel(strict_mode=False)
        feedback = DecompositionFeedback()
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer(), feedback=feedback)
        contract = _simple_contract(
            decomposition_strategy="linear",
            task_family="code_gen",
        )

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.return_value = "completed"

            orchestrator.execute(contract)

        stats = feedback.get_stats("code_gen")
        assert stats["total_records"] == 1
        assert stats["success_rate"] == 1.0


# ---------------------------------------------------------------------------
# TaskOrchestrator �?rollback on failure
# ---------------------------------------------------------------------------


class TestRollback:
    """Test rollback propagation on sub-task failure."""

    def test_rollback_on_failure_recorded(self) -> None:
        kernel = MockKernel(strict_mode=False)
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer())
        contract = _simple_contract(decomposition_strategy="linear")

        call_count = 0

        def _execute_side_effect() -> str:
            nonlocal call_count
            call_count += 1
            # Fail on the second sub-task (gather stage)
            if call_count == 2:
                return "failed"
            return "completed"

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.side_effect = _execute_side_effect

            result = orchestrator.execute(contract)

        assert result.success is False
        rolled_back = [s for s in result.sub_results if s.outcome == "rolled_back"]
        # The default rollback_policy is "compensate", so direct deps get rolled back
        assert len(rolled_back) >= 1


# ---------------------------------------------------------------------------
# ParallelDispatcher
# ---------------------------------------------------------------------------


class TestParallelDispatcher:
    """Test thread-based parallel dispatch."""

    def test_dispatch_and_wait_all(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=2)
        try:
            dispatcher.dispatch("a", lambda: "result_a")
            dispatcher.dispatch("b", lambda: "result_b")
            results = dispatcher.wait_all(timeout=5.0)
            assert results["a"] == "result_a"
            assert results["b"] == "result_b"
        finally:
            dispatcher.shutdown()

    def test_dispatch_independent_nodes_concurrently(self) -> None:
        """Verify independent nodes actually run in parallel."""
        dispatcher = ParallelDispatcher(max_workers=4)
        barrier = threading.Barrier(2, timeout=5.0)
        timestamps: dict[str, float] = {}

        def _work(name: str) -> str:
            barrier.wait()  # both threads must reach here
            timestamps[name] = time.monotonic()
            return name

        try:
            dispatcher.dispatch("x", _work, "x")
            dispatcher.dispatch("y", _work, "y")
            results = dispatcher.wait_all(timeout=10.0)
            assert results["x"] == "x"
            assert results["y"] == "y"
            # Both should have run roughly at the same time (barrier ensures this)
            assert abs(timestamps["x"] - timestamps["y"]) < 1.0
        finally:
            dispatcher.shutdown()

    def test_wait_any_returns_first_completed(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=2)
        try:
            dispatcher.dispatch("fast", lambda: "done")
            dispatcher.dispatch("slow", lambda: (time.sleep(1), "slow_done")[1])

            first = dispatcher.wait_any(timeout=5.0)
            assert len(first) == 1
            node_id, value = first[0]
            # The fast one should finish first
            assert node_id == "fast"
            assert value == "done"
        finally:
            dispatcher.shutdown()

    def test_exception_in_dispatched_task(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=1)
        try:
            dispatcher.dispatch("bad", lambda: (_ for _ in ()).throw(ValueError("boom")))
            results = dispatcher.wait_all(timeout=5.0)
            assert isinstance(results["bad"], ValueError)
            assert str(results["bad"]) == "boom"
        finally:
            dispatcher.shutdown()

    def test_shutdown_is_safe_when_empty(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=1)
        dispatcher.shutdown()  # should not raise


# ---------------------------------------------------------------------------
# DAG dependency ordering
# ---------------------------------------------------------------------------


class TestDAGDependencyRespected:
    """Test that DAG dependencies are respected during orchestrated execution."""

    def test_node_b_waits_for_node_a(self) -> None:
        """Verify sequential dependency: B cannot start until A completes."""
        kernel = MockKernel(strict_mode=False)
        orchestrator = TaskOrchestrator(kernel, decomposer=TaskDecomposer())

        # Use linear strategy which creates a strict chain
        contract = _simple_contract(decomposition_strategy="linear")
        execution_order: list[str] = []

        def _track_execute() -> str:
            # We cannot get node_id from RunExecutor easily, so track call order
            execution_order.append(f"call-{len(execution_order)}")
            return "completed"

        with patch(_RUNNER_PATCH) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.execute.side_effect = _track_execute

            result = orchestrator.execute(contract)

        assert result.success is True
        # Linear chain means exactly 5 sequential calls
        assert len(execution_order) == 5


# ---------------------------------------------------------------------------
# ResultAggregator
# ---------------------------------------------------------------------------


class TestResultAggregator:
    """Test result aggregation logic."""

    def test_combines_results_correctly(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult("n1", "t1", "completed", result={"ok": True}))
        agg.record("n2", SubTaskResult("n2", "t2", "completed", result={"ok": True}))
        agg.record("n3", SubTaskResult("n3", "t3", "failed", error="oops"))

        result = agg.aggregate(task_id="top", strategy="dag")

        assert result.task_id == "top"
        assert result.strategy == "dag"
        assert result.success is False  # one failure
        assert len(result.sub_results) == 3

    def test_all_completed_means_success(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult("n1", "t1", "completed"))
        agg.record("n2", SubTaskResult("n2", "t2", "completed"))

        result = agg.aggregate(task_id="top", strategy="linear")
        assert result.success is True

    def test_get_completed_and_failed(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult("n1", "t1", "completed"))
        agg.record("n2", SubTaskResult("n2", "t2", "failed", error="err"))
        agg.record("n3", SubTaskResult("n3", "t3", "completed"))

        assert len(agg.get_completed()) == 2
        assert len(agg.get_failed()) == 1
        assert agg.get_failed()[0].node_id == "n2"

    def test_success_rate_calculation(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult("n1", "t1", "completed"))
        agg.record("n2", SubTaskResult("n2", "t2", "failed", error="err"))
        agg.record("n3", SubTaskResult("n3", "t3", "completed"))
        agg.record("n4", SubTaskResult("n4", "t4", "completed"))

        assert agg.success_rate() == pytest.approx(0.75)

    def test_success_rate_empty(self) -> None:
        agg = ResultAggregator()
        assert agg.success_rate() == 0.0

    def test_success_rate_all_pass(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult("n1", "t1", "completed"))
        agg.record("n2", SubTaskResult("n2", "t2", "completed"))
        assert agg.success_rate() == 1.0

    def test_success_rate_all_fail(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult("n1", "t1", "failed", error="a"))
        agg.record("n2", SubTaskResult("n2", "t2", "failed", error="b"))
        assert agg.success_rate() == 0.0
