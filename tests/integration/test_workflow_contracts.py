"""Tests for hi_agent.workflows contracts."""

from __future__ import annotations

from hi_agent.workflows.contracts import (
    FallbackPolicy,
    WorkflowNode,
    WorkflowSpec,
    WorkflowTransition,
)

# ---------------------------------------------------------------------------
# WorkflowNode
# ---------------------------------------------------------------------------


class TestWorkflowNode:
    def test_defaults(self):
        n = WorkflowNode(node_id="s1", capability_binding="search")
        assert n.description == ""
        assert n.optional is False
        assert n.metadata == {}

    def test_custom_fields(self):
        n = WorkflowNode(
            node_id="ingest",
            capability_binding="load_data",
            description="Load source data",
            optional=True,
            metadata={"max_rows": 1000},
        )
        assert n.optional is True
        assert n.metadata["max_rows"] == 1000


# ---------------------------------------------------------------------------
# WorkflowTransition
# ---------------------------------------------------------------------------


class TestWorkflowTransition:
    def test_defaults(self):
        t = WorkflowTransition(source="s1", target="s2")
        assert t.condition == "always"
        assert t.priority == 0

    def test_custom_condition(self):
        t = WorkflowTransition(source="s1", target="s2", condition="on_success", priority=1)
        assert t.condition == "on_success"
        assert t.priority == 1


# ---------------------------------------------------------------------------
# FallbackPolicy
# ---------------------------------------------------------------------------


class TestFallbackPolicy:
    def test_values(self):
        assert FallbackPolicy.FAIL.value == "fail"
        assert FallbackPolicy.SKIP.value == "skip"
        assert FallbackPolicy.DEGRADE.value == "degrade"


# ---------------------------------------------------------------------------
# WorkflowSpec
# ---------------------------------------------------------------------------


def _make_support_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="support",
        display_name="Support Workflow",
        nodes=[
            WorkflowNode("intake", "classify_intent"),
            WorkflowNode("resolve", "lookup_kb"),
            WorkflowNode("respond", "generate_reply"),
        ],
        transitions=[
            WorkflowTransition("intake", "resolve"),
            WorkflowTransition("resolve", "respond"),
        ],
        initial_node="intake",
        terminal_nodes=["respond"],
    )


class TestWorkflowSpec:
    def test_creation(self):
        wf = _make_support_workflow()
        assert wf.workflow_id == "support"
        assert len(wf.nodes) == 3
        assert len(wf.transitions) == 2

    def test_get_node(self):
        wf = _make_support_workflow()
        n = wf.get_node("resolve")
        assert n is not None
        assert n.capability_binding == "lookup_kb"

    def test_get_node_missing(self):
        wf = _make_support_workflow()
        assert wf.get_node("nonexistent") is None

    def test_to_stage_actions(self):
        wf = _make_support_workflow()
        sa = wf.to_stage_actions()
        assert sa == {
            "intake": "classify_intent",
            "resolve": "lookup_kb",
            "respond": "generate_reply",
        }

    def test_to_stage_graph_edges(self):
        wf = _make_support_workflow()
        graph = wf.to_stage_graph()
        # intake -> resolve
        assert "resolve" in graph.successors("intake")
        # resolve -> respond
        assert "respond" in graph.successors("resolve")

    def test_to_stage_graph_terminal_node_present(self):
        wf = _make_support_workflow()
        graph = wf.to_stage_graph()
        # Terminal node must be in the graph
        assert "respond" in graph.transitions

    def test_validate_valid_workflow(self):
        wf = _make_support_workflow()
        errors = wf.validate()
        assert errors == []

    def test_validate_missing_initial_node(self):
        wf = WorkflowSpec(
            workflow_id="broken",
            display_name="Broken",
            nodes=[WorkflowNode("s1", "cap_a")],
            transitions=[],
        )
        errors = wf.validate()
        assert any("initial_node" in e for e in errors)

    def test_validate_invalid_initial_node(self):
        wf = WorkflowSpec(
            workflow_id="broken",
            display_name="Broken",
            nodes=[WorkflowNode("s1", "cap_a")],
            transitions=[],
            initial_node="nonexistent",
        )
        errors = wf.validate()
        assert any("nonexistent" in e for e in errors)

    def test_validate_unreachable_node(self):
        wf = WorkflowSpec(
            workflow_id="w",
            display_name="W",
            nodes=[
                WorkflowNode("s1", "a"),
                WorkflowNode("s2", "b"),
                WorkflowNode("orphan", "c"),  # not connected
            ],
            transitions=[WorkflowTransition("s1", "s2")],
            initial_node="s1",
            terminal_nodes=["s2"],
        )
        errors = wf.validate()
        assert any("orphan" in e for e in errors)

    def test_validate_dangling_transition(self):
        wf = WorkflowSpec(
            workflow_id="w",
            display_name="W",
            nodes=[WorkflowNode("s1", "a")],
            transitions=[WorkflowTransition("s1", "ghost")],  # ghost not in nodes
            initial_node="s1",
        )
        errors = wf.validate()
        assert any("ghost" in e for e in errors)

    def test_to_dict_roundtrip(self):
        wf = _make_support_workflow()
        d = wf.to_dict()
        wf2 = WorkflowSpec.from_dict(d)
        assert wf2.workflow_id == wf.workflow_id
        assert wf2.display_name == wf.display_name
        assert wf2.initial_node == wf.initial_node
        assert len(wf2.nodes) == len(wf.nodes)
        assert len(wf2.transitions) == len(wf.transitions)
        assert wf2.to_stage_actions() == wf.to_stage_actions()

    def test_fallback_policy_default(self):
        wf = WorkflowSpec(workflow_id="w", display_name="W")
        assert wf.fallback_policy == "fail"

    def test_fallback_policy_from_enum(self):
        wf = WorkflowSpec(
            workflow_id="w",
            display_name="W",
            fallback_policy=FallbackPolicy.DEGRADE.value,
        )
        assert wf.fallback_policy == "degrade"

    def test_integration_with_rule_route_engine(self):
        """WorkflowSpec.to_stage_actions() integrates with RuleRouteEngine."""
        from hi_agent.route_engine.rule_engine import RuleRouteEngine

        wf = _make_support_workflow()
        engine = RuleRouteEngine(stage_actions=wf.to_stage_actions())
        proposals = engine.propose("intake", "run-test", 1)
        assert len(proposals) >= 1
        action_kinds = [p.action_kind for p in proposals]
        assert "classify_intent" in action_kinds

    def test_integration_stage_graph_accepted_by_executor(self):
        """WorkflowSpec.to_stage_graph() is accepted by RunExecutor."""
        from hi_agent.contracts import TaskContract
        from hi_agent.runner import RunExecutor

        from tests.helpers.kernel_adapter_fixture import MockKernel

        wf = _make_support_workflow()
        contract = TaskContract(task_id="t1", goal="test workflow")
        kernel = MockKernel()
        # Should not raise — accepts custom stage graph
        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            stage_graph=wf.to_stage_graph(),
        )
        assert executor.stage_graph is not None
