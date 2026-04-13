"""Platform E2E composition tests.

Verifies that:
1. No profile → TRACE sample fallback executes normally
2. Custom profile with non-TRACE stage names routes correctly
3. Custom evaluator is used when profile provides one
4. Removing a profile leaves platform runnable
"""

from __future__ import annotations

import pytest

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.registry import ProfileRegistry
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.trajectory.stage_graph import StageGraph


class TestTraceFallback:
    def test_no_profile_uses_trace_defaults(self):
        """Without a profile, TRACE S1-S5 defaults are used."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.contracts.task import TaskContract

        builder = SystemBuilder()
        resolved = builder._resolve_profile(None)
        assert resolved is None

        # Route engine with no stage_actions uses TRACE defaults
        engine = builder._build_route_engine(stage_actions=None)
        proposals = engine.propose("S1_understand", "run-trace", 1)
        assert len(proposals) >= 1

    def test_trace_stage_graph_is_default(self):
        """RunExecutor defaults to TRACE stage graph when no profile given."""
        from hi_agent.trajectory.stage_graph import default_trace_stage_graph
        graph = default_trace_stage_graph()
        assert graph is not None
        assert "S1_understand" in graph.transitions


class TestCustomProfileExecution:
    def test_custom_3_stage_profile_routes_correctly(self):
        """Non-TRACE custom stage names route to correct capabilities."""
        profile = ProfileSpec(
            profile_id="pipeline",
            display_name="Pipeline",
            stage_actions={
                "ingest": "load_data",
                "process": "run_algorithm",
                "output": "write_results",
            },
        )
        engine = RuleRouteEngine(stage_actions=profile.stage_actions)

        for stage, expected in [
            ("ingest", "load_data"),
            ("process", "run_algorithm"),
            ("output", "write_results"),
        ]:
            proposals = engine.propose(stage, "run-custom", 1)
            kinds = [p.action_kind for p in proposals]
            assert expected in kinds, f"Expected {expected!r} for stage {stage!r}"

    def test_custom_profile_stage_graph_has_correct_topology(self):
        """WorkflowSpec-derived stage graph has correct edge topology."""
        from hi_agent.workflows.contracts import WorkflowNode, WorkflowSpec, WorkflowTransition

        wf = WorkflowSpec(
            workflow_id="custom",
            display_name="Custom",
            nodes=[
                WorkflowNode("a", "cap_a"),
                WorkflowNode("b", "cap_b"),
                WorkflowNode("c", "cap_c"),
            ],
            transitions=[
                WorkflowTransition("a", "b"),
                WorkflowTransition("b", "c"),
            ],
            initial_node="a",
            terminal_nodes=["c"],
        )
        graph = wf.to_stage_graph()
        assert "b" in graph.successors("a")
        assert "c" in graph.successors("b")


class TestCustomEvaluatorComposition:
    def test_custom_evaluator_invoked_via_middleware(self):
        """Profile-provided evaluator is called by EvaluationMiddleware."""
        from hi_agent.evaluation.contracts import EvaluationResult
        from hi_agent.middleware.evaluation import EvaluationMiddleware
        from hi_agent.middleware.protocol import MiddlewareMessage

        invoked: list[bool] = []

        class TrackingEval:
            def evaluate(self, context, output):
                invoked.append(True)
                return EvaluationResult(score=0.9, passed=True)

        mw = EvaluationMiddleware(quality_threshold=0.5, evaluator=TrackingEval())
        msg = MiddlewareMessage(
            source="execution",
            target="evaluation",
            msg_type="execution_result",
            payload={
                "results": [
                    {"node_id": "a", "output": {"output": "x"}, "success": True, "evidence": []},
                ],
                "perception_text": "test",
            },
        )
        result = mw.process(msg)
        assert len(invoked) == 1
        assert result.payload["evaluations"][0]["scoring_mode"] == "evaluator"


class TestProfileIsolation:
    def test_removing_profile_leaves_platform_runnable(self):
        """After removing a profile, platform falls back to TRACE defaults."""
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        reg = builder.build_profile_registry()
        reg.register(ProfileSpec(profile_id="temp", display_name="Temp"))
        assert reg.has("temp")

        reg.remove("temp")
        assert not reg.has("temp")

        # Builder falls back gracefully
        resolved = builder._resolve_profile("temp")
        assert resolved is None

    def test_separate_runs_use_separate_profiles(self):
        """Two runs with different profile_ids get different routing."""
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

        reg = ProfileRegistry()
        reg.register(ProfileSpec(
            profile_id="prof_a",
            display_name="A",
            stage_actions={"step": "do_a"},
        ))
        reg.register(ProfileSpec(
            profile_id="prof_b",
            display_name="B",
            stage_actions={"step": "do_b"},
        ))

        resolver = ProfileRuntimeResolver(reg)
        a = resolver.resolve("prof_a")
        b = resolver.resolve("prof_b")

        assert a.stage_actions["step"] == "do_a"
        assert b.stage_actions["step"] == "do_b"
