"""Main orchestrator: connects TaskDecomposition to RunExecutor."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts import TaskContract
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.task_decomposition.dag import TaskDAG, TaskNode, TaskNodeState
from hi_agent.task_decomposition.decomposer import TaskDecomposer
from hi_agent.task_decomposition.executor import DAGExecutor
from hi_agent.task_decomposition.feedback import DecompositionFeedback


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass
class SubTaskResult:
    """Result of a single sub-task execution.

    Attributes:
        node_id: DAG node identifier.
        task_id: Sub-task contract identifier.
        outcome: One of ``"completed"``, ``"failed"``, ``"skipped"``,
            ``"rolled_back"``.
        result: Arbitrary result payload from the sub-task executor.
        error: Human-readable error description when outcome is ``"failed"``.
    """

    node_id: str
    task_id: str
    outcome: str  # "completed" | "failed" | "skipped" | "rolled_back"
    result: Any = None
    error: str | None = None


@dataclass
class OrchestratorResult:
    """Aggregate result of an orchestrated task execution.

    Attributes:
        success: ``True`` when all sub-tasks completed successfully.
        task_id: Top-level task contract identifier.
        strategy: ``None`` for simple (no decomposition), or
            ``"linear"``/``"dag"``/``"tree"`` for decomposed tasks.
        sub_results: Per-node results.
        total_duration_seconds: Wall-clock duration of the execution.
        error: Top-level error message, if applicable.
    """

    success: bool
    task_id: str
    strategy: str | None  # None for simple, "linear"/"dag"/"tree" for decomposed
    sub_results: list[SubTaskResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TaskOrchestrator:
    """Orchestrates complex task execution via decomposition.

    For simple tasks (no ``decomposition_strategy``): delegates directly
    to :class:`RunExecutor`.

    For complex tasks: decomposes into a DAG, executes sub-tasks via
    individual :class:`RunExecutor` instances, and aggregates results.

    Args:
        kernel: Runtime adapter for run lifecycle management.
        decomposer: Optional task decomposer (created with defaults if
            not provided).
        feedback: Optional feedback collector for decomposition analytics.
        max_parallel: Maximum concurrent sub-tasks dispatched.
        on_subtask_complete: Optional callback invoked after each sub-task
            finishes, receiving the :class:`SubTaskResult`.
    """

    def __init__(
        self,
        kernel: RuntimeAdapter,
        *,
        decomposer: TaskDecomposer | None = None,
        feedback: DecompositionFeedback | None = None,
        max_parallel: int = 4,
        on_subtask_complete: Callable[[SubTaskResult], None] | None = None,
    ) -> None:
        self._kernel = kernel
        self._decomposer = decomposer or TaskDecomposer()
        self._feedback = feedback
        self._max_parallel = max_parallel
        self._on_subtask_complete = on_subtask_complete

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, contract: TaskContract) -> OrchestratorResult:
        """Execute task, with automatic decomposition if strategy is set.

        Args:
            contract: The top-level task contract.

        Returns:
            An :class:`OrchestratorResult` summarising the execution.
        """
        t0 = time.monotonic()
        try:
            if contract.decomposition_strategy is None:
                result = self._execute_simple(contract)
            else:
                result = self._execute_decomposed(contract)
        except Exception as exc:  # noqa: BLE001
            result = OrchestratorResult(
                success=False,
                task_id=contract.task_id,
                strategy=contract.decomposition_strategy,
                error=str(exc),
            )
        result.total_duration_seconds = time.monotonic() - t0
        return result

    # ------------------------------------------------------------------
    # Simple (direct) execution
    # ------------------------------------------------------------------

    def _execute_simple(self, contract: TaskContract) -> OrchestratorResult:
        """Direct execution without decomposition.

        Creates a single :class:`RunExecutor` for the contract and runs it
        to completion.
        """
        from hi_agent.runner import RunExecutor

        runner = RunExecutor(contract, self._kernel)
        status = runner.execute()
        sub = SubTaskResult(
            node_id=contract.task_id,
            task_id=contract.task_id,
            outcome="completed" if status == "completed" else "failed",
            result={"status": status},
            error=None if status == "completed" else f"Run finished with status: {status}",
        )
        return OrchestratorResult(
            success=(status == "completed"),
            task_id=contract.task_id,
            strategy=None,
            sub_results=[sub],
        )

    # ------------------------------------------------------------------
    # Decomposed execution
    # ------------------------------------------------------------------

    def _execute_decomposed(self, contract: TaskContract) -> OrchestratorResult:
        """Decompose and execute as DAG.

        Steps:
        1. Decompose the contract into a :class:`TaskDAG`.
        2. Use :class:`DAGExecutor` to walk the DAG, calling
           :meth:`_execute_subtask` for each node.
        3. Collect per-node results and aggregate.
        4. Optionally record feedback.
        """
        from hi_agent.orchestrator.result_aggregator import ResultAggregator

        dag = self._decomposer.decompose(contract)
        aggregator = ResultAggregator()

        def _node_executor(node: TaskNode) -> dict[str, Any]:
            """Execute a single node and feed the aggregator."""
            result_payload = self._execute_subtask(node)
            sub = SubTaskResult(
                node_id=node.node_id,
                task_id=node.task_contract.task_id,
                outcome="completed",
                result=result_payload,
            )
            aggregator.record(node.node_id, sub)
            if self._on_subtask_complete is not None:
                self._on_subtask_complete(sub)
            return result_payload

        dag_executor = DAGExecutor(dag, execute_fn=_node_executor)
        dag_result = dag_executor.run_to_completion()

        # Record failures into the aggregator.
        for nid in dag_result.failed_nodes:
            node = dag.get_node(nid)
            sub = SubTaskResult(
                node_id=nid,
                task_id=node.task_contract.task_id,
                outcome="failed",
                error=node.failure_reason,
            )
            aggregator.record(nid, sub)

        # Record rolled-back nodes.
        for nid in dag_result.rolled_back_nodes:
            node = dag.get_node(nid)
            sub = SubTaskResult(
                node_id=nid,
                task_id=node.task_contract.task_id,
                outcome="rolled_back",
            )
            aggregator.record(nid, sub)

        # Record skipped nodes (pending nodes that never ran).
        for nid, node in dag.nodes.items():
            if node.state == TaskNodeState.PENDING and nid not in aggregator._results:
                sub = SubTaskResult(
                    node_id=nid,
                    task_id=node.task_contract.task_id,
                    outcome="skipped",
                )
                aggregator.record(nid, sub)

        # Optionally record feedback for future strategy tuning.
        if self._feedback is not None:
            self._feedback.record(
                task_family=contract.task_family,
                strategy=contract.decomposition_strategy or "linear",
                result=dag_result,
            )

        result = aggregator.aggregate(
            task_id=contract.task_id,
            strategy=contract.decomposition_strategy,
        )
        result.success = dag_result.success
        return result

    # ------------------------------------------------------------------
    # Single sub-task execution
    # ------------------------------------------------------------------

    def _execute_subtask(self, node: TaskNode) -> dict[str, Any]:
        """Execute a single sub-task node using :class:`RunExecutor`.

        Creates a lightweight :class:`RunExecutor` for the node's
        sub-contract and runs it.  Returns the result payload.

        Raises:
            RuntimeError: If the sub-task execution fails.
        """
        from hi_agent.runner import RunExecutor

        runner = RunExecutor(node.task_contract, self._kernel)
        status = runner.execute()
        if status != "completed":
            raise RuntimeError(
                f"Sub-task {node.node_id} failed with status: {status}"
            )
        return {"status": status, "node_id": node.node_id}
