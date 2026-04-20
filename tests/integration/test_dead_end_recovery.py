"""Integration test for dead-end detection behavior."""

from hi_agent.contracts import NodeState, NodeType, TaskContract, TrajectoryNode
from hi_agent.runner import RunExecutor
from hi_agent.trajectory.dead_end import detect_dead_end

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_detect_dead_end_and_no_dead_end_in_successful_run() -> None:
    """Dead-end should be detected for failed branches, not for successful run."""
    failed_stage_dag = {
        "n1": TrajectoryNode("n1", NodeType.ACTION, "S3_build", "b1", state=NodeState.FAILED),
        "n2": TrajectoryNode("n2", NodeType.ACTION, "S3_build", "b2", state=NodeState.PRUNED),
    }
    assert detect_dead_end("S3_build", failed_stage_dag) is True

    executor = RunExecutor(TaskContract(task_id="int-002", goal="dead-end"), MockKernel())
    executor.execute()
    assert detect_dead_end("S3_build", executor.dag) is False

