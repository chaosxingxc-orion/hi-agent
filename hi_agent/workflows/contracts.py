"""Workflow contracts: profile-driven stage topology and capability binding.

A WorkflowSpec lets a business agent declare:
- which stages exist and in what order
- which platform capability each stage invokes
- transition conditions between stages
- what to do when a capability is unavailable (fallback policy)

The platform turns a WorkflowSpec into a StageGraph + stage_actions dict
that RuleRouteEngine and RunExecutor understand — without any business
semantics leaking into the core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FallbackPolicy(str, Enum):  # noqa: UP042  # scope: legacy-compatibility — str(EnumMember) behaviour used by downstream serialization
    """Behaviour when a bound capability is unavailable at runtime."""

    FAIL = "fail"  # Fail the stage with an explicit error
    SKIP = "skip"  # Skip the stage and continue
    DEGRADE = "degrade"  # Use a generic fallback capability


@dataclass
class WorkflowNode:
    """A node in the workflow graph representing one execution stage."""

    node_id: str
    capability_binding: str
    description: str = ""
    optional: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowTransition:
    """A directed edge between two workflow nodes."""

    source: str
    target: str
    condition: str = "always"  # always | on_success | on_failure
    priority: int = 0  # lower = higher priority


@dataclass
class WorkflowSpec:
    """Declarative workflow: stage topology + capability bindings.

    Usage::

        from hi_agent.workflows.contracts import WorkflowSpec, WorkflowNode, WorkflowTransition
        from hi_agent.route_engine.rule_engine import RuleRouteEngine

        wf = WorkflowSpec(
            workflow_id="customer_support",
            display_name="Customer Support Workflow",
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

        engine = RuleRouteEngine(stage_actions=wf.to_stage_actions())
        graph = wf.to_stage_graph()
    """

    workflow_id: str
    display_name: str
    nodes: list[WorkflowNode] = field(default_factory=list)
    transitions: list[WorkflowTransition] = field(default_factory=list)
    initial_node: str | None = None
    terminal_nodes: list[str] = field(default_factory=list)
    fallback_policy: str = FallbackPolicy.FAIL.value
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def to_stage_graph(self) -> Any:
        """Convert to a StageGraph for use with RunExecutor.

        Returns:
            A :class:`~hi_agent.trajectory.stage_graph.StageGraph` with
            one edge per WorkflowTransition.
        """
        from hi_agent.trajectory.stage_graph import StageGraph

        graph = StageGraph()
        for t in self.transitions:
            graph.add_edge(t.source, t.target)
        # Ensure terminal nodes appear in the graph even with no outgoing edges.
        for node_id in self.terminal_nodes:
            if node_id not in graph.transitions:
                graph.transitions[node_id] = set()
        return graph

    def to_stage_actions(self) -> dict[str, str]:
        """Return stage_id → capability_binding mapping.

        Pass this directly to ``RuleRouteEngine(stage_actions=...)``.
        """
        return {node.node_id: node.capability_binding for node in self.nodes}

    def get_node(self, node_id: str) -> WorkflowNode | None:
        """Return the node with *node_id*, or None if not found."""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty = valid)."""
        errors: list[str] = []
        node_ids = {n.node_id for n in self.nodes}

        # Missing initial node
        if self.initial_node is None:
            errors.append("initial_node is not set")
        elif self.initial_node not in node_ids:
            errors.append(f"initial_node {self.initial_node!r} not in nodes")

        # Dangling transitions
        for t in self.transitions:
            if t.source not in node_ids:
                errors.append(f"transition source {t.source!r} not in nodes")
            if t.target not in node_ids:
                errors.append(f"transition target {t.target!r} not in nodes")

        # Unreachable nodes (BFS from initial_node)
        if self.initial_node and self.initial_node in node_ids:
            reachable: set[str] = set()
            queue = [self.initial_node]
            while queue:
                current = queue.pop(0)
                if current in reachable:
                    continue
                reachable.add(current)
                for t in self.transitions:
                    if t.source == current and t.target not in reachable:
                        queue.append(t.target)
            unreachable = node_ids - reachable
            for n in sorted(unreachable):
                errors.append(f"node {n!r} is unreachable from initial_node")

        return errors

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "display_name": self.display_name,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "capability_binding": n.capability_binding,
                    "description": n.description,
                    "optional": n.optional,
                    "metadata": n.metadata,
                }
                for n in self.nodes
            ],
            "transitions": [
                {
                    "source": t.source,
                    "target": t.target,
                    "condition": t.condition,
                    "priority": t.priority,
                }
                for t in self.transitions
            ],
            "initial_node": self.initial_node,
            "terminal_nodes": list(self.terminal_nodes),
            "fallback_policy": self.fallback_policy,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowSpec:
        return cls(
            workflow_id=data["workflow_id"],
            display_name=data["display_name"],
            nodes=[
                WorkflowNode(
                    node_id=n["node_id"],
                    capability_binding=n["capability_binding"],
                    description=n.get("description", ""),
                    optional=n.get("optional", False),
                    metadata=n.get("metadata", {}),
                )
                for n in data.get("nodes", [])
            ],
            transitions=[
                WorkflowTransition(
                    source=t["source"],
                    target=t["target"],
                    condition=t.get("condition", "always"),
                    priority=t.get("priority", 0),
                )
                for t in data.get("transitions", [])
            ],
            initial_node=data.get("initial_node"),
            terminal_nodes=list(data.get("terminal_nodes", [])),
            fallback_policy=data.get("fallback_policy", FallbackPolicy.FAIL.value),
            metadata=dict(data.get("metadata", {})),
        )
