"""Backpropagation utilities for trajectory scoring."""

from __future__ import annotations

from hi_agent.contracts import NodeState, TrajectoryNode


def greedy_backpropagate(
    leaf: TrajectoryNode,
    dag: dict[str, TrajectoryNode],
    decay: float = 0.9,
) -> None:
    """Backpropagate over single-parent chain.

    Args:
      leaf: Recently evaluated node.
      dag: Full DAG dictionary.
      decay: Score decay per step.
    """
    leaf.visit_count += 1
    current_id = leaf.node_id
    while True:
        node = dag[current_id]
        if not node.parent_ids:
            break
        parent_id = node.parent_ids[0]
        parent = dag[parent_id]
        active_children = [
            dag[child_id]
            for child_id in parent.children_ids
            if dag[child_id].state != NodeState.PRUNED
        ]
        if active_children:
            total = sum(child.propagated_score for child in active_children)
            parent.propagated_score = decay * (total / len(active_children))
        parent.visit_count += 1
        current_id = parent_id
