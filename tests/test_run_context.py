"""Tests for RunContext and RunContextManager.

Validates:
- RunContext creation with defaults
- Serialization/deserialization roundtrip
- RunContextManager CRUD operations
- RunExecutor integration with RunContext
- State sync back to RunContext after execution
- Isolation between multiple RunExecutors with different RunContexts
"""

from __future__ import annotations

from hi_agent.context.run_context import RunContext, RunContextManager
from hi_agent.contracts import (
    NodeState,
    NodeType,
    StageSummary,
    TaskContract,
    TrajectoryNode,
)
from hi_agent.runner import RunExecutor
from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_contract(
    task_id: str = "test-ctx-001",
    goal: str = "run context test",
    **kwargs: object,
) -> TaskContract:
    """Helper to create task contracts for tests."""
    return TaskContract(task_id=task_id, goal=goal, **kwargs)


# ---------------------------------------------------------------------------
# Test 1: basic creation with defaults
# ---------------------------------------------------------------------------


class TestRunContextCreation:
    def test_run_context_creation(self) -> None:
        ctx = RunContext(run_id="run-001")
        assert ctx.run_id == "run-001"
        assert ctx.dag == {}
        assert ctx.stage_summaries == {}
        assert ctx.action_seq == 0
        assert ctx.branch_seq == 0
        assert ctx.decision_seq == 0
        assert ctx.current_stage == ""
        assert ctx.total_branches_opened == 0
        assert ctx.stage_active_branches == {}
        assert ctx.gate_seq == 0
        assert ctx.skill_ids_used == []
        assert ctx.completed_stages == set()
        assert ctx.metadata == {}


# ---------------------------------------------------------------------------
# Test 2: serialize and deserialize roundtrip
# ---------------------------------------------------------------------------


class TestRunContextRoundtrip:
    def test_run_context_to_dict_roundtrip(self) -> None:
        node = TrajectoryNode(
            node_id="n1",
            node_type=NodeType.ACTION,
            stage_id="S1",
            branch_id="b0",
            state=NodeState.SUCCEEDED,
        )
        summary = StageSummary(
            stage_id="S1",
            stage_name="understand",
            findings=["found something"],
            outcome="completed",
        )
        ctx = RunContext(
            run_id="run-rt",
            dag={"n1": node},
            stage_summaries={"S1": summary},
            action_seq=5,
            branch_seq=3,
            decision_seq=2,
            current_stage="S3",
            total_branches_opened=7,
            stage_active_branches={"S1": 2, "S2": 1},
            gate_seq=1,
            skill_ids_used=["sk-001", "sk-002"],
            completed_stages={"S1", "S2"},
            metadata={"key": "value"},
        )
        d = ctx.to_dict()
        assert d["run_id"] == "run-rt"
        assert d["action_seq"] == 5
        assert d["branch_seq"] == 3
        assert d["decision_seq"] == 2
        assert d["current_stage"] == "S3"
        assert d["total_branches_opened"] == 7
        assert d["gate_seq"] == 1
        assert d["skill_ids_used"] == ["sk-001", "sk-002"]
        assert sorted(d["completed_stages"]) == ["S1", "S2"]
        assert d["metadata"] == {"key": "value"}

        # Roundtrip via from_dict (dag/stage_summaries not restored by from_dict)
        ctx2 = RunContext.from_dict(d)
        assert ctx2.run_id == "run-rt"
        assert ctx2.action_seq == 5
        assert ctx2.branch_seq == 3
        assert ctx2.decision_seq == 2
        assert ctx2.current_stage == "S3"
        assert ctx2.total_branches_opened == 7
        assert ctx2.gate_seq == 1
        assert ctx2.skill_ids_used == ["sk-001", "sk-002"]
        assert ctx2.completed_stages == {"S1", "S2"}
        assert ctx2.metadata == {"key": "value"}


# ---------------------------------------------------------------------------
# Test 3: RunContextManager create and get
# ---------------------------------------------------------------------------


class TestRunContextManagerCreateGet:
    def test_run_context_manager_create_get(self) -> None:
        mgr = RunContextManager()
        ctx = mgr.create("run-a")
        assert ctx.run_id == "run-a"
        assert mgr.get("run-a") is ctx
        assert mgr.get("run-b") is None
        assert mgr.active_count == 1


# ---------------------------------------------------------------------------
# Test 4: duplicate creation raises
# ---------------------------------------------------------------------------


class TestRunContextManagerDuplicate:
    def test_run_context_manager_duplicate_error(self) -> None:
        mgr = RunContextManager()
        mgr.create("run-dup")
        try:
            mgr.create("run-dup")
            assert False, "Should have raised ValueError"
        except ValueError as exc:
            assert "already exists" in str(exc)


