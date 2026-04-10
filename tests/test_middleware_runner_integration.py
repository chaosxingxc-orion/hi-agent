"""Integration test: StageExecutor calls middleware_orchestrator.run() twice (pre + post)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hi_agent.runner_stage import StageExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_kernel() -> MagicMock:
    """Return a minimal mock kernel that satisfies StageExecutor."""
    kernel = MagicMock()
    kernel.open_stage.return_value = None
    kernel.mark_stage_state.return_value = None
    return kernel


def _make_mock_route_engine(proposals: list[Any] | None = None) -> MagicMock:
    """Return a mock route engine with a fixed proposal list."""
    re = MagicMock()
    re.propose.return_value = proposals or []
    return re


def _make_mock_executor(run_id: str = "run-test") -> MagicMock:
    """Return a mock RunExecutor state container used inside execute_stage()."""
    executor = MagicMock()
    executor.run_id = run_id
    executor.current_stage = None
    executor.action_seq = 0
    executor.session = None
    executor._budget_tier_decision = MagicMock(tier="medium")
    executor.stage_summaries = {}
    executor.dag = MagicMock()
    executor.optimizer = MagicMock()
    executor._record_event.return_value = None
    executor._emit_observability.return_value = None
    executor._persist_snapshot.return_value = None
    executor._watchdog_reset.return_value = None
    executor._watchdog_record_and_check.return_value = None
    executor._check_human_gate_triggers.return_value = None
    executor._observe_skill_execution.return_value = None
    return executor


def _make_acceptance_policy() -> MagicMock:
    policy = MagicMock()
    policy.accept.return_value = (True, "ok")
    return policy


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStageExecutorCallsMiddlewareRunTwice:
    """Verify run() is called exactly twice per stage (pre_execute + post_execute)."""

    def test_stage_executor_calls_middleware_pre_and_post(self) -> None:
        """middleware_orchestrator.run() must be called exactly 2 times per stage.

        The StageExecutor calls run() with phase='pre_execute' before routing
        and run() with phase='post_execute' after all proposals are processed.
        """
        # --- Arrange ---
        mock_orchestrator = MagicMock()
        mock_orchestrator.run.return_value = MagicMock()

        stage_id = "analyze"

        kernel = _make_mock_kernel()
        route_engine = _make_mock_route_engine(proposals=[])  # no proposals → fast path
        executor = _make_mock_executor()

        stage_exec = StageExecutor(
            kernel=kernel,
            route_engine=route_engine,
            context_manager=None,
            budget_guard=None,
            optional_stages=set(),
            acceptance_policy=_make_acceptance_policy(),
            policy_versions=MagicMock(),
            knowledge_query_fn=None,
            knowledge_query_text_builder=None,
            retrieval_engine=None,
            auto_compress=None,
            cost_calculator=None,
            middleware_orchestrator=mock_orchestrator,
        )

        # --- Act ---
        with patch("hi_agent.runner_stage.detect_dead_end", return_value=False):
            stage_exec.execute_stage(stage_id, executor=executor)

        # --- Assert ---
        assert mock_orchestrator.run.call_count == 2, (
            f"Expected 2 calls to middleware_orchestrator.run() (pre + post), "
            f"got {mock_orchestrator.run.call_count}"
        )

        # Verify call arguments contain the stage_id and correct phase labels
        calls = mock_orchestrator.run.call_args_list
        call_phases = [c.args[1]["phase"] for c in calls]
        assert "pre_execute" in call_phases, "Missing pre_execute call"
        assert "post_execute" in call_phases, "Missing post_execute call"
        assert calls[0].args[0] == stage_id
        assert calls[1].args[0] == stage_id

    def test_stage_executor_without_middleware_does_not_raise(self) -> None:
        """StageExecutor with middleware_orchestrator=None must not raise."""
        kernel = _make_mock_kernel()
        route_engine = _make_mock_route_engine(proposals=[])
        executor = _make_mock_executor()

        stage_exec = StageExecutor(
            kernel=kernel,
            route_engine=route_engine,
            context_manager=None,
            budget_guard=None,
            optional_stages=set(),
            acceptance_policy=_make_acceptance_policy(),
            policy_versions=MagicMock(),
            knowledge_query_fn=None,
            knowledge_query_text_builder=None,
            retrieval_engine=None,
            auto_compress=None,
            cost_calculator=None,
            middleware_orchestrator=None,
        )

        with patch("hi_agent.runner_stage.detect_dead_end", return_value=False):
            result = stage_exec.execute_stage("plan", executor=executor)

        # Should complete without error; result is None (not a dead end)
        assert result is None

    def test_middleware_run_exception_does_not_abort_stage(self) -> None:
        """A failing middleware_orchestrator.run() must not propagate and abort the stage.

        The StageExecutor wraps both pre/post calls in try/except so a broken
        orchestrator must be swallowed gracefully.
        """
        failing_orchestrator = MagicMock()
        failing_orchestrator.run.side_effect = RuntimeError("orchestrator down")

        kernel = _make_mock_kernel()
        route_engine = _make_mock_route_engine(proposals=[])
        executor = _make_mock_executor()

        stage_exec = StageExecutor(
            kernel=kernel,
            route_engine=route_engine,
            context_manager=None,
            budget_guard=None,
            optional_stages=set(),
            acceptance_policy=_make_acceptance_policy(),
            policy_versions=MagicMock(),
            knowledge_query_fn=None,
            knowledge_query_text_builder=None,
            retrieval_engine=None,
            auto_compress=None,
            cost_calculator=None,
            middleware_orchestrator=failing_orchestrator,
        )

        # Should not raise even though orchestrator raises
        with patch("hi_agent.runner_stage.detect_dead_end", return_value=False):
            result = stage_exec.execute_stage("finalize", executor=executor)

        # Stage completed (not aborted)
        assert result is None
        # run() was still called (twice — both swallowed)
        assert failing_orchestrator.run.call_count == 2
