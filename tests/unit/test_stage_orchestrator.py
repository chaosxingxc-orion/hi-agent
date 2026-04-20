"""Unit tests for StageOrchestrator (HI-W10-001)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.execution.stage_orchestrator import StageOrchestrator, StageOrchestratorContext
from hi_agent.gate_protocol import GatePendingError


def _make_graph(transitions: dict):
    """Simple StageGraph stub."""
    g = MagicMock()
    g.transitions = transitions
    g.trace_order.return_value = sorted(transitions.keys())
    g.successors.side_effect = lambda s: set(transitions.get(s, []))
    g.get_backtrack.return_value = None
    return g


def _make_ctx(
    graph=None,
    execute_stage_fn=None,
    handle_failure_fn=None,
    finalize_fn=None,
    **kwargs,
) -> StageOrchestratorContext:
    graph = graph or _make_graph({"s1": ["s2"], "s2": []})
    attrs = {}
    return StageOrchestratorContext(
        run_id="run-test",
        contract=MagicMock(task_id="t1", policy_versions=None),
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
        route_engine=MagicMock(spec=[]),  # no select_stage
        metrics_collector=None,
        replan_hook=None,
        execute_stage_fn=execute_stage_fn or (lambda s: None),
        handle_stage_failure_fn=handle_failure_fn or (lambda s, r, **kw: "failed"),
        finalize_run_fn=finalize_fn or (lambda outcome: outcome),
        emit_observability_fn=lambda *a, **kw: None,
        log_best_effort_fn=lambda *a, **kw: None,
        record_event_fn=lambda *a, **kw: None,
        set_executor_attr_fn=lambda k, v: attrs.update({k: v}),
    )


class TestFindStartStage:
    def test_returns_zero_indegree_node(self):
        ctx = _make_ctx(graph=_make_graph({"s1": ["s2"], "s2": []}))
        orch = StageOrchestrator(ctx)
        assert orch._find_start_stage() == "s1"

    def test_returns_none_for_empty_graph(self):
        ctx = _make_ctx(graph=_make_graph({}))
        orch = StageOrchestrator(ctx)
        assert orch._find_start_stage() is None

    def test_returns_lexically_first_root_when_multiple(self):
        ctx = _make_ctx(graph=_make_graph({"b": [], "a": []}))
        orch = StageOrchestrator(ctx)
        assert orch._find_start_stage() == "a"


class TestSelectNextStage:
    def test_picks_lexical_first_without_route_engine(self):
        ctx = _make_ctx()
        orch = StageOrchestrator(ctx)
        assert orch._select_next_stage({"c", "a", "b"}) == "a"

    def test_delegates_to_route_engine_when_available(self):
        ctx = _make_ctx()
        ctx.route_engine = MagicMock()
        ctx.route_engine.select_stage.return_value = "b"
        orch = StageOrchestrator(ctx)
        result = orch._select_next_stage({"a", "b"})
        assert result == "b"
        ctx.route_engine.select_stage.assert_called_once()

    def test_falls_back_to_lexical_on_route_engine_error(self):
        ctx = _make_ctx()
        ctx.route_engine = MagicMock()
        ctx.route_engine.select_stage.side_effect = RuntimeError("oops")
        orch = StageOrchestrator(ctx)
        assert orch._select_next_stage({"z", "a"}) == "a"


class TestRunLinear:
    def test_executes_all_stages_in_order(self):
        called = []
        ctx = _make_ctx(execute_stage_fn=lambda s: called.append(s) or None)
        result = StageOrchestrator(ctx).run_linear()
        assert called == ["s1", "s2"]
        assert result == "completed"

    def test_failed_stage_propagates_to_failed_outcome(self):
        ctx = _make_ctx(
            execute_stage_fn=lambda s: "failed" if s == "s1" else None,
            handle_failure_fn=lambda s, r, **kw: "failed",
        )
        result = StageOrchestrator(ctx).run_linear()
        assert result == "failed"

    def test_recovery_allows_continuation(self):
        ctx = _make_ctx(
            execute_stage_fn=lambda s: "failed" if s == "s1" else None,
            handle_failure_fn=lambda s, r, **kw: "reflected",
        )
        result = StageOrchestrator(ctx).run_linear()
        assert result == "completed"

    def test_gate_pending_propagates(self):
        def _ex(s):
            if s == "s1":
                raise GatePendingError(gate_id="g1")
            return None

        ctx = _make_ctx(execute_stage_fn=_ex)
        with pytest.raises(GatePendingError):
            StageOrchestrator(ctx).run_linear()

    def test_exception_sets_executor_attrs(self):
        captured = {}

        def _ex(s):
            raise ValueError("boom")

        def _set(k, v):
            captured[k] = v

        ctx = _make_ctx(execute_stage_fn=_ex)
        ctx.set_executor_attr_fn = _set
        result = StageOrchestrator(ctx).run_linear()
        assert captured.get("_last_exception_msg") == "boom"
        assert captured.get("_last_exception_type") == "ValueError"
        assert result == "failed"


class TestRunGraph:
    def test_runs_single_stage_graph(self):
        graph = _make_graph({"s1": []})
        ctx = _make_ctx(graph=graph)
        result = StageOrchestrator(ctx).run_graph()
        assert result == "completed"

    def test_follows_successors(self):
        graph = _make_graph({"s1": ["s2"], "s2": []})
        executed = []
        ctx = _make_ctx(graph=graph, execute_stage_fn=lambda s: executed.append(s) or None)
        result = StageOrchestrator(ctx).run_graph()
        assert "s1" in executed
        assert "s2" in executed
        assert result == "completed"


class TestRunResume:
    def test_skips_completed_stages(self):
        graph = _make_graph({"s1": ["s2"], "s2": []})
        executed = []
        session = MagicMock()
        session.stage_states = {"s1": "completed"}
        ctx = _make_ctx(graph=graph, execute_stage_fn=lambda s: executed.append(s) or None)
        ctx.session = session
        StageOrchestrator(ctx).run_resume()
        assert "s1" not in executed
        assert "s2" in executed

    def test_all_completed_skips_everything(self):
        graph = _make_graph({"s1": [], "s2": []})
        executed = []
        session = MagicMock()
        session.stage_states = {"s1": "completed", "s2": "completed"}
        ctx = _make_ctx(graph=graph, execute_stage_fn=lambda s: executed.append(s) or None)
        ctx.session = session
        result = StageOrchestrator(ctx).run_resume()
        assert executed == []
        assert result == "completed"