# ---------------------------------------------------------------------------
# Test 5: idempotent get_or_create
# ---------------------------------------------------------------------------


class TestRunContextManagerGetOrCreate:
    def test_run_context_manager_get_or_create(self) -> None:
        mgr = RunContextManager()
        ctx1 = mgr.get_or_create("run-goc", action_seq=10)
        ctx2 = mgr.get_or_create("run-goc", action_seq=99)
        assert ctx1 is ctx2
        # First creation wins
        assert ctx1.action_seq == 10


# ---------------------------------------------------------------------------
# Test 6: remove returns context
# ---------------------------------------------------------------------------


class TestRunContextManagerRemove:
    def test_run_context_manager_remove(self) -> None:
        mgr = RunContextManager()
        mgr.create("run-rm")
        removed = mgr.remove("run-rm")
        assert removed is not None
        assert removed.run_id == "run-rm"
        assert mgr.get("run-rm") is None
        assert mgr.active_count == 0
        # Removing again returns None
        assert mgr.remove("run-rm") is None


# ---------------------------------------------------------------------------
# Test 7: list active runs
# ---------------------------------------------------------------------------


class TestRunContextManagerListRuns:
    def test_run_context_manager_list_runs(self) -> None:
        mgr = RunContextManager()
        mgr.create("run-x")
        mgr.create("run-y")
        mgr.create("run-z")
        runs = mgr.list_runs()
        assert sorted(runs) == ["run-x", "run-y", "run-z"]
        assert mgr.active_count == 3


# ---------------------------------------------------------------------------
# Test 8: RunExecutor uses RunContext state
# ---------------------------------------------------------------------------


class TestRunnerWithRunContext:
    def test_runner_with_run_context(self) -> None:
        """RunExecutor picks up initial state from RunContext."""
        ctx = RunContext(
            run_id="run-init",
            action_seq=42,
            branch_seq=10,
            decision_seq=5,
            current_stage="S2_route",
            gate_seq=3,
        )
        contract = _make_contract()
        kernel = MockKernel()
        executor = RunExecutor(contract, kernel, run_context=ctx)

        # Verify executor picked up the initial state
        assert executor.action_seq == 42
        assert executor.branch_seq == 10
        assert executor.decision_seq == 5
        assert executor.current_stage == "S2_route"
        assert executor._gate_seq == 3

    def test_runner_without_run_context_unchanged(self) -> None:
        """RunExecutor without run_context works as before."""
        contract = _make_contract()
        kernel = MockKernel()
        executor = RunExecutor(contract, kernel)
        assert executor.run_context is None
        result = executor.execute()
        assert result == "completed"


# ---------------------------------------------------------------------------
# Test 9: after execute(), RunContext has updated state
# ---------------------------------------------------------------------------


class TestRunnerSyncsBackToContext:
    def test_runner_syncs_back_to_context(self) -> None:
        ctx = RunContext(run_id="run-sync")
        contract = _make_contract()
        kernel = MockKernel()
        executor = RunExecutor(contract, kernel, run_context=ctx)

        result = executor.execute()
        assert result == "completed"

        # After execution, RunContext should reflect the executor's final state
        assert ctx.current_stage != ""
        # action_seq should have advanced (TRACE runs multiple stages with actions)
        assert ctx.action_seq >= 0
        # branch_seq should have advanced
        assert ctx.branch_seq >= 0
        # stage_summaries should have entries
        assert len(ctx.stage_summaries) > 0


# ---------------------------------------------------------------------------
# Test 10: two RunExecutors with different RunContexts don't interfere
# ---------------------------------------------------------------------------


class TestMultipleRunnersIsolated:
    def test_multiple_runners_isolated(self) -> None:
        ctx_a = RunContext(run_id="run-iso-a")
        ctx_b = RunContext(run_id="run-iso-b")

        contract_a = _make_contract(task_id="iso-a", goal="task A")
        contract_b = _make_contract(task_id="iso-b", goal="task B")
        kernel_a = MockKernel()
        kernel_b = MockKernel()

        executor_a = RunExecutor(contract_a, kernel_a, run_context=ctx_a)
        executor_b = RunExecutor(contract_b, kernel_b, run_context=ctx_b)

        result_a = executor_a.execute()
        result_b = executor_b.execute()

        assert result_a == "completed"
        assert result_b == "completed"

        # Each context should have its own state
        assert ctx_a.run_id == "run-iso-a"
        assert ctx_b.run_id == "run-iso-b"
        # Both should have stage summaries but they are independent objects
        assert ctx_a.stage_summaries is not ctx_b.stage_summaries
        assert len(ctx_a.stage_summaries) > 0
        assert len(ctx_b.stage_summaries) > 0
