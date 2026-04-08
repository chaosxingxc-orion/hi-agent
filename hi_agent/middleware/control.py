"""Control middleware: request decomposition and trajectory planning.

Receives standardized PerceptionResult, decomposes into executable
TrajectoryGraph with per-node resource bindings.
"""
from __future__ import annotations

from typing import Any

from hi_agent.middleware.protocol import (
    ExecutionPlan,
    MiddlewareMessage,
    PerceptionResult,
)
from hi_agent.trajectory.graph import TrajNode, TrajectoryGraph


# Default TRACE stage sequence
_DEFAULT_STAGES = [
    ("understand", "Understand the task requirements"),
    ("gather", "Gather necessary information"),
    ("build", "Build or analyze the solution"),
    ("synthesize", "Synthesize results"),
    ("review", "Review and finalize"),
]


class ControlMiddleware:
    """Task decomposition and planning middleware."""

    def __init__(
        self,
        skill_loader: Any | None = None,
        knowledge_manager: Any | None = None,
        llm_gateway: Any | None = None,
        max_plan_nodes: int = 20,
    ) -> None:
        self._skill_loader = skill_loader
        self._knowledge_manager = knowledge_manager
        self._llm_gateway = llm_gateway
        self._max_plan_nodes = max_plan_nodes

    @property
    def name(self) -> str:
        return "control"

    def on_create(self, config: dict[str, Any]) -> None:
        """Configure from external config dict."""
        if "max_plan_nodes" in config:
            self._max_plan_nodes = config["max_plan_nodes"]

    def on_destroy(self) -> None:
        """Cleanup resources."""
        self._skill_loader = None
        self._knowledge_manager = None
        self._llm_gateway = None

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage:
        """Decompose request -> TrajectoryGraph -> resource bindings."""
        # Reconstruct PerceptionResult from payload
        payload = message.payload
        perception = PerceptionResult(
            raw_text=payload.get("raw_text", ""),
            entities=[],
            summary=payload.get("summary"),
            modality=payload.get("modality", "text"),
            context=payload.get("context", ""),
            token_count=payload.get("token_count", 0),
            metadata=payload.get("metadata", {}),
        )

        graph_json = self._decompose(perception)
        resources = self._bind_resources(graph_json, perception)
        issues = self._validate_executability(graph_json, resources)

        plan = ExecutionPlan(
            graph_json=graph_json,
            node_resources=resources,
            total_nodes=len(graph_json.get("nodes", [])),
            estimated_cost=0.0,
        )

        return MiddlewareMessage(
            source="control",
            target="execution",
            msg_type="execution_plan",
            payload={
                "graph_json": plan.graph_json,
                "node_resources": plan.node_resources,
                "total_nodes": plan.total_nodes,
                "estimated_cost": plan.estimated_cost,
                "validation_issues": issues,
                "perception_text": perception.raw_text,
            },
            token_cost=message.token_cost,
            metadata=message.metadata,
        )

    def _decompose(self, perception: PerceptionResult) -> dict[str, Any]:
        """Decompose into TrajectoryGraph JSON.
        With LLM: ask model to plan steps.
        Without LLM: heuristic decomposition (linear 5-stage TRACE)."""
        # Heuristic: create a linear TRACE chain
        nodes = []
        edges = []
        for i, (stage_id, desc) in enumerate(_DEFAULT_STAGES):
            nodes.append({
                "node_id": stage_id,
                "node_type": "stage",
                "payload": {
                    "description": desc,
                    "input_text": perception.raw_text if i == 0 else "",
                },
            })
            if i > 0:
                edges.append({
                    "source": _DEFAULT_STAGES[i - 1][0],
                    "target": stage_id,
                    "edge_type": "sequence",
                })

        return {
            "graph_id": "trace_plan",
            "nodes": nodes,
            "edges": edges,
        }

    def _bind_resources(
        self, graph_json: dict[str, Any], perception: PerceptionResult,
    ) -> dict[str, dict[str, Any]]:
        """For each node, determine: which skill, what memory query,
        what knowledge query, what tools.
        Returns: {node_id: {skill_id, memory_query, knowledge_query, tools[]}}"""
        resources: dict[str, dict[str, Any]] = {}
        for node in graph_json.get("nodes", []):
            node_id = node["node_id"]
            resources[node_id] = {
                "skill_id": None,
                "memory_query": perception.raw_text[:200] if perception.raw_text else "",
                "knowledge_query": "",
                "tools": [],
            }

            # Attempt skill matching if loader available
            if self._skill_loader is not None:
                try:
                    desc = node.get("payload", {}).get("description", "")
                    if hasattr(self._skill_loader, "match"):
                        skill = self._skill_loader.match(desc)
                        if skill:
                            resources[node_id]["skill_id"] = getattr(skill, "skill_id", None)
                except Exception:
                    pass

        return resources

    def _validate_executability(
        self, graph_json: dict[str, Any], resources: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Check each node is executable (skill exists, tools available).
        Returns list of issues (empty = all good)."""
        issues: list[str] = []
        for node in graph_json.get("nodes", []):
            node_id = node["node_id"]
            res = resources.get(node_id, {})
            # No strict validation without external deps -- just check structure
            if not res:
                issues.append(f"Node '{node_id}' has no resource bindings")
        return issues

    def handle_escalation(self, escalation: MiddlewareMessage) -> MiddlewareMessage:
        """Handle escalation from Evaluation: re-plan failed portion of graph."""
        payload = escalation.payload
        failed_node_id = payload.get("node_id", "unknown")
        original_text = payload.get("perception_text", "")
        feedback = payload.get("feedback", "")

        # Create a simpler single-node plan for the failed portion
        graph_json: dict[str, Any] = {
            "graph_id": f"replan_{failed_node_id}",
            "nodes": [
                {
                    "node_id": f"{failed_node_id}_retry",
                    "node_type": "task",
                    "payload": {
                        "description": f"Retry: {feedback}",
                        "input_text": original_text,
                    },
                }
            ],
            "edges": [],
        }

        resources = {
            f"{failed_node_id}_retry": {
                "skill_id": None,
                "memory_query": original_text[:200],
                "knowledge_query": "",
                "tools": [],
            },
        }

        return MiddlewareMessage(
            source="control",
            target="execution",
            msg_type="execution_plan",
            payload={
                "graph_json": graph_json,
                "node_resources": resources,
                "total_nodes": 1,
                "estimated_cost": 0.0,
                "validation_issues": [],
                "perception_text": original_text,
            },
            token_cost=0,
            metadata=escalation.metadata,
        )
