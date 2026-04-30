"""Unit test: StageExecutor calls middleware_orchestrator.run() twice (pre + post).

This test file is honest about its discipline: it mocks the subsystem under test
(StageExecutor's collaborators -- kernel, route engine, executor context, acceptance
policy, middleware orchestrator) with MagicMock trees in order to verify the glue
logic of `execute_stage()` -- specifically, that `middleware_orchestrator.run()` is
invoked exactly twice per stage with the correct phase labels, and that exceptions
in the orchestrator are swallowed without aborting the stage.

Because real components are not wired together here (no real kernel, no real route
engine, no real executor), this is a *unit* test of glue logic, not an integration
test. It was previously mislabeled under `tests/integration/` -- a Rule 4 violation
that this rename closes.

A true integration test of StageExecutor with real collaborators is a follow-up
item for a later wave (see Wave 23 Track G note).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from hi_agent.runner_stage import StageExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_kernel() -> MagicMock:
    """Return a minimal mock kernel dependency that satisfies StageExecutor."""
    mock_kernel = MagicMock()
    mock_kernel.open_stage.return_value = None
    mock_kernel.mark_stage_state.return_value = None
    return mock_kernel


def _make_mock_route_engine(proposals: list[Any] | None = None) -> MagicMock:
    """Return a mock route engine dependency with a fixed proposal list."""
    mock_re = MagicMock()
    mock_re.propose.return_value = proposals or []
    return mock_re


def _make_mock_executor(run_id: str = "run-test") -> MagicMock:
    """Return a mock RunExecutor state container used inside execute_stage().

    This is a mock of the executor *context* passed as a parameter to
    StageExecutor.execute_stage() — not a mock of the StageExecutor (SUT).
    """
    mock_executor = MagicMock()
    mock_executor.run_id = run_id
    mock_executor.current_stage = None
    mock_executor.action_seq = 0
    mock_executor.session = None
    mock_executor._budget_tier_decision = MagicMock(tier="medium")
    mock_executor.stage_summaries = {}
    mock_executor.dag = MagicMock()
    mock_executor.optimizer = MagicMock()
    mock_executor._record_event.return_value = None
    mock_executor._emit_observability.return_value = None
    mock_executor._persist_snapshot.return_value = None
    mock_executor._watchdog_reset.return_value = None
    mock_executor._watchdog_record_and_check.return_value = None
    mock_executor._check_human_gate_triggers.return_value = None
    mock_executor._observe_skill_execution.return_value = None
    return mock_executor


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

        mock_kernel = _make_mock_kernel()
        mock_route_engine = _make_mock_route_engine(proposals=[])  # no proposals → fast path
        mock_executor = _make_mock_executor()

        stage_exec = StageExecutor(
            kernel=mock_kernel,
            route_engine=mock_route_engine,
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
            stage_exec.execute_stage(stage_id, executor=mock_executor)

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
        mock_kernel = _make_mock_kernel()
        mock_route_engine = _make_mock_route_engine(proposals=[])
        mock_executor = _make_mock_executor()

        stage_exec = StageExecutor(
            kernel=mock_kernel,
            route_engine=mock_route_engine,
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
            result = stage_exec.execute_stage("plan", executor=mock_executor)

        # Should complete without error; result is None (not a dead end)
        assert result is None

    def test_middleware_run_exception_does_not_abort_stage(self) -> None:
        """A failing middleware_orchestrator.run() must not propagate and abort the stage.

        The StageExecutor wraps both pre/post calls in try/except so a broken
        orchestrator must be swallowed gracefully.
        """
        failing_orchestrator = MagicMock()
        failing_orchestrator.run.side_effect = RuntimeError("orchestrator down")

        mock_kernel = _make_mock_kernel()
        mock_route_engine = _make_mock_route_engine(proposals=[])
        mock_executor = _make_mock_executor()

        stage_exec = StageExecutor(
            kernel=mock_kernel,
            route_engine=mock_route_engine,
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
            result = stage_exec.execute_stage("finalize", executor=mock_executor)

        # Stage completed (not aborted)
        assert result is None
        # run() was still called (twice — both swallowed)
        assert failing_orchestrator.run.call_count == 2
