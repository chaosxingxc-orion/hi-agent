"""Greedy trajectory optimizer implementation."""

from __future__ import annotations

from hi_agent.contracts import NodeState, TrajectoryNode
from hi_agent.trajectory.backpropagation import greedy_backpropagate


class GreedyOptimizer:
    """Single-path greedy optimizer."""

    def select_next(
        self,
        current: TrajectoryNode,
        children: list[TrajectoryNode],
    ) -> TrajectoryNode | None:
        """Select best child by propagated score among expandable nodes."""
        _ = current
        expandable = [
            child for child in children if child.state in (NodeState.OPEN, NodeState.EXPANDED)
        ]
        if not expandable:
            return None
        return max(expandable, key=lambda node: node.propagated_score)

    def backpropagate(
        self,
        leaf: TrajectoryNode,
        dag: dict[str, TrajectoryNode],
        decay: float = 0.9,
    ) -> None:
        """Backpropagate quality signal from leaf."""
        greedy_backpropagate(leaf=leaf, dag=dag, decay=decay)
