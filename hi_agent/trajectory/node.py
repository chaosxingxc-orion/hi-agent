"""Trajectory DAG helper utilities."""

from __future__ import annotations

from hi_agent.contracts import TrajectoryNode


def link_parent_child(
    dag: dict[str, TrajectoryNode],
    *,
    parent_id: str,
    child_id: str,
) -> None:
    """Create parent-child relationship in DAG.

    Args:
      dag: Node dictionary keyed by node ID.
      parent_id: Parent node ID.
      child_id: Child node ID.
    """
    parent = dag[parent_id]
    child = dag[child_id]
    if child_id not in parent.children_ids:
        parent.children_ids.append(child_id)
    if parent_id not in child.parent_ids:
        child.parent_ids.append(parent_id)
