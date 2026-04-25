"""Integration tests for run state snapshot persistence."""

from hi_agent.contracts import CTSExplorationBudget, StageState, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.state import RunStateStore

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_run_state_snapshot_persisted_on_completed(tmp_path) -> None:
    """Runner should persist final snapshot for completed runs."""
    contract = TaskContract(task_id="int-state-001", goal="persist completed state")
    kernel = MockKernel(strict_mode=True)
    store = RunStateStore(file_path=tmp_path / "run_state.json")
    executor = RunExecutor(
        contract,
        kernel,
        state_store=store,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

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
    executor = RunExecutor(
        contract,
        kernel,
        state_store=store,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

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
