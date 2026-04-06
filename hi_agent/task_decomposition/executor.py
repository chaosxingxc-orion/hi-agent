"""DAG executor: drives sub-task execution through a TaskDAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from hi_agent.task_decomposition.dag import TaskDAG, TaskNode, TaskNodeState


@dataclass
class DAGProgress:
    """Snapshot of DAG execution progress.

    Attributes:
        completed: Number of completed nodes.
        total: Total number of nodes in the DAG.
        running: Node IDs currently running.
        failed: Node IDs that have failed.
    """

    completed: int
    total: int
    running: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


@dataclass
class DAGStepResult:
    """Result of a single execution step.

    Attributes:
        dispatched: Node IDs started this step.
        completed: Node IDs finished this step.
        failed: Node IDs that failed this step.
        is_terminal: True when no more work is possible.
    """

    dispatched: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    is_terminal: bool = False


@dataclass
class DAGResult:
    """Final result after running a DAG to completion.

    Attributes:
        success: True if all nodes completed or were skipped.
        completed_nodes: Node IDs that completed successfully.
        failed_nodes: Node IDs that failed permanently.
        rolled_back_nodes: Node IDs that were rolled back.
        total_steps: Number of execution steps taken.
    """

    success: bool
    completed_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[str] = field(default_factory=list)
    rolled_back_nodes: list[str] = field(default_factory=list)
    total_steps: int = 0


def _default_execute(node: TaskNode) -> dict[str, Any]:
    """No-op default executor that always succeeds."""
    return {"status": "ok"}


class DAGExecutor:
    """Executes a TaskDAG, dispatching ready nodes and managing lifecycle.

    The executor drives sub-task execution by:
    1. Finding ready nodes (all dependencies satisfied).
    2. Dispatching them via the ``execute_fn`` callback.
    3. Handling completion and failure.
    4. Triggering rollback on failure when the node's policy requires it.
    5. Reporting progress via the ``on_progress`` callback.

    Args:
        dag: The task DAG to execute.
        execute_fn: Callable that runs a single node. Returns a result
            dict on success; raises an exception on failure.
        on_progress: Optional callback invoked after each step with a
            progress snapshot.
    """

    def __init__(
        self,
        dag: TaskDAG,
        execute_fn: Callable[[TaskNode], dict[str, Any]] | None = None,
        on_progress: Callable[[DAGProgress], None] | None = None,
    ) -> None:
        self.dag = dag
        self.execute_fn = execute_fn or _default_execute
        self.on_progress = on_progress
        self._rolled_back: list[str] = []

    def step(self) -> DAGStepResult:
        """Execute one step: find ready nodes, dispatch them, collect results.

        Returns:
            A DAGStepResult describing what happened in this step.
        """
        ready = self.dag.get_ready_nodes()

        if not ready and not self._has_running():
            return DAGStepResult(is_terminal=True)

        dispatched: list[str] = []
        completed: list[str] = []
        failed: list[str] = []

        for node in ready:
            self.dag.mark_running(node.node_id)
            dispatched.append(node.node_id)

            try:
                result = self.execute_fn(node)
                self.dag.mark_completed(node.node_id, result)
                completed.append(node.node_id)
            except Exception as exc:
                self.dag.mark_failed(node.node_id, str(exc))
                failed.append(node.node_id)

                # Apply rollback policy.
                if node.rollback_policy in ("compensate", "cascade"):
                    self._rolled_back.extend(self.rollback(node.node_id))

        if self.on_progress is not None:
            self.on_progress(self._make_progress())

        is_terminal = self.dag.is_complete() or (
            self.dag.is_failed() and not self.dag.get_ready_nodes()
        )

        return DAGStepResult(
            dispatched=dispatched,
            completed=completed,
            failed=failed,
            is_terminal=is_terminal,
        )

    def run_to_completion(self) -> DAGResult:
        """Run all steps until the DAG is complete or fatally failed.

        Returns:
            A DAGResult summarising the execution.
        """
        total_steps = 0
        while True:
            result = self.step()
            total_steps += 1
            if result.is_terminal:
                break

        completed_ids = [
            nid for nid, n in self.dag.nodes.items()
            if n.state == TaskNodeState.COMPLETED
        ]
        failed_ids = [
            nid for nid, n in self.dag.nodes.items()
            if n.state == TaskNodeState.FAILED
        ]

        return DAGResult(
            success=self.dag.is_complete(),
            completed_nodes=completed_ids,
            failed_nodes=failed_ids,
            rolled_back_nodes=list(self._rolled_back),
            total_steps=total_steps,
        )

    def rollback(self, failed_node_id: str) -> list[str]:
        """Rollback completed nodes that the failed node depends on.

        Walks the dependency chain upward and marks completed ancestors
        as ROLLED_BACK when the rollback policy is ``"cascade"``.
        For ``"compensate"`` only direct dependencies are rolled back.

        Args:
            failed_node_id: The node that failed.

        Returns:
            List of node IDs that were rolled back.
        """
        failed_node = self.dag.get_node(failed_node_id)
        rolled_back: list[str] = []

        if failed_node.rollback_policy == "none":
            return rolled_back

        if failed_node.rollback_policy == "compensate":
            # Roll back direct dependencies only.
            for dep_id in failed_node.dependencies:
                dep = self.dag.get_node(dep_id)
                if dep.state == TaskNodeState.COMPLETED:
                    dep.state = TaskNodeState.ROLLED_BACK
                    rolled_back.append(dep_id)
            return rolled_back

        # "cascade" — roll back all transitive dependencies.
        frontier = list(failed_node.dependencies)
        visited: set[str] = set()
        while frontier:
            nid = frontier.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            node = self.dag.get_node(nid)
            if node.state == TaskNodeState.COMPLETED:
                node.state = TaskNodeState.ROLLED_BACK
                rolled_back.append(nid)
            frontier.extend(node.dependencies)

        return rolled_back

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _has_running(self) -> bool:
        """Check if any node is currently in RUNNING state."""
        return any(
            n.state == TaskNodeState.RUNNING
            for n in self.dag.nodes.values()
        )

    def _make_progress(self) -> DAGProgress:
        """Build a progress snapshot."""
        nodes = self.dag.nodes
        return DAGProgress(
            completed=sum(
                1 for n in nodes.values()
                if n.state == TaskNodeState.COMPLETED
            ),
            total=len(nodes),
            running=[
                nid for nid, n in nodes.items()
                if n.state == TaskNodeState.RUNNING
            ],
            failed=[
                nid for nid, n in nodes.items()
                if n.state == TaskNodeState.FAILED
            ],
        )
