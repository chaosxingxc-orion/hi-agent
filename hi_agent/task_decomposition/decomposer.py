"""Task decomposition engine: breaks a TaskContract into a TaskDAG."""

from __future__ import annotations

import uuid
from typing import Any

from hi_agent.contracts import TaskContract, TaskBudget
from hi_agent.task_decomposition.dag import TaskDAG, TaskNode, TaskNodeState


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
            # Placeholder: would call model to produce structured plan.
            return self._linear_decompose(contract)

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

        Without an LLM this falls back to linear decomposition.
        """
        if self.llm_gateway is not None:
            return self._linear_decompose(contract)
        return self._linear_decompose(contract)

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
