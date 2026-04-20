"""Task decomposition engine: breaks a TaskContract into a TaskDAG."""

from __future__ import annotations

import uuid
from typing import Any

from hi_agent.contracts import TaskContract
from hi_agent.task_decomposition.dag import TaskDAG, TaskNode

# Default TRACE stage sequence used for linear decomposition.
_TRACE_STAGES: list[tuple[str, str]] = [
    ("understand", "Understand the task requirements and constraints"),
    ("gather", "Gather necessary information and resources"),
    ("build", "Build or analyze the core solution"),
    ("synthesize", "Synthesize results into deliverable form"),
    ("review", "Review and finalize the output"),
]


class TaskDecomposer:
    """Decomposes a TaskContract into a TaskDAG.

    Strategies:
    - ``"linear"``: Sequential chain of sub-tasks matching TRACE stages.
    - ``"dag"``: Parallel DAG based on dependency analysis.
    - ``"tree"``: Recursive decomposition tree (falls back to linear
      for rule-based mode).

    Without an LLM gateway the decomposer uses rule-based heuristics.
    With an LLM gateway it delegates goal analysis to the model.

    Attributes:
        llm_gateway: Optional LLM gateway for model-assisted decomposition.
    """

    def __init__(self, llm_gateway: Any | None = None) -> None:
        """Initialize TaskDecomposer."""
        self.llm_gateway = llm_gateway

    def decompose(self, contract: TaskContract) -> TaskDAG:
        """Decompose a task into a sub-task DAG.

        The strategy is selected from ``contract.decomposition_strategy``.
        Falls back to ``"linear"`` when the strategy is ``None`` or
        unrecognised.

        Args:
            contract: The top-level task contract to decompose.

        Returns:
            A validated TaskDAG containing sub-task nodes.
        """
        strategy = contract.decomposition_strategy or "linear"

        if strategy == "dag":
            return self._dag_decompose(contract)
        elif strategy == "tree":
            return self._tree_decompose(contract)
        else:
            return self._linear_decompose(contract)

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _linear_decompose(self, contract: TaskContract) -> TaskDAG:
        """Default 5-stage linear decomposition matching TRACE stages.

        Each stage depends on the previous one, forming a simple chain.
        """
        dag = TaskDAG()
        prev_id: str | None = None

        for stage_key, stage_desc in _TRACE_STAGES:
            deps = [prev_id] if prev_id else []
            node = self._create_subtask(
                parent=contract,
                stage=stage_key,
                goal=f"{stage_desc} for: {contract.goal}",
                deps=deps,
            )
            dag.add_node(node)
            if prev_id is not None:
                dag.add_edge(prev_id, node.node_id)
            prev_id = node.node_id

        return dag

    def _dag_decompose(self, contract: TaskContract) -> TaskDAG:
        """Parallel DAG decomposition.

        Uses LLM if available; otherwise falls back to a heuristic that
        runs *understand* first, then *gather* and *build* in parallel,
        followed by *synthesize* and *review* in sequence.
        """
        if self.llm_gateway is not None:
            try:
                return self._llm_dag_decompose(contract)
            except Exception:
                pass  # fall through to heuristic DAG below

        dag = TaskDAG()

        understand = self._create_subtask(
            contract, "understand",
            f"Understand requirements for: {contract.goal}", [],
        )
        dag.add_node(understand)

        gather = self._create_subtask(
            contract, "gather",
            f"Gather information for: {contract.goal}",
            [understand.node_id],
        )
        dag.add_node(gather)
        dag.add_edge(understand.node_id, gather.node_id)

        build = self._create_subtask(
            contract, "build",
            f"Build core solution for: {contract.goal}",
            [understand.node_id],
        )
        dag.add_node(build)
        dag.add_edge(understand.node_id, build.node_id)

        synthesize = self._create_subtask(
            contract, "synthesize",
            f"Synthesize results for: {contract.goal}",
            [gather.node_id, build.node_id],
        )
        dag.add_node(synthesize)
        dag.add_edge(gather.node_id, synthesize.node_id)
        dag.add_edge(build.node_id, synthesize.node_id)

        review = self._create_subtask(
            contract, "review",
            f"Review and finalize: {contract.goal}",
            [synthesize.node_id],
        )
        dag.add_node(review)
        dag.add_edge(synthesize.node_id, review.node_id)

        return dag

    def _tree_decompose(self, contract: TaskContract) -> TaskDAG:
        """Recursive decomposition tree.

        With an LLM, asks for a two-level hierarchy: top-level sub-goals
        each with optional child sub-goals.  Children are added first
        (no deps); each parent depends on all its children.
        Falls back to linear decomposition on any error or when no LLM.
        """
        if self.llm_gateway is not None:
            try:
                return self._llm_tree_decompose(contract)
            except Exception:
                pass  # fall through to linear
        return self._linear_decompose(contract)

    def _llm_dag_decompose(self, contract: TaskContract) -> TaskDAG:
        """Call LLM to build a structured DAG plan.

        Prompt the model for a JSON list of nodes
        ``[{"stage": str, "goal": str, "deps": [stage_name, ...]}]``
        where ``deps`` are stage names of predecessors.  Falls back to the
        heuristic DAG if parsing fails.
        """
        from hi_agent.llm.protocol import LLMRequest

        prompt = (
            f"Decompose this task into a parallel DAG of sub-tasks:\n\n"
            f"Goal: {contract.goal}\n\n"
            "Return a JSON array of nodes. Each node:\n"
            '  {"stage": "<short_name>", "goal": "<sub-goal>", "deps": ["<stage_name>", ...]}\n'
            "deps lists stage names this node depends on (empty list = no deps).\n"
            "Aim for 3-6 nodes with real parallelism where possible.\n"
            "Respond with ONLY the JSON array, no extra text."
        )
        assert self.llm_gateway is not None
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        response = self.llm_gateway.complete(request)

        import json
        items = json.loads(response.content)
        if not isinstance(items, list) or not items:
            raise ValueError("LLM returned empty or non-list DAG plan")

        dag = TaskDAG()
        node_by_stage: dict[str, TaskNode] = {}

        # First pass: create all nodes
        for item in items:
            stage = str(item.get("stage", "")).strip()
            goal = str(item.get("goal", "")).strip()
            if not stage or not goal:
                continue
            node = self._create_subtask(contract, stage, goal, [])
            dag.add_node(node)
            node_by_stage[stage] = node

        if not node_by_stage:
            raise ValueError("LLM returned no valid nodes")

        # Second pass: wire edges
        for item in items:
            stage = str(item.get("stage", "")).strip()
            if stage not in node_by_stage:
                continue
            node = node_by_stage[stage]
            for dep_stage in item.get("deps", []):
                dep_stage = str(dep_stage).strip()
                if dep_stage in node_by_stage:
                    dep_node = node_by_stage[dep_stage]
                    dag.add_edge(dep_node.node_id, node.node_id)

        return dag

    def _llm_tree_decompose(self, contract: TaskContract) -> TaskDAG:
        """Call LLM to build a two-level hierarchical task tree as a DAG."""
        from hi_agent.llm.protocol import LLMRequest

        prompt = (
            f"Decompose this task hierarchically into a 2-level tree:\n\n"
            f"Goal: {contract.goal}\n\n"
            "Return a JSON array of top-level nodes, each with optional children:\n"
            '  [{"stage": "<name>", "goal": "<sub-goal>", '
            '"children": [{"stage": "<name>", "goal": "<sub-goal>"}]}]\n'
            "Aim for 2-4 top-level nodes, each with 0-3 children.\n"
            "Respond with ONLY the JSON array."
        )
        assert self.llm_gateway is not None
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=900,
        )
        response = self.llm_gateway.complete(request)

        import json
        items = json.loads(response.content)
        if not isinstance(items, list) or not items:
            raise ValueError("LLM returned empty tree plan")

        dag = TaskDAG()

        for item in items:
            parent_stage = str(item.get("stage", "")).strip()
            parent_goal = str(item.get("goal", "")).strip()
            if not parent_stage or not parent_goal:
                continue

            child_ids: list[str] = []
            for child in item.get("children", []):
                c_stage = str(child.get("stage", "")).strip()
                c_goal = str(child.get("goal", "")).strip()
                if not c_stage or not c_goal:
                    continue
                child_node = self._create_subtask(contract, c_stage, c_goal, [])
                dag.add_node(child_node)
                child_ids.append(child_node.node_id)

            parent_node = self._create_subtask(contract, parent_stage, parent_goal, child_ids)
            dag.add_node(parent_node)
            for cid in child_ids:
                dag.add_edge(cid, parent_node.node_id)

        if not dag._nodes:
            raise ValueError("No valid nodes in tree plan")

        return dag

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_subtask(
        self,
        parent: TaskContract,
        stage: str,
        goal: str,
        deps: list[str],
    ) -> TaskNode:
        """Create a sub-task node inheriting parent context.

        Args:
            parent: The parent task contract.
            stage: Stage key (e.g. ``"understand"``).
            goal: Natural-language goal for the sub-task.
            deps: Node IDs this sub-task depends on.

        Returns:
            A new TaskNode ready to be added to a DAG.
        """
        node_id = f"{parent.task_id}:{stage}:{uuid.uuid4().hex[:8]}"
        sub_contract = TaskContract(
            task_id=node_id,
            goal=goal,
            constraints=list(parent.constraints),
            acceptance_criteria=[],
            task_family=parent.task_family,
            budget=parent.budget,
            deadline=parent.deadline,
            risk_level=parent.risk_level,
            environment_scope=list(parent.environment_scope),
            input_refs=list(parent.input_refs),
            priority=parent.priority,
            parent_task_id=parent.task_id,
            decomposition_strategy=None,
        )
        return TaskNode(
            node_id=node_id,
            task_contract=sub_contract,
            dependencies=list(deps),
        )
