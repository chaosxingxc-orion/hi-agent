"""Spike 3: verify dead-end detection behavior."""

from hi_agent.contracts import NodeState, NodeType, TrajectoryNode
from hi_agent.trajectory.dead_end import detect_dead_end


def test_no_dead_end_when_branch_succeeded() -> None:
    """A stage is not dead-end if any branch succeeded."""
    dag = {
        "n1": TrajectoryNode("n1", NodeType.ACTION, "S3", "b1", state=NodeState.SUCCEEDED),
        "n2": TrajectoryNode("n2", NodeType.ACTION, "S3", "b2", state=NodeState.FAILED),
    }

    assert detect_dead_end("S3", dag) is False


def test_dead_end_when_all_failed() -> None:
    """A stage is dead-end when all nodes are terminal and none succeeded."""
    dag = {
        "n1": TrajectoryNode("n1", NodeType.ACTION, "S3", "b1", state=NodeState.FAILED),
        "n2": TrajectoryNode("n2", NodeType.ACTION, "S3", "b2", state=NodeState.PRUNED),
    }

    assert detect_dead_end("S3", dag) is True


def test_no_dead_end_when_open_nodes_exist() -> None:
    """A stage is not dead-end while open work remains."""
    dag = {
        "n1": TrajectoryNode("n1", NodeType.ACTION, "S3", "b1", state=NodeState.FAILED),
        "n2": TrajectoryNode("n2", NodeType.ACTION, "S3", "b2", state=NodeState.OPEN),
    }

    assert detect_dead_end("S3", dag) is False
