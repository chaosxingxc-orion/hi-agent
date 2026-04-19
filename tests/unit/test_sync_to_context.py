"""Unit tests for _sync_to_context() mutable field copying.

C-5: _sync_to_context() must use copy.copy() for mutable fields
to prevent unintended shared state mutations.
"""

from __future__ import annotations

import pytest

from hi_agent.contracts import TaskContract
from hi_agent.context.run_context import RunContext
from hi_agent.runner import RunExecutor
from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_executor_with_context() -> RunExecutor:
    """Create a RunExecutor with an attached RunContext."""
    contract = TaskContract(task_id="t-001", goal="test goal")
    kernel = MockKernel()
    run_context = RunContext(run_id="run-001")
    executor = RunExecutor(contract=contract, kernel=kernel, run_context=run_context)
    return executor


class TestSyncToContextMutableCopies:
    """Verify _sync_to_context() creates shallow copies of mutable fields."""

    def test_action_seq_scalar_not_copied(self):
        """action_seq is int (scalar); no copy needed."""
        executor = _make_executor_with_context()
        executor.action_seq = 42
        executor._sync_to_context()
        assert executor.run_context.action_seq == 42

    def test_branch_seq_scalar_not_copied(self):
        """branch_seq is int (scalar); no copy needed."""
        executor = _make_executor_with_context()
        executor.branch_seq = 5
        executor._sync_to_context()
        assert executor.run_context.branch_seq == 5

    def test_decision_seq_scalar_not_copied(self):
        """decision_seq is int (scalar); no copy needed."""
        executor = _make_executor_with_context()
        executor.decision_seq = 3
        executor._sync_to_context()
        assert executor.run_context.decision_seq == 3

    def test_current_stage_scalar_not_copied(self):
        """current_stage is str (scalar); no copy needed."""
        executor = _make_executor_with_context()
        executor.current_stage = "stage_1"
        executor._sync_to_context()
        assert executor.run_context.current_stage == "stage_1"

    def test_gate_seq_scalar_not_copied(self):
        """gate_seq is int (scalar); no copy needed."""
        executor = _make_executor_with_context()
        executor._gate_seq = 7
        executor._sync_to_context()
        assert executor.run_context.gate_seq == 7

    def test_dag_dict_is_copied(self):
        """dag dict is shallow copied; mutation does not affect run_context."""
        executor = _make_executor_with_context()
        executor.dag = {"node1": "value1"}
        executor._sync_to_context()

        # Mutate the executor's dag
        executor.dag["node2"] = "value2"

        # run_context.dag should not have node2
        assert "node2" not in executor.run_context.dag
        assert executor.run_context.dag == {"node1": "value1"}

    def test_stage_summaries_dict_is_copied(self):
        """stage_summaries dict is shallow copied; mutation does not affect run_context."""
        executor = _make_executor_with_context()
        executor.stage_summaries = {"s1": "summary1"}
        executor._sync_to_context()

        # Mutate the executor's stage_summaries
        executor.stage_summaries["s2"] = "summary2"

        # run_context.stage_summaries should not have s2
        assert "s2" not in executor.run_context.stage_summaries
        assert executor.run_context.stage_summaries == {"s1": "summary1"}

    def test_stage_active_branches_dict_is_copied(self):
        """stage_active_branches dict is shallow copied; mutation does not affect run_context."""
        executor = _make_executor_with_context()
        executor._stage_active_branches = {"stage1": 1}
        executor._sync_to_context()

        # Mutate the executor's _stage_active_branches
        executor._stage_active_branches["stage2"] = 2

        # run_context.stage_active_branches should not have stage2
        assert "stage2" not in executor.run_context.stage_active_branches
        assert executor.run_context.stage_active_branches == {"stage1": 1}

    def test_skill_ids_used_list_is_copied(self):
        """skill_ids_used list is shallow copied; mutation does not affect run_context."""
        executor = _make_executor_with_context()
        executor._skill_ids_used = ["skill1"]
        executor._sync_to_context()

        # Mutate the executor's _skill_ids_used
        executor._skill_ids_used.append("skill2")

        # run_context.skill_ids_used should not have skill2
        assert "skill2" not in executor.run_context.skill_ids_used
        assert executor.run_context.skill_ids_used == ["skill1"]

    def test_sync_to_context_no_context_returns_early(self):
        """If run_context is None, _sync_to_context() returns early without error."""
        contract = TaskContract(task_id="t-001", goal="test goal")
        kernel = MockKernel()
        executor = RunExecutor(contract=contract, kernel=kernel, run_context=None)
        executor.dag = {"node": "value"}
        # Should not raise
        executor._sync_to_context()

    def test_multiple_syncs_independent_copies(self):
        """Multiple _sync_to_context() calls produce independent copies."""
        executor = _make_executor_with_context()
        executor._skill_ids_used = ["skill1"]
        executor._sync_to_context()

        first_copy = executor.run_context.skill_ids_used
        executor._skill_ids_used.append("skill2")
        executor._sync_to_context()

        # first_copy should not be affected by the second sync
        assert first_copy == ["skill1"]
        assert executor.run_context.skill_ids_used == ["skill1", "skill2"]
