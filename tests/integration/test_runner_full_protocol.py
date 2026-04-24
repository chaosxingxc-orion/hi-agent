"""Tests for runner.py full RuntimeAdapter protocol integration (EP-1.2).

Validates that RunExecutor uses the complete 17-method protocol surface
including start_run, open_branch, mark_branch_state, bind_task_view_to_decision,
and signal_run.
"""

from __future__ import annotations

from hi_agent.contracts import StageState, TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import STAGES, RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_contract(
    task_id: str = "test-fp-001",
    goal: str = "full protocol test",
    **kwargs: object,
) -> TaskContract:
    """Helper to create task contracts for tests."""
    return TaskContract(task_id=task_id, goal=goal, **kwargs)


class TestStartRun:
    """start_run is called at the beginning of execute()."""

    def test_start_run_called(self) -> None:
        """Kernel should have exactly one run after execute."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        assert len(kernel.runs) == 1

    def test_run_id_comes_from_kernel(self) -> None:
        """Run ID should be the kernel-assigned value."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        assert executor.run_id == "run-0001"

    def test_start_run_event_recorded(self) -> None:
        """RunStarted event should be emitted with correct task_id."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        run_started = kernel.get_events_of_type("RunStarted")
        assert len(run_started) == 1
        assert run_started[0]["task_id"] == "test-fp-001"


class TestRunStateTransitions:
    """Validate run state transitions CREATED->ACTIVE->COMPLETED."""

    def test_run_status_is_running_during_execute(self) -> None:
        """After start_run, MockKernel sets status to running."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        run = kernel.query_run(executor.run_id)
        assert run["status"] == "running"

    def test_run_exists_after_execute(self) -> None:
        """Run should exist in kernel after successful execution."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "completed"
        assert executor.run_id in kernel.runs


class TestBranchLifecycle:
    """Branches are opened and marked through their lifecycle."""

    def test_branches_created_per_stage(self) -> None:
        """Default route engine creates 1 branch per stage, 5 total."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        assert len(kernel.branches) == 5

    def test_branch_opened_events(self) -> None:
        """BranchOpened event should be emitted for each branch."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        opened = kernel.get_events_of_type("BranchOpened")
        assert len(opened) == 5

    def test_all_branches_succeed(self) -> None:
        """All branches should reach succeeded state on a clean run."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        for branch_data in kernel.branches.values():
            assert branch_data["state"] == "succeeded"

    def test_branch_state_transitions(self) -> None:
        """Each branch goes proposed -> active -> succeeded."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        state_changes = kernel.get_events_of_type("BranchStateChanged")
        # Each branch: proposed->active, active->succeeded = 2 transitions
        assert len(state_changes) == 10  # 5 branches * 2 transitions

    def test_branch_id_format(self) -> None:
        """Branch IDs are deterministic hash strings from proposal.branch_id.

        After D3 fix, branch_id is taken from proposal.branch_id (a
        deterministic hash) rather than the counter-based _make_branch_id().
        We verify that IDs are non-empty strings; they no longer contain the
        old ':b' counter marker.
        """
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        for key in kernel.branches:
            _run_id, _stage_id, branch_id = key
            assert branch_id, "branch_id must be a non-empty string"


class TestBranchFailure:
    """Branch failure triggers mark_branch_state(FAILED)."""

    def test_failed_action_marks_branch_failed(self) -> None:
        """Failed action should mark the branch as failed with failure_code."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract(
            constraints=["fail_action:analyze_goal"],
        )
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "failed"

        s1_branches = [(k, v) for k, v in kernel.branches.items() if k[1] == "S1_understand"]
        assert len(s1_branches) == 1
        _, branch_data = s1_branches[0]
        assert branch_data["state"] == "failed"
        assert branch_data["failure_code"] == "harness_denied"

    def test_branch_failed_event_emitted(self) -> None:
        """BranchFailed event should be emitted on action failure."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract(
            constraints=["fail_action:analyze_goal"],
        )
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        branch_failed = [e for e in executor.event_emitter.events if e.event_type == "BranchFailed"]
        assert len(branch_failed) >= 1


class TestTaskViewBinding:
    """Task views are bound to decision references."""

    def test_task_view_bound_to_decision(self) -> None:
        """Every task view should have a decision binding."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        assert len(kernel.task_view_decisions) == 5
        for tv_id, decision_ref in kernel.task_view_decisions.items():
            assert tv_id in kernel.task_views
            assert decision_ref  # non-empty

    def test_decision_ref_format(self) -> None:
        """Decision references should contain the :d marker."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        for decision_ref in kernel.task_view_decisions.values():
            assert ":d" in decision_ref

    def test_task_view_recorded_event_includes_decision_ref(self) -> None:
        """TaskViewRecorded events should contain decision_ref in payload."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        tv_events = [e for e in executor.event_emitter.events if e.event_type == "TaskViewRecorded"]
        assert len(tv_events) == 5
        for ev in tv_events:
            assert "decision_ref" in ev.payload


