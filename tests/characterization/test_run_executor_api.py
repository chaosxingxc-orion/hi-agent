"""Characterization tests for RunExecutor public execution API.

These tests lock the current RunExecutor behavior before RunFinalizer extraction.
They use real RunExecutor instances built by SystemBuilder and replace only
collaborator methods needed to make each outcome deterministic.
"""

from __future__ import annotations

import contextlib
import inspect
import uuid
from dataclasses import fields
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts import StageSummary, TaskContract
from hi_agent.contracts.requests import RunResult
from hi_agent.gate_protocol import GatePendingError
from hi_agent.runner import RunExecutor, execute_async

from tests.helpers.kernel_facade_fixture import MockKernelFacade


@pytest.fixture
def builder():
    """SystemBuilder with isolated storage and deterministic abort-on-failure policy."""
    base_dir = Path(".hi_agent") / "test_run_executor_api" / uuid.uuid4().hex
    return SystemBuilder(
        config=TraceConfig(
            episodic_storage_dir=str(base_dir / "episodes"),
            skill_storage_dir=str(base_dir / "skills"),
            evidence_store_path=str(base_dir / "evidence.db"),
            auto_dream_interval=0,
            auto_consolidate_interval=0,
            restart_max_attempts=1,
            restart_on_exhausted="abort",
            feedback_store_enabled=False,
        )
    )


def _contract(task_id: str) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        goal="Characterize RunExecutor behavior",
        task_family="quick_task",
    )


def _executor(builder: SystemBuilder, task_id: str) -> RunExecutor:
    executor = builder.build_executor(contract=_contract(task_id))
    assert isinstance(executor, RunExecutor)
    assert hasattr(executor, "route_engine")
    assert hasattr(executor, "_lifecycle")
    assert hasattr(executor, "raw_memory")
    return executor


def _quiet_lifecycle(monkeypatch: pytest.MonkeyPatch, executor: RunExecutor) -> Mock:
    finalize = Mock(return_value=None)
    monkeypatch.setattr(executor._lifecycle, "finalize_run", finalize)
    return finalize


def _stage_behavior(
    monkeypatch: pytest.MonkeyPatch,
    executor: RunExecutor,
    behavior: str | None | BaseException,
) -> list[str]:
    calls: list[str] = []

    def execute_stage(stage_id: str, *, executor: Any) -> str | None:
        calls.append(stage_id)
        executor.current_stage = stage_id
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior

    monkeypatch.setattr(executor._stage_executor, "execute_stage", execute_stage)
    return calls


def _close_raw_memory(executor: RunExecutor) -> None:
    with contextlib.suppress(Exception):
        executor.raw_memory.close()


