"""Unit tests for run_linear directive handling: InsertSpec anchor + skip_to (W25-M.2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.contracts.directives import InsertSpec, StageDirective
from hi_agent.contracts.exceptions import StageDirectiveError
from hi_agent.execution.stage_orchestrator import StageOrchestrator, StageOrchestratorContext


def _make_graph(transitions: dict):
    """Simple StageGraph stub that returns sorted keys as trace_order."""
    g = MagicMock()
    g.transitions = transitions
    g.trace_order.return_value = sorted(transitions.keys())
    g.successors.side_effect = lambda s: set(transitions.get(s, []))
    g.get_backtrack.return_value = None
    return g


def _make_ctx(graph=None, execute_stage_fn=None, replan_hook=None) -> StageOrchestratorContext:
    graph = graph or _make_graph({"s1": ["s2"], "s2": ["s3"], "s3": []})
    attrs: dict = {}
    return StageOrchestratorContext(
        run_id="run-directive-test",
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


class TestInsertWithValidAnchor:
    def test_new_stage_inserted_after_anchor(self) -> None:
        """insert with a valid anchor inserts spec.new_stage immediately after anchor."""
        executed: list[str] = []

        # After s1 completes, directive fires: insert "s_extra" after "s2"
        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(
                    action="insert",
                    insert=[InsertSpec(target_stage_id="s2", new_stage="s_extra")],
                    reason="test",
                )
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(
            graph=graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        result = StageOrchestrator(ctx).run_linear()

        assert result == "completed"
        # s_extra must appear immediately after s2 in execution order
        assert "s_extra" in executed
        s2_idx = executed.index("s2")
        extra_idx = executed.index("s_extra")
        assert extra_idx == s2_idx + 1


class TestInsertMissingAnchorDevPosture:
    def test_appends_to_tail_in_dev(self, monkeypatch) -> None:
        """insert with missing anchor in dev posture appends new_stage to tail."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        executed: list[str] = []

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(
                    action="insert",
                    insert=[InsertSpec(target_stage_id="nonexistent", new_stage="s_tail")],
                    reason="test",
                )
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(
            graph=graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        result = StageOrchestrator(ctx).run_linear()

        assert result == "completed"
        assert "s_tail" in executed
        # s_tail must be last (appended to tail after s2, s3)
        assert executed.index("s_tail") == len(executed) - 1


class TestInsertMissingAnchorStrictPosture:
    def test_raises_stage_directive_error_in_strict(self, monkeypatch) -> None:
        """insert with missing anchor in strict posture raises StageDirectiveError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(
                    action="insert",
                    insert=[InsertSpec(target_stage_id="nonexistent", new_stage="s_bad")],
                    reason="test",
                )
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(graph=graph, replan_hook=_replan)

        with pytest.raises(StageDirectiveError, match="insert anchor"):
            StageOrchestrator(ctx).run_linear()


class TestSkipToValidStage:
    def test_skip_to_truncates_remaining_to_target(self) -> None:
        """skip_to a valid stage drops all stages before the target."""
        executed: list[str] = []

        # After s1, directive fires: skip_to s3 (dropping s2)
        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="s3", reason="jump")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(
            graph=graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        result = StageOrchestrator(ctx).run_linear()

        assert result == "completed"
        assert "s1" in executed
        assert "s2" not in executed
        assert "s3" in executed
        assert executed.index("s3") > executed.index("s1")


class TestSkipToInvalidStageDevPosture:
    def test_invalid_skip_to_ignored_in_dev(self, monkeypatch) -> None:
        """skip_to an unknown stage in dev posture is ignored; all remaining stages run."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        executed: list[str] = []

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="no_such_stage", reason="oops")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(
            graph=graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        result = StageOrchestrator(ctx).run_linear()

        assert result == "completed"
        # All three stages still ran (directive was a no-op in dev posture)
        assert "s1" in executed
        assert "s2" in executed
        assert "s3" in executed
