"""Branch lifecycle integration tests.

Validates branch state machine transitions including:
- Happy path: open->active->succeeded
- Failure path: open->active->failed
- Dead-end detection trigger on all-failed branches
- Multiple branches per stage via custom route engine
- Pruning and trajectory state with mixed outcomes
"""

from __future__ import annotations

from typing import ClassVar

from hi_agent.contracts import (
    NodeState,
    StageState,
    TaskContract,
    deterministic_id,
)
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.base import BranchProposal
from hi_agent.runner import STAGES, RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


class _MultiBranchRouteEngine:
    """Route engine that proposes multiple branches per stage."""

    def __init__(self, branch_count: int = 2) -> None:
        self.branch_count = branch_count

    def propose(
        self,
        stage_id: str,
        run_id: str,
        seq: int,
    ) -> list[BranchProposal]:
        proposals = []
        for i in range(self.branch_count):
            branch_id = deterministic_id(run_id, stage_id, str(seq), str(i))
            proposals.append(
                BranchProposal(
                    branch_id=branch_id,
                    rationale=f"multi-branch-{i}",
                    action_kind="analyze_goal",
                )
            )
        return proposals


class _PartialFailRouteEngine:
    """Route engine with 3 branches: first two succeed, third fails."""

    STAGE_ACTIONS: ClassVar[dict[str, str]] = {
        "S1_understand": "analyze_goal",
        "S2_gather": "search_evidence",
        "S3_build": "build_draft",
        "S4_synthesize": "synthesize",
        "S5_review": "evaluate_acceptance",
    }

    def propose(
        self,
        stage_id: str,
        run_id: str,
        seq: int,
    ) -> list[BranchProposal]:
        action = self.STAGE_ACTIONS.get(stage_id, "analyze_goal")
        proposals = []
        for i in range(3):
            branch_id = deterministic_id(run_id, stage_id, str(seq), str(i))
            # Third branch uses a forced-fail action kind if configured
            kind = action if i < 2 else f"fail_{action}"
            proposals.append(
                BranchProposal(
                    branch_id=branch_id,
                    rationale=f"partial-{i}",
                    action_kind=kind,
                )
            )
        return proposals


class TestBranchHappyPath:
    """Branch open->active->succeeded lifecycle."""

    def test_branch_reaches_succeeded(self) -> None:
        """Standard run branches should all reach succeeded state."""
        contract = TaskContract(task_id="branch-happy-001", goal="branch happy path")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "completed"
        for key, info in kernel.branches.items():
            if key[0] == executor.run_id:
                assert info["state"] == "succeeded", f"Branch {key} in state {info['state']}"

    def test_branch_state_history_in_kernel_events(self) -> None:
        """Kernel events should record proposed->active->succeeded transitions."""
        contract = TaskContract(task_id="branch-happy-002", goal="branch events")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        for stage_id in STAGES:
            opened = [
                e
                for e in kernel.events
                if e["event_type"] == "BranchOpened" and e.get("stage_id") == stage_id
            ]
            assert len(opened) >= 1, f"No branch opened for {stage_id}"


class TestBranchFailurePath:
    """Branch open->active->failed lifecycle."""

    def test_branch_reaches_failed_on_action_failure(self) -> None:
        """Forced action failure should result in failed branch state."""
        contract = TaskContract(
            task_id="branch-fail-001",
            goal="branch failure",
            constraints=["fail_action:analyze_goal"],
        )
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "failed"
        # S1 branch should be in failed state
        s1_branches = [
            (key, info)
            for key, info in kernel.branches.items()
            if key[0] == executor.run_id and key[1] == "S1_understand"
        ]
        assert len(s1_branches) >= 1
        for _, info in s1_branches:
            assert info["state"] == "failed"
            assert info["failure_code"] is not None