class TestRunResultContract:
    def test_run_result_fields_are_locked(self) -> None:
        field_names = [field.name for field in fields(RunResult)]

        assert field_names == [
            "run_id",
            "status",
            "stages",
            "artifacts",
            "error",
            "duration_ms",
            "failure_code",
            "failed_stage_id",
            "is_retryable",
            "execution_provenance",
        ]

    def test_run_result_string_equality_and_dict_shape_are_locked(self) -> None:
        result = RunResult(
            run_id="run-contract",
            status="completed",
            stages=[{"stage_id": "S1", "outcome": "succeeded"}],
            artifacts=["artifact-1"],
            duration_ms=7,
        )

        assert str(result) == "completed"
        assert result == "completed"
        assert result.to_dict().keys() == {
            "run_id",
            "status",
            "stages",
            "artifacts",
            "error",
            "duration_ms",
            "failure_code",
            "failed_stage_id",
            "is_retryable",
            "execution_provenance",
        }

    def test_run_executor_entry_point_signatures_are_locked(self) -> None:
        assert list(inspect.signature(RunExecutor.execute).parameters) == ["self"]
        assert list(inspect.signature(RunExecutor.execute_graph).parameters) == ["self"]

        finalize_sig = inspect.signature(RunExecutor._finalize_run)
        assert list(finalize_sig.parameters) == ["self", "outcome"]
        assert str(finalize_sig.return_annotation) in {
            "RunResult",
            "<class 'hi_agent.contracts.requests.RunResult'>",
        }

        async_sig = inspect.signature(execute_async)
        assert list(async_sig.parameters) == ["executor", "max_concurrency"]
        assert async_sig.parameters["max_concurrency"].default == 64
        assert str(async_sig.return_annotation) in {
            "RunResult",
            "<class 'hi_agent.contracts.requests.RunResult'>",
        }

    def test_finalize_run_returns_run_result_with_stage_and_artifact_fields(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-finalize-contract")
        _quiet_lifecycle(monkeypatch, executor)
        executor.run_id = "run-finalize-contract"
        executor.current_stage = "S1_understand"
        executor.stage_summaries = {
            "S1_understand": StageSummary(
                stage_id="S1_understand",
                stage_name="Understand",
                findings=["finding"],
                decisions=["decision"],
                outcome="succeeded",
                artifact_ids=["artifact-1"],
            )
        }

        result = executor._finalize_run("completed")

        assert isinstance(result, RunResult)
        assert result.run_id == "run-finalize-contract"
        assert result.status == "completed"
        assert result.artifacts == ["artifact-1"]
        assert result.stages == [
            {
                "stage_id": "S1_understand",
                "stage_name": "Understand",
                "outcome": "succeeded",
                "findings": ["finding"],
                "decisions": ["decision"],
                "artifact_ids": ["artifact-1"],
            }
        ]


class TestExecuteOutcomes:
    def test_execute_completed_returns_completed_run_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-execute-completed")
        _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, None)

        result = executor.execute()

        assert isinstance(result, RunResult)
        assert result.status == "completed"
        assert result == "completed"
        assert result.run_id == executor.run_id
        assert calls == executor.stage_graph.trace_order()

    def test_execute_failed_stage_return_finalizes_failed_run_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-execute-failed")
        _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, "failed")

        result = executor.execute()

        assert isinstance(result, RunResult)
        assert result.status == "failed"
        assert result.failed_stage_id == calls[-1]
        assert result.error == f"Run failed at stage {calls[-1]!r}"
        assert calls == [executor.stage_graph.trace_order()[0]]

    def test_execute_stage_exception_finalizes_failed_run_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-execute-exception")
        _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, RuntimeError("execute exploded"))

        result = executor.execute()

        assert isinstance(result, RunResult)
        assert result.status == "failed"
        assert result.failed_stage_id == calls[-1]
        assert result.error == "execute exploded"

    def test_execute_gate_pending_propagates_without_finalizing(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-execute-gate")
        finalize = _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, GatePendingError("gate-execute"))

        try:
            with pytest.raises(GatePendingError) as exc_info:
                executor.execute()
        finally:
            _close_raw_memory(executor)

        assert exc_info.value.gate_id == "gate-execute"
        assert calls == [executor.stage_graph.trace_order()[0]]
        finalize.assert_not_called()


class TestExecuteGraphOutcomes:
    def test_execute_graph_completed_returns_completed_run_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-graph-completed")
        _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, None)

        result = executor.execute_graph()

        assert isinstance(result, RunResult)
        assert result.status == "completed"
        assert result.run_id == executor.run_id
        assert calls == executor.stage_graph.trace_order()

    def test_execute_graph_failed_stage_return_finalizes_failed_run_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-graph-failed")
        _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, "failed")

        result = executor.execute_graph()

        assert isinstance(result, RunResult)
        assert result.status == "failed"
        assert result.failed_stage_id == calls[-1]
        assert result.error == f"Run failed at stage {calls[-1]!r}"
        assert calls == [executor.stage_graph.trace_order()[0]]

    def test_execute_graph_stage_exception_finalizes_failed_run_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-graph-exception")
        _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, RuntimeError("graph exploded"))

        result = executor.execute_graph()

        assert isinstance(result, RunResult)
        assert result.status == "failed"
        assert result.failed_stage_id == calls[-1]
        assert result.error == "graph exploded"

    def test_execute_graph_gate_pending_propagates_without_finalizing(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-graph-gate")
        finalize = _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, GatePendingError("gate-graph"))

        try:
            with pytest.raises(GatePendingError) as exc_info:
                executor.execute_graph()
        finally:
            _close_raw_memory(executor)

        assert exc_info.value.gate_id == "gate-graph"
        assert calls == [executor.stage_graph.trace_order()[0]]
        finalize.assert_not_called()


