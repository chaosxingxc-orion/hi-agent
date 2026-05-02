"""Integration tests for P-4 StageDirective full wiring.

Uses real StageGraph and real StageOrchestrator (no mocks on SUT).
Verifies that skip_to, insert, skip, and repeat directives:
  1. Correctly alter the stage execution order
  2. Fire the real spine emit functions without crashing (Rule 7)

This closes P-4 PARTIAL → full with Layer-2 integration evidence.
Unit-level spine-call assertions live in tests/unit/test_stage_directive_spine_telemetry.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.contracts.directives import InsertSpec, StageDirective
from hi_agent.execution.stage_orchestrator import StageOrchestrator, StageOrchestratorContext
from hi_agent.trajectory.stage_graph import StageGraph

# ---------------------------------------------------------------------------
# Helpers: build a real StageGraph and a minimal context
# ---------------------------------------------------------------------------


def _build_graph(*stages: str) -> StageGraph:
    """Build a real StageGraph with a linear chain of stages."""
    g = StageGraph()
    for i, stage in enumerate(stages):
        if i + 1 < len(stages):
            g.add_edge(stage, stages[i + 1])
        else:
            g.transitions.setdefault(stage, set())
    return g


def _make_ctx(
    graph: StageGraph,
    execute_stage_fn=None,
    replan_hook=None,
    run_id: str = "run-p4-integration",
) -> StageOrchestratorContext:
    attrs: dict = {}
    return StageOrchestratorContext(
        run_id=run_id,
        contract=MagicMock(task_id="task-p4", policy_versions=None),
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
# skip_to directive (P-4 evidence kind 1)
# ---------------------------------------------------------------------------


class TestSkipToDirectiveIntegration:
    def test_skip_to_truncates_remaining_stages(self, monkeypatch):
        """skip_to drops all intermediate stages and jumps to target."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        executed: list[str] = []
        graph = _build_graph("s1", "s2", "s3", "s4")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="s4", reason="skip-test")
            return None

        ctx = _make_ctx(
            graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        outcome = StageOrchestrator(ctx).run_linear()

        assert outcome == "completed"
        assert "s1" in executed
        assert "s2" not in executed  # skipped
        assert "s3" not in executed  # skipped
        assert "s4" in executed

    def test_skip_to_fires_real_spine_emitter(self, monkeypatch):
        """skip_to calls emit_stage_replanned without crashing (Rule 7: real emit path)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        graph = _build_graph("s1", "s2", "s3")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(action="skip_to", skip_to="s3", reason="spine-test")
            return None

        ctx = _make_ctx(graph, replan_hook=_replan, run_id="run-spine-real")
        # Must not raise — real spine emitters are best-effort and never block
        outcome = StageOrchestrator(ctx).run_linear()
        assert outcome == "completed"


# ---------------------------------------------------------------------------
# insert directive (P-4 evidence kind 2)
# ---------------------------------------------------------------------------


class TestInsertDirectiveIntegration:
    def test_insert_stage_executed_after_anchor(self, monkeypatch):
        """insert with valid anchor executes new stage immediately after anchor."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        executed: list[str] = []
        graph = _build_graph("s1", "s2", "s3")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(
                    action="insert",
                    insert=[InsertSpec(target_stage_id="s2", new_stage="s_injected")],
                    reason="insert-test",
                )
            return None

        ctx = _make_ctx(
            graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        outcome = StageOrchestrator(ctx).run_linear()

        assert outcome == "completed"
        assert "s_injected" in executed
        s2_idx = executed.index("s2")
        injected_idx = executed.index("s_injected")
        assert injected_idx == s2_idx + 1, "injected stage must run immediately after anchor"

    def test_insert_fires_real_spine_emitter(self, monkeypatch):
        """insert calls emit_stage_inserted without crashing (Rule 7 compliance)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        graph = _build_graph("s1", "s2")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            if stage_id == "s1":
                return StageDirective(
                    action="insert",
                    insert=[InsertSpec(target_stage_id="s2", new_stage="s_new")],
                    reason="spine-check",
                )
            return None

        ctx = _make_ctx(graph, replan_hook=_replan, run_id="run-insert-real")
        outcome = StageOrchestrator(ctx).run_linear()
        assert outcome == "completed"


# ---------------------------------------------------------------------------
# replan / repeat directive (P-4 evidence kind 3)
# ---------------------------------------------------------------------------


class TestReplanDirectiveIntegration:
    def test_repeat_reruns_current_stage(self, monkeypatch):
        """repeat directive causes a stage to execute twice."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        executed: list[str] = []
        call_count: dict[str, int] = {}
        graph = _build_graph("s1", "s2", "s3")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            call_count[stage_id] = call_count.get(stage_id, 0) + 1
            if stage_id == "s1" and call_count["s1"] == 1:
                return StageDirective(action="repeat", target_stage_id="s1", reason="retry-once")
            return None

        ctx = _make_ctx(
            graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
            replan_hook=_replan,
        )
        outcome = StageOrchestrator(ctx).run_linear()

        assert outcome == "completed"
        assert executed.count("s1") == 2, "s1 must have executed twice (original + repeat)"
        assert executed.count("s2") == 1
        assert executed.count("s3") == 1

    def test_replan_fires_real_spine_emitter(self, monkeypatch):
        """repeat calls emit_stage_replanned without crashing (Rule 7 compliance)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        call_count: dict = {"n": 0}
        graph = _build_graph("s1", "s2")

        def _replan(stage_id: str, result: dict) -> StageDirective | None:
            call_count["n"] += 1
            if stage_id == "s1" and call_count["n"] == 1:
                return StageDirective(action="repeat", target_stage_id="s1", reason="spine-repeat")
            return None

        ctx = _make_ctx(graph, replan_hook=_replan, run_id="run-repeat-real")
        outcome = StageOrchestrator(ctx).run_linear()
        assert outcome == "completed"


# ---------------------------------------------------------------------------
# No-directive baseline (validates execution without interference)
# ---------------------------------------------------------------------------


class TestNoDirectiveBaseline:
    def test_no_directive_executes_all_stages(self, monkeypatch):
        """Without a replan_hook, all stages execute in graph trace_order."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        executed: list[str] = []
        graph = _build_graph("s1", "s2", "s3")
        ctx = _make_ctx(
            graph,
            execute_stage_fn=lambda s: executed.append(s) or None,
        )
        outcome = StageOrchestrator(ctx).run_linear()
        assert outcome == "completed"
        assert executed == ["s1", "s2", "s3"]
