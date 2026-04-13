"""Integration tests for workflow contracts driving runtime execution.

Verifies that a WorkflowSpec / ProfileSpec routes through the correct
stage_actions and stage_graph when injected via profile_id.
"""

from __future__ import annotations

import pytest

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.registry import ProfileRegistry
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.workflows.contracts import WorkflowNode, WorkflowSpec, WorkflowTransition


class TestProfileStageActionsInRouteEngine:
    def test_profile_stage_actions_drive_route_engine(self):
        """RuleRouteEngine uses profile's stage_actions, not TRACE defaults."""
        profile = ProfileSpec(
            profile_id="support",
            display_name="Support",
            stage_actions={
                "intake": "classify_intent",
                "resolve": "lookup_kb",
            },
        )
        engine = RuleRouteEngine(stage_actions=profile.stage_actions)
        proposals = engine.propose("intake", "run-001", 1)
        action_kinds = [p.action_kind for p in proposals]
        assert "classify_intent" in action_kinds

    def test_non_trace_stage_names_work(self):
        """Custom stage names (not S1-S5) route correctly."""
        engine = RuleRouteEngine(stage_actions={
            "ingest": "load_data",
            "transform": "apply_rules",
            "export": "write_output",
        })
        proposals = engine.propose("transform", "run-002", 1)
        kinds = [p.action_kind for p in proposals]
        assert "apply_rules" in kinds

    def test_no_stage_actions_falls_back_to_trace(self):
        """Without stage_actions override, TRACE defaults apply."""
        engine = RuleRouteEngine()
        # TRACE default includes S1_understand → understand
        proposals = engine.propose("S1_understand", "run-003", 1)
        assert len(proposals) >= 1


class TestWorkflowSpecToRuntimeObjects:
    def _make_wf(self):
        return WorkflowSpec(
            workflow_id="pipeline",
            display_name="Pipeline",
            nodes=[
                WorkflowNode("ingest", "load_data"),
                WorkflowNode("transform", "apply_rules"),
                WorkflowNode("export", "write_output"),
            ],
            transitions=[
                WorkflowTransition("ingest", "transform"),
                WorkflowTransition("transform", "export"),
            ],
            initial_node="ingest",
            terminal_nodes=["export"],
        )

    def test_to_stage_actions_correct(self):
        wf = self._make_wf()
        sa = wf.to_stage_actions()
        assert sa["ingest"] == "load_data"
        assert sa["transform"] == "apply_rules"
        assert sa["export"] == "write_output"

    def test_to_stage_graph_valid(self):
        wf = self._make_wf()
        graph = wf.to_stage_graph()
        assert "transform" in graph.successors("ingest")
        assert "export" in graph.successors("transform")

    def test_workflow_profile_integration(self):
        """ProfileSpec built from WorkflowSpec routes correctly end-to-end."""
        wf = self._make_wf()
        profile = ProfileSpec(
            profile_id="data_pipeline",
            display_name="Data Pipeline",
            stage_actions=wf.to_stage_actions(),
            stage_graph_factory=wf.to_stage_graph,
        )
        engine = RuleRouteEngine(stage_actions=profile.stage_actions)
        proposals = engine.propose("ingest", "run-wf-001", 1)
        assert any(p.action_kind == "load_data" for p in proposals)


class TestBuilderWiresProfileActions:
    def test_builder_uses_profile_stage_actions(self):
        """SystemBuilder._build_route_engine passes profile stage_actions."""
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        reg = builder.build_profile_registry()
        reg.register(ProfileSpec(
            profile_id="custom",
            display_name="Custom",
            stage_actions={"step_a": "do_thing_a", "step_b": "do_thing_b"},
        ))
        resolved = builder._resolve_profile("custom")
        assert resolved is not None
        # Build route engine with profile's stage_actions
        engine = builder._build_route_engine(stage_actions=resolved.stage_actions)
        proposals = engine.propose("step_a", "run-x", 1)
        kinds = [p.action_kind for p in proposals]
        assert "do_thing_a" in kinds
