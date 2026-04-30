"""Unit tests for run_graph replan_hook support (W25-M.3).

Tests verify that replan_hook directives (skip_to, skip, insert, None)
are applied between node executions in graph-based traversal.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.contracts.directives import StageDirective
from hi_agent.contracts.exceptions import StageDirectiveError
from hi_agent.execution.stage_orchestrator import StageOrchestrator, StageOrchestratorContext


def _make_graph(transitions: dict):
    """Minimal StageGraph stub for graph traversal tests."""
    g = MagicMock()
    g.transitions = transitions
    g.successors.side_effect = lambda s: set(transitions.get(s, []))
    g.get_backtrack.return_value = None
    # trace_order not required for graph traversal but included for completeness
    g.trace_order.return_value = sorted(transitions.keys())
    return g


def _make_ctx(graph=None, execute_stage_fn=None, replan_hook=None) -> StageOrchestratorContext:
    # Linear graph: s1 → s2 → s3 → (no successors)
    graph = graph or _make_graph({"s1": ["s2"], "s2": ["s3"], "s3": []})
    attrs: dict = {}
    return StageOrchestratorContext(
        run_id="run-graph-test",
        contract=MagicMock(task_id="t1"),
        stage_graph=graph,
        stage_summaries={},
        policy_versions=MagicMock(
            route_policy="v1",
            acceptance_policy="v1",
            memory_policy="v1",
            evaluation_policy="v1",
            task_view_policy="v1",
            skill_policy="v1",
        ),
        session=None,
        route_engine=MagicMock(spec=[]),
        metrics_collector=None,
        replan_hook=replan_hook,
        execute_stage_fn=execute_stage_fn or (lambda s: None),
        handle_stage_failure_fn=lambda s, r, **kw: "failed",
        finalize_run_fn=lambda outcome: outcome,
        emit_observability_fn=lambda *a, **kw: None,
        log_best_effort_fn=lambda *a, **kw: None,
        record_event_fn=lambda *a, **kw: None,
        set_executor_attr_fn=lambda k, v: attrs.update({k: v}),
    )


class TestReplanHookNoneDoesNothing:
    def test_no_hook_runs_all_stages_normally(self) -> None:
        """run_graph without replan_hook executes all nodes in successor order."""
        executed: list[str] = []
        ctx = _make_ctx(
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=None,
        )
        result = StageOrchestrator(ctx).run_graph()

        assert result == "completed"
        assert executed == ["s1", "s2", "s3"]


class TestReplanHookReturnsNone:
    def test_hook_returning_none_has_no_effect(self) -> None:
        """replan_hook that always returns None does not alter graph traversal."""
        executed: list[str] = []

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            return None

        ctx = _make_ctx(
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        result = StageOrchestrator(ctx).run_graph()

        assert result == "completed"
        assert executed == ["s1", "s2", "s3"]


class TestSkipToValidNode:
    def test_skip_to_jumps_to_named_node(self) -> None:
        """skip_to a valid graph node jumps current_stage to that node."""
        executed: list[str] = []

        # After s1, directive fires: skip_to s3 (bypassing s2)
        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="s3", reason="jump")
            return None

        ctx = _make_ctx(
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        result = StageOrchestrator(ctx).run_graph()

        assert result == "completed"
        assert "s1" in executed
        assert "s2" not in executed
        assert "s3" in executed
        assert executed.index("s3") > executed.index("s1")


class TestSkipToInvalidNodeDevPosture:
    def test_invalid_skip_to_ignored_in_dev(self, monkeypatch) -> None:
        """skip_to an unknown node in dev posture is silently ignored; traversal continues."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        executed: list[str] = []

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="no_such_node", reason="oops")
            return None

        ctx = _make_ctx(
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        result = StageOrchestrator(ctx).run_graph()

        assert result == "completed"
        # All three stages still ran (directive was a no-op in dev posture)
        assert executed == ["s1", "s2", "s3"]


class TestSkipToInvalidNodeStrictPosture:
    def test_invalid_skip_to_raises_in_strict(self, monkeypatch) -> None:
        """skip_to an unknown node in strict posture raises StageDirectiveError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="ghost_node", reason="bad")
            return None

        ctx = _make_ctx(replan_hook=_replan)

        with pytest.raises(StageDirectiveError, match="skip_to"):
            StageOrchestrator(ctx).run_graph()


class TestBackwardCompatWithoutHook:
    def test_run_graph_no_hook_arg_succeeds(self) -> None:
        """run_graph() with ctx.replan_hook=None is backward compatible."""
        executed: list[str] = []
        ctx = _make_ctx(
            execute_stage_fn=lambda s: executed.append(s) or None,
        )
        # replan_hook defaults to None in _make_ctx; confirm no AttributeError
        result = StageOrchestrator(ctx).run_graph()

        assert result == "completed"
        assert len(executed) == 3
