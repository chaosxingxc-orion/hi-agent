"""Superstep execution engine for TrajectoryGraph.

Pregel-inspired: each step processes all ready nodes in parallel,
collects results, updates state, evaluates conditional edges, repeats.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hi_agent.trajectory.graph import (
    EdgeType,
    NodeState,
    TrajectoryGraph,
    TrajNode,
)


@dataclass
class StepResult:
    """Result of one superstep."""

    step_number: int
    executed: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    backtracked: list[str] = field(default_factory=list)
    is_terminal: bool = False


@dataclass
class ExecutionResult:
    """Result of full graph execution."""

    success: bool
    total_steps: int
    completed_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[str] = field(default_factory=list)
    skipped_nodes: list[str] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    total_cost: float = 0.0


class GraphExecutor:
    """Executes a TrajectoryGraph using superstep model."""

    def __init__(
        self,
        graph: TrajectoryGraph,
        execute_fn: Callable[[TrajNode], Any] | None = None,
        on_step: Callable[[StepResult], None] | None = None,
        max_retries: int = 2,
    ) -> None:
        """Initialize GraphExecutor."""
        self.graph = graph
        self.execute_fn = execute_fn
        self.on_step = on_step
        self.max_retries = max_retries
        self._step_count = 0

    def step(self) -> StepResult:
        """Execute one superstep."""
        self._step_count += 1
        result = StepResult(step_number=self._step_count)

        ready = self.graph.get_ready_nodes()
        if not ready:
            result.is_terminal = True
            return result

        for node in ready:
            node.state = NodeState.RUNNING
            result.executed.append(node.node_id)

            if self.execute_fn is not None:
                try:
                    res = self.execute_fn(node)
                    node.state = NodeState.COMPLETED
                    node.result = res
                    result.completed.append(node.node_id)
                except Exception as exc:
                    self._handle_failure(node, str(exc))
                    if node.state == NodeState.FAILED:
                        result.failed.append(node.node_id)
            else:
                node.state = NodeState.COMPLETED
                result.completed.append(node.node_id)

        # Evaluate backtrack edges for failed nodes.
        backtracked = self._evaluate_all_backtracks()
        result.backtracked = backtracked

        # Check if terminal.
        terminal_ids = self.graph.terminal_nodes
        if terminal_ids:
            all_done = all(
                self.graph.get_node(tid) is not None
                and self.graph.get_node(tid).state  # type: ignore[union-attr]
                in (NodeState.COMPLETED, NodeState.SKIPPED, NodeState.FAILED)
                for tid in terminal_ids
            )
            result.is_terminal = all_done
        else:
            all_done = all(
                n.state in (NodeState.COMPLETED, NodeState.SKIPPED, NodeState.FAILED)
                for n in self.graph._nodes.values()
            )
            result.is_terminal = all_done

        if self.on_step:
            self.on_step(result)

        return result

    def run(self, max_steps: int = 100) -> ExecutionResult:
        """Run to completion or max steps."""
        for _ in range(max_steps):
            step_result = self.step()
            if step_result.is_terminal:
                break
            if not step_result.executed:
                break

        completed = [
            n.node_id for n in self.graph._nodes.values()
            if n.state == NodeState.COMPLETED
        ]
        failed = [
            n.node_id for n in self.graph._nodes.values()
            if n.state == NodeState.FAILED
        ]
        skipped = [
            n.node_id for n in self.graph._nodes.values()
            if n.state == NodeState.SKIPPED
        ]
        total_cost = sum(
            n.cost_estimate for n in self.graph._nodes.values()
            if n.state == NodeState.COMPLETED
        )

        success = len(failed) == 0 and len(completed) > 0

        try:
            critical_path = self.graph.get_critical_path()
        except Exception:
            critical_path = []

        return ExecutionResult(
            success=success,
            total_steps=self._step_count,
            completed_nodes=completed,
            failed_nodes=failed,
            skipped_nodes=skipped,
            critical_path=critical_path,
            total_cost=total_cost,
        )

    def _handle_failure(self, node: TrajNode, error: str) -> None:
        """Handle node failure: retry or prune dependents."""
        node.failure_reason = error
        if node.retry_count < node.max_retries:
            node.retry_count += 1
            node.state = NodeState.PENDING
            node.failure_reason = None
        else:
            node.state = NodeState.FAILED
            # Prune dependents.
            self.graph.prune_node(node.node_id, reason=f"failed: {error}")
            # Re-set this node to FAILED (prune_node sets SKIPPED).
            node.state = NodeState.FAILED
            node.failure_reason = error

    def _evaluate_backtrack(self, node_id: str) -> list[str]:
        """Check if any backtrack edges should trigger."""
        triggered: list[str] = []
        node = self.graph.get_node(node_id)
        if node is None or node.state != NodeState.FAILED:
            return triggered

        state = self.graph._build_graph_state()
        for e in self.graph.get_outgoing(node_id):
            if e.edge_type == EdgeType.BACKTRACK:
                target = self.graph.get_node(e.target)
                if target and target.retry_count < target.max_retries:
                    should_trigger = True
                    if e.condition is not None:
                        should_trigger = e.condition(state)
                    if should_trigger:
                        target.state = NodeState.PENDING
                        target.retry_count += 1
                        triggered.append(e.target)
        return triggered

    def _evaluate_all_backtracks(self) -> list[str]:
        """Evaluate backtrack edges for all failed nodes."""
        all_triggered: list[str] = []
        for node in self.graph._nodes.values():
            if node.state == NodeState.FAILED:
                triggered = self._evaluate_backtrack(node.node_id)
                all_triggered.extend(triggered)
        return all_triggered
