"""Dead-end detection for trajectory stages."""

from __future__ import annotations

from hi_agent.contracts import NodeState, TrajectoryNode


def detect_dead_end(stage_id: str, dag: dict[str, TrajectoryNode]) -> bool:
    """Determine whether a stage reaches dead-end.

    A stage is dead-end when all its nodes are terminal, and none succeeded.

    Args:
      stage_id: Stage identifier to inspect.
      dag: Full trajectory DAG.

    Returns:
      True if stage is dead-end, otherwise False.
    """
    stage_nodes = [node for node in dag.values() if node.stage_id == stage_id]
    if not stage_nodes:
        return False

    terminal_states = {NodeState.PRUNED, NodeState.FAILED, NodeState.SUCCEEDED}
    all_terminal = all(node.state in terminal_states for node in stage_nodes)
    any_succeeded = any(node.state == NodeState.SUCCEEDED for node in stage_nodes)
    return all_terminal and not any_succeeded

