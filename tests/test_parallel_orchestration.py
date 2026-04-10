"""Tests for parallel orchestration: dispatcher and result aggregator."""

from __future__ import annotations

import time

import pytest

from hi_agent.orchestrator.parallel_dispatcher import ParallelDispatcher
from hi_agent.orchestrator.result_aggregator import ResultAggregator
from hi_agent.orchestrator.task_orchestrator import SubTaskResult


# ---------------------------------------------------------------------------
# ParallelDispatcher
# ---------------------------------------------------------------------------


class TestParallelDispatcher:
    def test_dispatch_three_tasks(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=3)
        try:
            for i in range(3):
                dispatcher.dispatch(f"node-{i}", lambda x=i: x * 10)
            results = dispatcher.wait_all(timeout=5)
            assert len(results) == 3
            assert results["node-0"] == 0
            assert results["node-1"] == 10
            assert results["node-2"] == 20
        finally:
            dispatcher.shutdown()

    def test_failure_captured_as_exception(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=2)
        try:
            def fail():
                raise ValueError("task error")

            dispatcher.dispatch("bad", fail)
            results = dispatcher.wait_all(timeout=5)
            assert isinstance(results["bad"], ValueError)
            assert "task error" in str(results["bad"])
        finally:
            dispatcher.shutdown()

    def test_wait_any_returns_at_least_one(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=2)
        try:
            dispatcher.dispatch("a", lambda: "done-a")
            dispatcher.dispatch("b", lambda: "done-b")
            results = dispatcher.wait_any(timeout=5)
            assert len(results) >= 1
            node_id, value = results[0]
            assert node_id in ("a", "b")
        finally:
            dispatcher.shutdown()

    def test_wait_all_empty_dispatcher(self) -> None:
        dispatcher = ParallelDispatcher(max_workers=1)
        try:
            results = dispatcher.wait_all(timeout=1)
            assert results == {}
        finally:
            dispatcher.shutdown()


# ---------------------------------------------------------------------------
# ResultAggregator
# ---------------------------------------------------------------------------


class TestResultAggregator:
    def test_aggregate_all_completed(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult(node_id="n1", task_id="t1", outcome="completed"))
        agg.record("n2", SubTaskResult(node_id="n2", task_id="t2", outcome="completed"))
        result = agg.aggregate(task_id="top", strategy="dag")
        assert result.success is True
        assert len(result.sub_results) == 2

    def test_aggregate_with_failure(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult(node_id="n1", task_id="t1", outcome="completed"))
        agg.record("n2", SubTaskResult(node_id="n2", task_id="t2", outcome="failed", error="boom"))
        result = agg.aggregate(task_id="top", strategy="linear")
        assert result.success is False

    def test_empty_aggregator(self) -> None:
        agg = ResultAggregator()
        result = agg.aggregate(task_id="top", strategy=None)
        assert result.success is False  # no results => not success

    def test_mixed_outcomes(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult(node_id="n1", task_id="t1", outcome="completed"))
        agg.record("n2", SubTaskResult(node_id="n2", task_id="t2", outcome="skipped"))
        agg.record("n3", SubTaskResult(node_id="n3", task_id="t3", outcome="failed"))
        assert len(agg.get_completed()) == 1
        assert len(agg.get_failed()) == 1

    def test_success_rate(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult(node_id="n1", task_id="t1", outcome="completed"))
        agg.record("n2", SubTaskResult(node_id="n2", task_id="t2", outcome="failed"))
        assert agg.success_rate() == pytest.approx(0.5)

    def test_success_rate_empty(self) -> None:
        agg = ResultAggregator()
        assert agg.success_rate() == 0.0

    def test_success_rate_all_completed(self) -> None:
        agg = ResultAggregator()
        agg.record("n1", SubTaskResult(node_id="n1", task_id="t1", outcome="completed"))
        agg.record("n2", SubTaskResult(node_id="n2", task_id="t2", outcome="completed"))
        assert agg.success_rate() == pytest.approx(1.0)
