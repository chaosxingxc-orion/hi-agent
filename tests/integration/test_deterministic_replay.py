"""Integration test for deterministic replay."""

from hi_agent.contracts import TaskContract
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_same_contract_replay_produces_stable_ids_and_summaries() -> None:
    """Executing same contract twice should produce stable deterministic output."""
    contract = TaskContract(task_id="int-003", goal="deterministic replay")

    first = RunExecutor(contract, MockKernel())
    second = RunExecutor(contract, MockKernel())
    first.execute()
    second.execute()

    assert first.run_id == second.run_id
    assert list(first.dag.keys()) == list(second.dag.keys())
    assert list(first.stage_summaries.keys()) == list(second.stage_summaries.keys())