class TestDeadEndDetection:
    """Dead-end detection triggers when all branches in a stage fail."""

    def test_dead_end_triggers_stage_failure(self) -> None:
        """All branches failing should cause dead-end and stage failure."""
        contract = TaskContract(
            task_id="dead-end-001",
            goal="dead-end trigger",
            constraints=["fail_action:build_draft"],
        )
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "failed"
        kernel.assert_stage_state("S3_build", StageState.FAILED)

        # The stage should have had recovery triggered (event recorded)
        recovery_events = [
            e for e in executor.event_emitter.events if e.event_type == "RecoveryTriggered"
        ]
        assert len(recovery_events) >= 1

    def test_dead_end_does_not_affect_earlier_stages(self) -> None:
        """Stages before the dead-end should remain completed."""
        contract = TaskContract(
            task_id="dead-end-002",
            goal="dead-end partial",
            constraints=["fail_action:build_draft"],
        )
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        kernel.assert_stage_state("S1_understand", StageState.COMPLETED)
        kernel.assert_stage_state("S2_gather", StageState.COMPLETED)
        kernel.assert_stage_state("S3_build", StageState.FAILED)


class TestMultipleBranchesPerStage:
    """Custom route engine returning multiple branch proposals."""

    def test_two_branches_per_stage(self) -> None:
        """Route engine producing 2 branches should create 2 branches per stage."""
        contract = TaskContract(task_id="multi-branch-001", goal="multi-branch")
        kernel = MockKernel(strict_mode=True)
        route_engine = _MultiBranchRouteEngine(branch_count=2)
        executor = RunExecutor(contract, kernel, route_engine=route_engine, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "completed"
        for stage_id in STAGES:
            stage_branches = [
                key for key in kernel.branches if key[0] == executor.run_id and key[1] == stage_id
            ]
            assert len(stage_branches) == 2, (
                f"{stage_id} has {len(stage_branches)} branches, expected 2"
            )

    def test_all_multi_branches_succeed(self) -> None:
        """All branches from multi-proposal should succeed in happy path."""
        contract = TaskContract(task_id="multi-branch-002", goal="multi-succeed")
        kernel = MockKernel(strict_mode=True)
        route_engine = _MultiBranchRouteEngine(branch_count=3)
        executor = RunExecutor(contract, kernel, route_engine=route_engine, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "completed"
        for key, info in kernel.branches.items():
            if key[0] == executor.run_id:
                assert info["state"] == "succeeded"


class TestBranchPruningAndTrajectoryState:
    """Verify trajectory state with mixed branch outcomes."""

    def test_two_succeed_one_fails_run_still_completes(self) -> None:
        """With 3 branches per stage, if 2 succeed the run still completes."""
        contract = TaskContract(
            task_id="prune-001",
            goal="pruning test",
            constraints=["fail_action:fail_analyze_goal"],
        )
        kernel = MockKernel(strict_mode=True)
        route_engine = _PartialFailRouteEngine()
        executor = RunExecutor(contract, kernel, route_engine=route_engine, raw_memory=RawMemoryStore())

        result = executor.execute()

        # Even though one branch per stage fails, the others succeed,
        # so dead-end is not triggered.
        assert result == "completed"

    def test_mixed_branch_states_in_kernel(self) -> None:
        """Kernel should record both succeeded and failed branch states."""
        contract = TaskContract(
            task_id="prune-002",
            goal="mixed states",
            constraints=["fail_action:fail_build_draft"],
        )
        kernel = MockKernel(strict_mode=True)
        route_engine = _PartialFailRouteEngine()
        executor = RunExecutor(contract, kernel, route_engine=route_engine, raw_memory=RawMemoryStore())

        executor.execute()

        s3_branches = [
            (key, info)
            for key, info in kernel.branches.items()
            if key[0] == executor.run_id and key[1] == "S3_build"
        ]
        states = {info["state"] for _, info in s3_branches}
        assert "succeeded" in states, "Expected at least one succeeded branch"
        assert "failed" in states, "Expected at least one failed branch"

    def test_trajectory_dag_records_node_states(self) -> None:
        """Executor DAG should contain nodes with correct terminal states."""
        contract = TaskContract(
            task_id="prune-003",
            goal="dag states",
            constraints=["fail_action:fail_synthesize"],
        )
        kernel = MockKernel(strict_mode=True)
        route_engine = _PartialFailRouteEngine()
        executor = RunExecutor(contract, kernel, route_engine=route_engine, raw_memory=RawMemoryStore())

        executor.execute()

        succeeded_count = sum(1 for n in executor.dag.values() if n.state == NodeState.SUCCEEDED)
        failed_count = sum(1 for n in executor.dag.values() if n.state == NodeState.FAILED)
        assert succeeded_count > 0
        assert failed_count > 0
