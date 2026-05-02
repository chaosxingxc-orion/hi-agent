"""Unit tests for run_resume replan_hook support (W25-M.4).

Tests verify that after re-anchoring to completed stages, replan_hook is consulted
before each remaining stage is replayed. Covers: None hook, skip_to valid,
skip_to invalid (dev/strict posture), and backward compatibility.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.contracts.directives import StageDirective
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


def _make_ctx(
    graph=None,
    execute_stage_fn=None,
    replan_hook=None,
    completed_stage_ids: set | None = None,
) -> StageOrchestratorContext:
    """Build a StageOrchestratorContext with optional pre-completed stages."""
    graph = graph or _make_graph({"s1": [], "s2": [], "s3": []})
    attrs: dict = {}

    # Wire completed stages via stage_summaries (outcome="completed")
    stage_summaries: dict = {}
    if completed_stage_ids:
        for sid in completed_stage_ids:
            summary = MagicMock()
            summary.outcome = "completed"
            stage_summaries[sid] = summary

    return StageOrchestratorContext(
        run_id="run-resume-test",
        contract=MagicMock(task_id="t1", policy_versions=None),
        stage_graph=graph,
        stage_summaries=stage_summaries,
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


class TestReplanHookNoneResumesNormally:
    def test_no_hook_resumes_remaining_stages_only(self) -> None:
        """run_resume with replan_hook=None skips completed stages and runs the rest."""
        executed: list[str] = []
        # s1 is already completed; s2 and s3 should run
        ctx = _make_ctx(
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=None,
            completed_stage_ids={"s1"},
        )
        result = StageOrchestrator(ctx).run_resume()

        assert result == "completed"
        assert "s1" not in executed
        assert "s2" in executed
        assert "s3" in executed


class TestSkipToValidStage:
    def test_skip_to_valid_stage_drops_intermediate_stages(self) -> None:
        """skip_to a valid remaining stage drops all stages between current and target."""
        executed: list[str] = []

        # s1 is already completed; after s2, directive fires: skip_to s4 (dropping s3)
        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s2":
                return StageDirective(action="skip_to", skip_to="s4", reason="jump")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": [], "s4": []})
        ctx = _make_ctx(
            graph=graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
            completed_stage_ids={"s1"},
        )
        result = StageOrchestrator(ctx).run_resume()

        assert result == "completed"
        assert "s1" not in executed  # was already completed; skipped in re-anchor
        assert "s2" in executed
        assert "s3" not in executed  # dropped by skip_to
        assert "s4" in executed
        assert executed.index("s4") > executed.index("s2")


class TestSkipToInvalidStageDevPosture:
    def test_invalid_skip_to_ignored_in_dev(self, monkeypatch) -> None:
        """skip_to an unknown stage in dev posture is ignored; remaining stages all run."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        executed: list[str] = []

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s2":
                return StageDirective(action="skip_to", skip_to="no_such_stage", reason="oops")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(
            graph=graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
            completed_stage_ids={"s1"},
        )
        result = StageOrchestrator(ctx).run_resume()

        assert result == "completed"
        # s2 and s3 both ran; directive was a no-op in dev posture
        assert "s2" in executed
        assert "s3" in executed


class TestSkipToInvalidStageStrictPosture:
    def test_invalid_skip_to_raises_in_strict(self, monkeypatch) -> None:
        """skip_to an unknown stage in strict posture raises StageDirectiveError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s2":
                return StageDirective(action="skip_to", skip_to="ghost_stage", reason="bad")
            return None

        graph = _make_graph({"s1": [], "s2": [], "s3": []})
        ctx = _make_ctx(
            graph=graph,
            replan_hook=_replan,
            completed_stage_ids={"s1"},
        )

        with pytest.raises(StageDirectiveError, match="skip_to"):
            StageOrchestrator(ctx).run_resume()


class TestRunResumeBackwardCompat:
    def test_run_resume_no_replan_hook_arg_succeeds(self) -> None:
        """run_resume() with ctx.replan_hook=None is backward compatible (no regression)."""
        executed: list[str] = []
        # No completed stages; all three should run
        ctx = _make_ctx(
            execute_stage_fn=lambda s: executed.append(s) or None,
        )
        result = StageOrchestrator(ctx).run_resume()

        assert result == "completed"
        assert len(executed) == 3
        assert "s1" in executed
        assert "s2" in executed
        assert "s3" in executed
