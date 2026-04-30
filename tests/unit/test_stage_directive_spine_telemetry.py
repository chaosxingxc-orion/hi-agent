"""Tests that directive handlers emit the correct spine events (W25-M.5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hi_agent.contracts.directives import InsertSpec, StageDirective
from hi_agent.execution.stage_orchestrator import StageOrchestrator, StageOrchestratorContext

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_stage_directive_run_linear.py pattern)
# ---------------------------------------------------------------------------


def _make_graph(transitions: dict):
    """Minimal StageGraph stub that exposes trace_order + successors."""
    g = MagicMock()
    g.transitions = transitions
    g.trace_order.return_value = sorted(transitions.keys())
    g.successors.side_effect = lambda s: set(transitions.get(s, []))
    g.get_backtrack.return_value = None
    return g


def _make_ctx(graph=None, execute_stage_fn=None, replan_hook=None) -> StageOrchestratorContext:
    """Build a minimal StageOrchestratorContext for directive telemetry tests."""
    graph = graph or _make_graph({"s1": ["s2"], "s2": ["s3"], "s3": []})
    attrs: dict = {}
    return StageOrchestratorContext(
        run_id="run-spine-test",
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSkipEmitsStageSkipped:
    def test_skip_emits_stage_skipped(self, monkeypatch) -> None:
        """A skip directive calls emit_stage_skipped with correct run_id and stage ids."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip", target_stage_id="s2", reason="test-skip")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(graph=graph, replan_hook=_replan)

        with patch(
            "hi_agent.execution.stage_orchestrator.emit_stage_skipped"
        ) as mock_emit:
            StageOrchestrator(ctx).run_linear()

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        # positional args: run_id, stage_id, target_stage_id
        args = call_kwargs.args
        assert args[0] == "run-spine-test"
        assert args[1] == "s1"
        assert args[2] == "s2"
        assert call_kwargs.kwargs.get("reason") == "test-skip"


class TestInsertEmitsStageInserted:
    def test_insert_emits_stage_inserted(self, monkeypatch) -> None:
        """An insert directive calls emit_stage_inserted for each inserted spec."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(
                    action="insert",
                    insert=[InsertSpec(target_stage_id="s2", new_stage="s_extra")],
                    reason="test-insert",
                )
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(graph=graph, replan_hook=_replan)

        with patch(
            "hi_agent.execution.stage_orchestrator.emit_stage_inserted"
        ) as mock_emit:
            StageOrchestrator(ctx).run_linear()

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        args = call_kwargs.args
        assert args[0] == "run-spine-test"
        assert args[1] == "s2"       # anchor_stage_id
        assert args[2] == "s_extra"  # new_stage_id
        assert call_kwargs.kwargs.get("reason") == "test-insert"


class TestSkipToEmitsStageReplanned:
    def test_skip_to_emits_stage_replanned(self, monkeypatch) -> None:
        """A skip_to directive calls emit_stage_replanned with action='skip_to'."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="s3", reason="test-skipto")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(graph=graph, replan_hook=_replan)

        with patch(
            "hi_agent.execution.stage_orchestrator.emit_stage_replanned"
        ) as mock_emit:
            StageOrchestrator(ctx).run_linear()

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        args = call_kwargs.args
        assert args[0] == "run-spine-test"
        assert args[1] == "skip_to"  # action
        assert args[2] == "s1"       # from_stage
        assert args[3] == "s3"       # to_stage
        assert call_kwargs.kwargs.get("reason") == "test-skipto"


class TestRepeatEmitsStageReplanned:
    def test_repeat_emits_stage_replanned(self, monkeypatch) -> None:
        """A repeat directive calls emit_stage_replanned with action='repeat'."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        call_count = {"n": 0}

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            # Repeat s1 once, then stop to avoid infinite loop
            if stage_id == "s1" and call_count["n"] == 0:
                call_count["n"] += 1
                # repeat requires target_stage_id per contract validator
                return StageDirective(action="repeat", target_stage_id="s1", reason="test-repeat")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(graph=graph, replan_hook=_replan)

        with patch(
            "hi_agent.execution.stage_orchestrator.emit_stage_replanned"
        ) as mock_emit:
            StageOrchestrator(ctx).run_linear()

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        args = call_kwargs.args
        assert args[0] == "run-spine-test"
        assert args[1] == "repeat"   # action
        assert args[2] == "s1"       # from_stage (same as to_stage for repeat)
        assert args[3] == "s1"       # to_stage
        assert call_kwargs.kwargs.get("reason") == "test-repeat"


class TestEmitFailureNonFatal:
    def test_emit_failure_is_non_fatal(self, monkeypatch) -> None:
        """If an emit function raises, the directive handling continues without error."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        executed: list[str] = []

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="s3", reason="boom")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(
            graph=graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )

        with patch(
            "hi_agent.execution.stage_orchestrator.emit_stage_replanned",
            side_effect=RuntimeError("emit exploded"),
        ):
            result = StageOrchestrator(ctx).run_linear()

        # Directive still ran (s2 skipped), run completed normally
        assert result == "completed"
        assert "s1" in executed
        assert "s2" not in executed
        assert "s3" in executed
