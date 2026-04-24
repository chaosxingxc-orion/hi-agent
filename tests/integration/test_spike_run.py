"""Spike 1: verify Run S1->S5 completes with greedy optimizer."""

import pytest
from hi_agent.contracts import StageState, TaskContract
from hi_agent.runner import STAGES, RunExecutor

from tests.helpers.kernel_adapter_fixture import IllegalStateTransition, MockKernel


def test_run_s1_to_s5_completes() -> None:
    """A quick_task run should complete all S1->S5 stages."""
    contract = TaskContract(task_id="test-001", goal="spike test", task_family="quick_task")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel)

    result = executor.execute()

    assert result == "completed"


def test_all_stages_reach_completed() -> None:
    """Each stage should end in COMPLETED after successful execution."""
    contract = TaskContract(task_id="test-002", goal="stage check")
    kernel = MockKernel(strict_mode=True)

    RunExecutor(contract, kernel).execute()

    for stage_id in STAGES:
        kernel.assert_stage_state(stage_id, StageState.COMPLETED)


def test_trajectory_nodes_created() -> None:
    """The spike flow should create one trajectory node per stage."""
    contract = TaskContract(task_id="test-003", goal="node check")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel)

    executor.execute()

    assert len(executor.dag) == 5


def test_action_ids_are_deterministic() -> None:
    """Replaying the same contract should produce identical node IDs."""
    contract = TaskContract(task_id="test-004", goal="determinism check")
    first_executor = RunExecutor(contract, MockKernel())
    second_executor = RunExecutor(contract, MockKernel())

    first_executor.execute()
    second_executor.execute()

    assert list(first_executor.dag.keys()) == list(second_executor.dag.keys())


def test_illegal_stage_transition_rejected() -> None:
    """Strict mode should reject illegal stage transitions."""
    kernel = MockKernel(strict_mode=True)
    kernel.open_stage("run-1", "s1")

    with pytest.raises(IllegalStateTransition):
        kernel.mark_stage_state("run-1", "s1", StageState.COMPLETED)