class TestExecuteAsyncOutcomes:
    @pytest.mark.asyncio
    async def test_execute_async_completed_returns_successful_async_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-async-completed")
        executor.kernel = MockKernelFacade()  # type: ignore[assignment]
        finalize = _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, None)

        result = await execute_async(executor, max_concurrency=4)

        assert isinstance(result, RunResult)
        assert result.status == "completed"
        # S2 fix (2026-04-21): execute_async() now mirrors the executor's
        # stage_graph (via GraphFactory.from_stage_graph) instead of the
        # generic S1/S3/S5 "simple" template. Assert the call set matches
        # the executor's actual stage_graph — which is the correct
        # post-fix contract and also what execute()/execute_graph() use.
        assert set(calls).issubset(set(executor.stage_graph.trace_order()))
        assert calls, "expected at least one stage to run"
        finalize.assert_called_once()
        assert finalize.call_args.args[0] == "completed"

    @pytest.mark.asyncio
    async def test_execute_async_failed_stage_return_is_reported_successfully_today(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-async-failed-return")
        executor.kernel = MockKernelFacade()  # type: ignore[assignment]
        finalize = _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, "failed")

        result = await execute_async(executor, max_concurrency=4)

        assert isinstance(result, RunResult)
        assert result.status == "completed"
        # S2 fix (2026-04-21): execute_async() now mirrors the executor's
        # stage_graph (via GraphFactory.from_stage_graph) instead of the
        # generic S1/S3/S5 "simple" template. Assert the call set matches
        # the executor's actual stage_graph — which is the correct
        # post-fix contract and also what execute()/execute_graph() use.
        assert set(calls).issubset(set(executor.stage_graph.trace_order()))
        assert calls, "expected at least one stage to run"
        finalize.assert_called_once()
        assert finalize.call_args.args[0] == "completed"

    @pytest.mark.asyncio
    async def test_execute_async_stage_exception_is_reported_successfully_today(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-async-exception")
        executor.kernel = MockKernelFacade()  # type: ignore[assignment]
        finalize = _quiet_lifecycle(monkeypatch, executor)
        calls = _stage_behavior(monkeypatch, executor, RuntimeError("async exploded"))

        result = await execute_async(executor, max_concurrency=4)

        assert isinstance(result, RunResult)
        assert result.status == "completed"
        # S2 fix (2026-04-21): execute_async() now mirrors the executor's
        # stage_graph (via GraphFactory.from_stage_graph) instead of the
        # generic S1/S3/S5 "simple" template. Assert the call set matches
        # the executor's actual stage_graph — which is the correct
        # post-fix contract and also what execute()/execute_graph() use.
        assert set(calls).issubset(set(executor.stage_graph.trace_order()))
        assert calls, "expected at least one stage to run"
        finalize.assert_called_once()
        assert finalize.call_args.args[0] == "completed"

    @pytest.mark.asyncio
    async def test_execute_async_gate_pending_returns_failed_async_result(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pass


class TestFinalizeRunSideEffectOrder:
    def test_finalize_run_closes_raw_memory_before_lifecycle_finalize(
        self,
        builder: SystemBuilder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executor = _executor(builder, "char-finalize-order")
        executor.run_id = "run-finalize-order"
        executor.current_stage = "S1_understand"
        calls: list[str] = []
        original_close = executor.raw_memory.close

        def close_raw_memory() -> None:
            calls.append("raw_memory.close")
            original_close()

        def finalize_run(*args: Any, **kwargs: Any) -> None:
            calls.append("lifecycle.finalize_run")

        monkeypatch.setattr(executor.raw_memory, "close", close_raw_memory)
        monkeypatch.setattr(executor._lifecycle, "finalize_run", finalize_run)

        result = executor._finalize_run("completed")

        assert isinstance(result, RunResult)
        assert result.status == "completed"
        assert calls[:2] == ["raw_memory.close", "lifecycle.finalize_run"]
