"""Integration tests for runner capability/event/memory pipeline."""

from hi_agent.contracts import StageState, TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import RunExecutor
from hi_agent.trajectory.stage_graph import StageGraph

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_runner_fails_on_forced_action_failure() -> None:
    """Runner should fail fast when configured action is forced to fail."""
    contract = TaskContract(
        task_id="int-pipe-001",
        goal="failure path",
        constraints=["fail_action:build_draft"],
    )
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

    result = executor.execute()

    assert result == "failed"
    kernel.assert_stage_state("S3_build", StageState.FAILED)


def test_runner_records_task_view_and_memory_artifacts() -> None:
    """Runner should emit task-view artifacts and compressed stage summaries."""
    contract = TaskContract(task_id="int-pipe-002", goal="artifact path")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

    result = executor.execute()

    assert result == "completed"
    assert len(kernel.task_views) == 5
    assert any(event.event_type == "TaskViewRecorded" for event in executor.event_emitter.events)
    assert executor.stage_summaries["S5_review"].outcome == "succeeded"


def test_runner_custom_stage_graph_controls_execution_path() -> None:
    """Runner should execute only the stages reachable in custom graph order."""
    graph = StageGraph()
    graph.add_edge("S1_understand", "S3_build")
    graph.add_edge("S3_build", "S5_review")

    contract = TaskContract(task_id="int-pipe-003", goal="custom graph path")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, stage_graph=graph, raw_memory=RawMemoryStore())

    result = executor.execute()

    assert result == "completed"
    assert [event["stage_id"] for event in kernel.get_events_of_type("StageOpened")] == [
        "S1_understand",
        "S3_build",
        "S5_review",
    ]
    assert "S2_gather" not in kernel.stages
    assert len(kernel.task_views) == 3
