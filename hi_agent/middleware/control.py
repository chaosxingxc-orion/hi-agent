"""Control middleware: request decomposition and trajectory planning.

Receives standardized PerceptionResult, decomposes into executable
TrajectoryGraph with per-node resource bindings.

When an LLM gateway is available the decomposition is driven by the
model -- the gateway receives the task description and returns a
JSON array of stages.  On any failure (missing gateway, parse error,
LLM exception) the middleware falls back to the deterministic
``_DEFAULT_STAGES`` five-stage plan.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hi_agent.middleware.protocol import (
    ExecutionPlan,
    MiddlewareMessage,
    PerceptionResult,
)

logger = logging.getLogger(__name__)

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
        model_tier: str = "medium",
    ) -> None:
        """Initialize ControlMiddleware."""
        self._skill_loader = skill_loader
        self._knowledge_manager = knowledge_manager
        self._llm_gateway = llm_gateway
        self._max_plan_nodes = max_plan_nodes
        self._model_tier = model_tier

    @property
    def name(self) -> str:
        """Return name."""
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
        run_id: str | None = message.metadata.get("run_id")
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

        graph_json = self._decompose(perception, run_id=run_id)
        resources = self._bind_resources(graph_json, perception)
        issues = self._validate_executability(graph_json, resources)

        node_count = len(graph_json.get("nodes", []))
        # Estimate cost proportional to decomposed node count; default stages have
        # a known cost of 0 (heuristic path, no LLM calls consumed for planning).
        is_default_plan = [
            (n["node_id"], n["payload"].get("description", "")) for n in graph_json.get("nodes", [])
        ] == [(s[0], s[1]) for s in _DEFAULT_STAGES]
        estimated_cost = 0.0 if is_default_plan else float(node_count) * 0.01
        plan = ExecutionPlan(
            graph_json=graph_json,
            node_resources=resources,
            total_nodes=node_count,
            estimated_cost=estimated_cost,
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

    # ------------------------------------------------------------------
    # LLM-driven adaptive decomposition
    # ------------------------------------------------------------------

    _DECOMPOSE_PROMPT_TEMPLATE = (
        "Given this task, decompose it into ordered stages for execution.\n"
        "Return ONLY a JSON array of objects, each with:\n"
        '  - "stage_id": a short snake_case identifier\n'
        '  - "stage_name": a human-readable name\n'
        '  - "description": what this stage does\n'
        '  - "depends_on": list of stage_ids this stage depends on '
        "(empty list for the first stage)\n\n"
        "Task: {task}\n\n"
        "Context: {context}\n\n"
        "Return the JSON array and nothing else."
    )

    def _llm_decompose(
        self,
        task_description: str,
        context: dict[str, Any],
        *,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Ask the LLM to decompose *task_description* into stages.

        Returns a list of stage dicts on success.
        Raises ``ValueError`` on parse / validation failure so the
        caller can fall back to the default stages.
        """
        from hi_agent.llm.protocol import LLMRequest

        prompt = self._DECOMPOSE_PROMPT_TEMPLATE.format(
            task=task_description,
            context=json.dumps(context) if context else "{}",
        )
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="default",
            temperature=0.3,
            max_tokens=2048,
            metadata={"purpose": self._model_tier, "run_id": run_id},
        )
        response = self._llm_gateway.complete(request)  # type: ignore[union-attr]  expiry_wave: Wave 27
        raw = response.content.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            # Remove opening fence (and optional language tag) and closing fence
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        stages: list[dict[str, Any]] = json.loads(raw)

        # --- validation ---
        if not isinstance(stages, list) or len(stages) < 2:
            raise ValueError(
                f"LLM returned {type(stages).__name__} with "
                f"{len(stages) if isinstance(stages, list) else 0} items; "
                "need a list of >= 2 stages"
            )
        for s in stages:
            if "stage_id" not in s or "stage_name" not in s:
                raise ValueError(f"Stage missing required keys (stage_id, stage_name): {s}")
        return stages

    # ------------------------------------------------------------------

    def _decompose(
        self, perception: PerceptionResult, *, run_id: str | None = None
    ) -> dict[str, Any]:
        """Decompose perception result into TrajectoryGraph JSON.

        Attempts LLM-driven decomposition when a gateway is available,
        falling back to the deterministic ``_DEFAULT_STAGES`` on any failure.
        """
        stages: list[tuple[str, str]] | None = None

        if self._llm_gateway is not None:
            try:
                llm_stages = self._llm_decompose(
                    perception.raw_text,
                    perception.metadata,
                    run_id=run_id,
                )
                # Convert to the (stage_id, description) tuple format
                stages = [
                    (s["stage_id"], s.get("description", s["stage_name"])) for s in llm_stages
                ]
            except Exception as exc:
                from hi_agent.observability.fallback import record_fallback

                record_fallback(
                    "heuristic",
                    reason="llm_stage_decompose_failed_default_plan",
                    run_id=run_id or "unknown",
                    extra={
                        "site": "ControlMiddleware._decompose",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                        "default_stage_count": len(_DEFAULT_STAGES),
                    },
                    logger=logger,
                )

        if stages is None:
            stages = list(_DEFAULT_STAGES)

        # Build the graph JSON
        nodes = []
        edges = []
        for i, (stage_id, desc) in enumerate(stages):
            nodes.append(
                {
                    "node_id": stage_id,
                    "node_type": "stage",
                    "payload": {
                        "description": desc,
                        "input_text": perception.raw_text if i == 0 else "",
                    },
                }
            )
            if i > 0:
                edges.append(
                    {
                        "source": stages[i - 1][0],
                        "target": stage_id,
                        "edge_type": "sequence",
                    }
                )

        return {
            "graph_id": "trace_plan",
            "nodes": nodes,
            "edges": edges,
        }

    def _bind_resources(
        self,
        graph_json: dict[str, Any],
        perception: PerceptionResult,
    ) -> dict[str, dict[str, Any]]:
        """Resolve skill, memory, knowledge, and tool resources per node."""
        resources: dict[str, dict[str, Any]] = {}
        for node in graph_json.get("nodes", []):
            node_id = node["node_id"]
            resources[node_id] = {
                "skill_id": None,
                "memory_query": perception.raw_text[:200] if perception.raw_text else "",
                "knowledge_query": "",
                "tools": [],
            }

            # Attempt knowledge query if knowledge_manager available
            if self._knowledge_manager is not None:
                try:
                    desc = node.get("payload", {}).get("description", "")
                    if desc and hasattr(self._knowledge_manager, "query"):
                        kresult = self._knowledge_manager.query(desc, limit=3)
                        pages = getattr(kresult, "wiki_pages", []) or []
                        if pages:
                            resources[node_id]["knowledge_query"] = desc
                except Exception as exc:
                    logger.debug("Control middleware knowledge query failed: %s", exc)

            # Attempt skill matching if loader available
            if self._skill_loader is not None:
                try:
                    desc = node.get("payload", {}).get("description", "")
                    if hasattr(self._skill_loader, "match"):
                        skill = self._skill_loader.match(desc)
                        if skill:
                            resources[node_id]["skill_id"] = getattr(skill, "skill_id", None)
                except Exception as exc:
                    logger.warning("Control middleware plan decomposition failed: %s", exc)

        return resources

    def _validate_executability(
        self,
        graph_json: dict[str, Any],
        resources: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Validate node executability and return issue list."""
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
