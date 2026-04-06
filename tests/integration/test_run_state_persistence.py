"""Integration tests for run state snapshot persistence."""

from hi_agent.contracts import StageState, TaskContract
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter.mock_kernel import MockKernel
from hi_agent.state import RunStateStore


def test_run_state_snapshot_persisted_on_completed(tmp_path) -> None:
    """Runner should persist final snapshot for completed runs."""
    contract = TaskContract(task_id="int-state-001", goal="persist completed state")
    kernel = MockKernel(strict_mode=True)
    store = RunStateStore(file_path=tmp_path / "run_state.json")
    executor = RunExecutor(contract, kernel, state_store=store)

    result = executor.execute()

    assert result == "completed"
    snapshot = store.get(executor.run_id)
    assert snapshot is not None
    assert snapshot.run_id == executor.run_id
    assert snapshot.current_stage == "S5_review"
    assert snapshot.stage_states["S5_review"] == StageState.COMPLETED.value
    assert snapshot.action_seq == 5
    assert snapshot.task_views_count == 5
    assert snapshot.result == "completed"

    restored = RunStateStore(file_path=tmp_path / "run_state.json").get(executor.run_id)
    assert restored is not None
    assert restored.result == "completed"


def test_run_state_snapshot_persisted_on_failed(tmp_path) -> None:
    """Runner should persist final snapshot for failed runs."""
    contract = TaskContract(
        task_id="int-state-002",
        goal="persist failed state",
        constraints=["fail_action:build_draft"],
    )
    kernel = MockKernel(strict_mode=True)
    store = RunStateStore(file_path=tmp_path / "run_state.json")
    executor = RunExecutor(contract, kernel, state_store=store)

    result = executor.execute()

    assert result == "failed"
    snapshot = store.get(executor.run_id)
    assert snapshot is not None
    assert snapshot.run_id == executor.run_id
    assert snapshot.current_stage == "S3_build"
    assert snapshot.stage_states["S3_build"] == StageState.FAILED.value
    assert snapshot.action_seq == 3
    assert snapshot.task_views_count == 2
    assert snapshot.result == "failed"

    restored = RunStateStore(file_path=tmp_path / "run_state.json").get(executor.run_id)
    assert restored is not None
    assert restored.result == "failed"
