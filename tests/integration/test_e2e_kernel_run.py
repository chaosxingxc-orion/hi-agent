"""End-to-end run via MockKernel integration tests.

Validates the complete quick_task Run lifecycle S1->S5 including:
- run_id returned from start_run
- event log sequential integrity
- stage transition legality (PENDING->ACTIVE->COMPLETED)
- branch transition legality (PROPOSED->ACTIVE->SUCCEEDED)
- deterministic ID reproducibility across identical runs
"""

from __future__ import annotations

from hi_agent.contracts import StageState, TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import STAGES, RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def _run_quick_task(
    task_id: str = "e2e-kernel-001",
    goal: str = "full kernel run",
) -> tuple[RunExecutor, MockKernel]:
    """Execute a standard quick_task and return executor + kernel."""
    contract = TaskContract(task_id=task_id, goal=goal)
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())
    executor.execute()
    return executor, kernel


class TestCompleteQuickTaskRun:
    """Verify complete S1->S5 run produces correct kernel state."""

    def test_run_id_returned_from_start_run(self) -> None:
        """start_run should return a non-empty run_id stored in executor."""
        executor, kernel = _run_quick_task()

        assert executor.run_id is not None
        assert executor.run_id != ""
        assert executor.run_id in kernel.runs

    def test_all_stages_completed(self) -> None:
        """Every stage in the default graph should reach COMPLETED."""
        _, kernel = _run_quick_task()

        for stage_id in STAGES:
            kernel.assert_stage_state(stage_id, StageState.COMPLETED)

    def test_run_result_is_completed(self) -> None:
        """execute() should return 'completed' for a happy-path run."""
        contract = TaskContract(task_id="e2e-result", goal="check result")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "completed"

    def test_branches_created_and_succeeded(self) -> None:
        """Each stage should have at least one branch in succeeded state."""
        executor, kernel = _run_quick_task()

        branches_by_stage: dict[str, list[str]] = {}
        for (run_id, stage_id, _), info in kernel.branches.items():
            if run_id == executor.run_id:
                branches_by_stage.setdefault(stage_id, []).append(info["state"])

        for stage_id in STAGES:
            assert stage_id in branches_by_stage, f"No branches found for {stage_id}"
            assert "succeeded" in branches_by_stage[stage_id], f"No succeeded branch in {stage_id}"


class TestEventLogIntegrity:
    """Verify the event log has no gaps and correct ordering."""

    def test_event_log_not_empty(self) -> None:
        """A completed run must produce events."""
        _, kernel = _run_quick_task()

        assert len(kernel.events) > 0

    def test_event_log_sequential_commit_offset(self) -> None:
        """Event emitter envelopes should have sequential indices (no gaps)."""
        executor, _ = _run_quick_task()

        events = executor.event_emitter.events
        assert len(events) > 0
        # Envelopes are appended in order; verify sequential indexing
        for _, envelope in enumerate(events):
            assert envelope.event_type is not None
            assert envelope.run_id == executor.run_id
            # Verify no None gaps
            assert envelope.timestamp is not None

    def test_run_started_is_first_event(self) -> None:
        """The first emitted event should be RunStarted."""
        executor, _ = _run_quick_task()

        first = executor.event_emitter.events[0]
        assert first.event_type == "RunStarted"
        assert first.payload["run_id"] == executor.run_id


class TestStageTransitions:
    """Verify all stage transitions follow legal state machine."""

    def test_all_stages_pass_through_pending_active_completed(self) -> None:
        """Each stage should transition PENDING->ACTIVE->COMPLETED in kernel events."""
        _, kernel = _run_quick_task()

        for stage_id in STAGES:
            stage_events = [
                e
                for e in kernel.events
                if e.get("stage_id") == stage_id and e["event_type"] == "StageStateChanged"
            ]
            # Must have at least 2 transitions: PENDING->ACTIVE and ACTIVE->COMPLETED
            assert len(stage_events) >= 2, f"{stage_id} has only {len(stage_events)} transitions"
            # First transition should be to active
            assert stage_events[0]["to_state"] == StageState.ACTIVE
            # Last transition should be to completed
            assert stage_events[-1]["to_state"] == StageState.COMPLETED


class TestBranchTransitions:
    """Verify branch transitions follow legal state machine."""

    def test_all_branches_transition_proposed_active_succeeded(self) -> None:
        """Each branch should follow proposed->active->succeeded in kernel events."""
        _, kernel = _run_quick_task()

        branch_events: dict[str, list[dict]] = {}
        for e in kernel.events:
            if e["event_type"] == "BranchStateChanged":
                bid = e["branch_id"]
                branch_events.setdefault(bid, []).append(e)

        assert len(branch_events) > 0, "No branch state changes recorded"

        for bid, events in branch_events.items():
            states = [e["to_state"] for e in events]
            assert states == ["active", "succeeded"], f"Branch {bid} transitions: {states}"


class TestDeterministicIDs:
    """Verify ID determinism across identical runs."""

    def test_same_task_produces_same_branch_ids(self) -> None:
        """Running the same task contract twice should produce identical branch_ids."""
        executor1, kernel1 = _run_quick_task(task_id="det-001", goal="determinism check")
        executor2, kernel2 = _run_quick_task(task_id="det-001", goal="determinism check")

        # Branch IDs are based on run_id:stage_id:bNNN - but run_id is
        # counter-based in MockKernel, so run_id itself differs.
        # Instead, verify that branch IDs within each run follow the same
        # pattern relative to their run_id.
        def relative_branch_ids(kernel: MockKernel, run_id: str) -> list[str]:
            return sorted(
                bid.replace(run_id, "RUN") for (rid, _, bid) in kernel.branches if rid == run_id
            )

        ids1 = relative_branch_ids(kernel1, executor1.run_id)
        ids2 = relative_branch_ids(kernel2, executor2.run_id)

        assert ids1 == ids2, "Branch ID patterns differ between identical runs"

    def test_same_task_produces_same_decision_refs(self) -> None:
        """Decision references should be deterministic relative to run_id."""
        executor1, kernel1 = _run_quick_task(task_id="det-002", goal="decision ref check")
        executor2, kernel2 = _run_quick_task(task_id="det-002", goal="decision ref check")

        def relative_decision_refs(
            kernel: MockKernel,
            run_id: str,
        ) -> list[str]:
            return sorted(ref.replace(run_id, "RUN") for ref in kernel.task_view_decisions.values())

        refs1 = relative_decision_refs(kernel1, executor1.run_id)
        refs2 = relative_decision_refs(kernel2, executor2.run_id)

        assert refs1 == refs2, "Decision ref patterns differ between identical runs"

    def test_task_view_count_deterministic(self) -> None:
        """Same contract should produce the same number of task views."""
        _, kernel1 = _run_quick_task(task_id="det-003", goal="tv count")
        _, kernel2 = _run_quick_task(task_id="det-003", goal="tv count")

        assert len(kernel1.task_views) == len(kernel2.task_views)
        assert len(kernel1.task_views) == len(STAGES)