class TestFullS1ToS5WithBranches:
    """Integration test: full run with branch lifecycle."""

    def test_full_run_stages_and_branches(self) -> None:
        """Full run should complete all stages, branches, and bindings."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract(task_id="integration-001")
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "completed"

        for stage_id in STAGES:
            kernel.assert_stage_state(stage_id, StageState.COMPLETED)

        assert len(kernel.branches) == 5
        for branch_data in kernel.branches.values():
            assert branch_data["state"] == "succeeded"

        assert len(kernel.task_view_decisions) == 5
        assert executor.run_id in kernel.runs

    def test_event_ordering(self) -> None:
        """Key events should appear in expected order."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        event_types = [e["event_type"] for e in kernel.events]

        assert event_types[0] == "RunStarted"

        stage_opened_indices = [i for i, t in enumerate(event_types) if t == "StageOpened"]
        branch_opened_indices = [i for i, t in enumerate(event_types) if t == "BranchOpened"]
        assert len(stage_opened_indices) == 5
        assert len(branch_opened_indices) == 5
        for s_idx, b_idx in zip(stage_opened_indices, branch_opened_indices, strict=True):
            assert s_idx < b_idx


class TestMultipleBranchesPerStage:
    """Test runner with multiple branches per stage."""

    def test_two_branches_per_stage(self) -> None:
        """Custom route engine that proposes two branches per stage."""
        from hi_agent.contracts import deterministic_id
        from hi_agent.route_engine.base import BranchProposal

        class TwoBranchEngine:
            """Route engine producing two branches per stage."""

            def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
                """Return two branch proposals."""
                return [
                    BranchProposal(
                        branch_id=deterministic_id(run_id, stage_id, str(seq), "a"),
                        rationale=f"branch-a for {stage_id}",
                        action_kind="analyze_goal",
                    ),
                    BranchProposal(
                        branch_id=deterministic_id(run_id, stage_id, str(seq), "b"),
                        rationale=f"branch-b for {stage_id}",
                        action_kind="analyze_goal",
                    ),
                ]

        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(
            contract, kernel, route_engine=TwoBranchEngine(), raw_memory=RawMemoryStore()
        )

        result = executor.execute()

        assert result == "completed"
        # 5 stages * 2 branches each = 10 branches
        assert len(kernel.branches) == 10
        for branch_data in kernel.branches.values():
            assert branch_data["state"] == "succeeded"
        assert len(kernel.task_view_decisions) == 10


class TestSignalRunOnFailure:
    """signal_run is used for recovery signaling on failure."""

    def test_signal_run_on_dead_end(self) -> None:
        """signal_run should be called with recovery_failed on dead end."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract(
            constraints=["fail_action:analyze_goal"],
        )
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "failed"
        run = kernel.query_run(executor.run_id)
        signals = run["signals"]
        assert len(signals) >= 1
        assert signals[0]["signal"] == "recovery_failed"


class TestDeterministicIds:
    """Branch and decision IDs are deterministic across replays."""

    def test_replay_produces_same_branch_ids(self) -> None:
        """Replaying same contract produces identical branch IDs."""
        contract = _make_contract(task_id="replay-001")

        kernel1 = MockKernel(strict_mode=True)
        executor1 = RunExecutor(contract, kernel1, raw_memory=RawMemoryStore())
        executor1.execute()

        kernel2 = MockKernel(strict_mode=True)
        executor2 = RunExecutor(contract, kernel2, raw_memory=RawMemoryStore())
        executor2.execute()

        branches1 = sorted(kernel1.branches.keys())
        branches2 = sorted(kernel2.branches.keys())
        assert branches1 == branches2

    def test_replay_produces_same_decision_refs(self) -> None:
        """Replaying same contract produces identical decision refs."""
        contract = _make_contract(task_id="replay-002")

        kernel1 = MockKernel(strict_mode=True)
        executor1 = RunExecutor(contract, kernel1, raw_memory=RawMemoryStore())
        executor1.execute()

        kernel2 = MockKernel(strict_mode=True)
        executor2 = RunExecutor(contract, kernel2, raw_memory=RawMemoryStore())
        executor2.execute()

        decisions1 = sorted(kernel1.task_view_decisions.values())
        decisions2 = sorted(kernel2.task_view_decisions.values())
        assert decisions1 == decisions2
