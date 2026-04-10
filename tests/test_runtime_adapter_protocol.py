"""Tests for the expanded RuntimeAdapter protocol and MockKernel (17 methods).

Covers:
- All 17 protocol methods on MockKernel
- RunState illegal transitions
- BranchState illegal transitions
- Idempotent operations
- Human Gate lifecycle (open -> approve/reject)
- Async stream_run_events
"""

from __future__ import annotations

import pytest

from hi_agent.contracts import BranchState, RunState, StageState
from hi_agent.contracts.requests import (
    ApprovalRequest,
    HumanGateRequest,
)
from hi_agent.runtime_adapter.errors import IllegalStateTransitionError
from hi_agent.runtime_adapter.mock_kernel import MockKernel
from hi_agent.runtime_adapter.protocol import RuntimeAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kernel() -> MockKernel:
    """Return a strict-mode MockKernel."""
    return MockKernel(strict_mode=True)


def _start_run(kernel: MockKernel, task_id: str = "task-1") -> str:
    """Start a run and return the run_id."""
    return kernel.start_run(task_id)


def _open_branch(
    kernel: MockKernel,
    run_id: str,
    stage_id: str = "S1",
    branch_id: str = "b-1",
) -> None:
    """Open a stage and a branch under it."""
    kernel.open_stage(stage_id)
    kernel.mark_stage_state(stage_id, StageState.ACTIVE)
    kernel.open_branch(run_id, stage_id, branch_id)


# ---------------------------------------------------------------------------
# Protocol structural checks
# ---------------------------------------------------------------------------


class TestProtocolSurface:
    """Verify the RuntimeAdapter protocol exposes all 17 methods."""

    EXPECTED_METHODS = [
        "open_stage",
        "mark_stage_state",
        "record_task_view",
        "bind_task_view_to_decision",
        "start_run",
        "query_run",
        "cancel_run",
        "resume_run",
        "signal_run",
        "query_trace_runtime",
        "stream_run_events",
        "open_branch",
        "mark_branch_state",
        "open_human_gate",
        "submit_approval",
        "get_manifest",
        "submit_plan",
    ]

    def test_protocol_has_all_17_methods(self) -> None:
        for method in self.EXPECTED_METHODS:
            assert hasattr(RuntimeAdapter, method), (
                f"RuntimeAdapter missing method: {method}"
            )

    def test_protocol_method_count(self) -> None:
        protocol_methods = [
            name
            for name in dir(RuntimeAdapter)
            if not name.startswith("_") and callable(getattr(RuntimeAdapter, name))
        ]
        assert len(protocol_methods) >= 17


# ---------------------------------------------------------------------------
# Stage lifecycle (methods 1-2)
# ---------------------------------------------------------------------------


class TestStageLifecycle:
    def test_open_stage(self) -> None:
        k = _make_kernel()
        k.open_stage("S1")
        assert k.stages["S1"] == StageState.PENDING

    def test_open_stage_idempotent(self) -> None:
        k = _make_kernel()
        k.open_stage("S1")
        k.open_stage("S1")
        assert len(k.get_events_of_type("StageOpened")) == 1

    def test_mark_stage_state_happy_path(self) -> None:
        k = _make_kernel()
        k.open_stage("S1")
        k.mark_stage_state("S1", StageState.ACTIVE)
        assert k.stages["S1"] == StageState.ACTIVE

    def test_mark_stage_state_idempotent(self) -> None:
        k = _make_kernel()
        k.open_stage("S1")
        k.mark_stage_state("S1", StageState.ACTIVE)
        k.mark_stage_state("S1", StageState.ACTIVE)
        assert len(k.get_events_of_type("StageStateChanged")) == 1

    def test_mark_stage_state_illegal_transition(self) -> None:
        k = _make_kernel()
        k.open_stage("S1")
        k.mark_stage_state("S1", StageState.ACTIVE)
        k.mark_stage_state("S1", StageState.COMPLETED)
        with pytest.raises(IllegalStateTransitionError):
            k.mark_stage_state("S1", StageState.ACTIVE)

    def test_mark_stage_not_opened(self) -> None:
        k = _make_kernel()
        with pytest.raises(ValueError, match="not opened"):
            k.mark_stage_state("S1", StageState.ACTIVE)


# ---------------------------------------------------------------------------
# Task view (methods 3-4)
# ---------------------------------------------------------------------------


class TestTaskView:
    def test_record_task_view(self) -> None:
        k = _make_kernel()
        result = k.record_task_view("tv-1", {"goal": "test"})
        assert result == "tv-1"
        assert k.task_views["tv-1"] == {"goal": "test"}

    def test_record_task_view_idempotent(self) -> None:
        k = _make_kernel()
        k.record_task_view("tv-1", {"goal": "test"})
        k.record_task_view("tv-1", {"goal": "different"})
        assert k.task_views["tv-1"] == {"goal": "test"}

    def test_bind_task_view_to_decision(self) -> None:
        k = _make_kernel()
        k.record_task_view("tv-1", {"goal": "test"})
        k.bind_task_view_to_decision("tv-1", "dec-1")
        assert k.task_view_decisions["tv-1"] == "dec-1"

    def test_bind_task_view_to_decision_idempotent(self) -> None:
        k = _make_kernel()
        k.record_task_view("tv-1", {"goal": "test"})
        k.bind_task_view_to_decision("tv-1", "dec-1")
        k.bind_task_view_to_decision("tv-1", "dec-1")  # same binding = no error
        assert k.task_view_decisions["tv-1"] == "dec-1"

    def test_bind_task_view_conflict(self) -> None:
        k = _make_kernel()
        k.record_task_view("tv-1", {"goal": "test"})
        k.bind_task_view_to_decision("tv-1", "dec-1")
        with pytest.raises(ValueError, match="already bound"):
            k.bind_task_view_to_decision("tv-1", "dec-2")

    def test_bind_task_view_not_found(self) -> None:
        k = _make_kernel()
        with pytest.raises(ValueError, match="not found"):
            k.bind_task_view_to_decision("missing", "dec-1")


# ---------------------------------------------------------------------------
# Run lifecycle (methods 5-9)
# ---------------------------------------------------------------------------


class TestRunLifecycle:
    def test_start_run(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        assert run_id.startswith("run-")
        assert k.runs[run_id]["status"] == "running"

    def test_query_run(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        snapshot = k.query_run(run_id)
        assert snapshot["run_id"] == run_id
        assert snapshot["status"] == "running"

    def test_query_run_not_found(self) -> None:
        k = _make_kernel()
        with pytest.raises(ValueError, match="not found"):
            k.query_run("nonexistent")

    def test_cancel_run(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.cancel_run(run_id, "user requested")
        assert k.runs[run_id]["status"] == "cancelled"
        assert k.runs[run_id]["cancel_reason"] == "user requested"

    def test_cancel_run_idempotent(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.cancel_run(run_id, "reason")
        k.cancel_run(run_id, "reason again")
        assert len(k.get_events_of_type("RunCancelled")) == 1

    def test_resume_run(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.cancel_run(run_id, "pause")
        k.resume_run(run_id)
        assert k.runs[run_id]["status"] == "running"

    def test_resume_run_idempotent(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.resume_run(run_id)  # already running
        assert k.runs[run_id]["status"] == "running"

    def test_resume_run_from_terminal_fails(self) -> None:
        k = MockKernel(strict_mode=True)
        run_id = _start_run(k)
        k.runs[run_id]["status"] = "completed"
        with pytest.raises(IllegalStateTransitionError):
            k.resume_run(run_id)

    def test_resume_run_from_failed_fails(self) -> None:
        k = MockKernel(strict_mode=True)
        run_id = _start_run(k)
        k.runs[run_id]["status"] = "failed"
        with pytest.raises(IllegalStateTransitionError):
            k.resume_run(run_id)

    def test_signal_run(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.signal_run(run_id, "timeout", {"gate_ref": "g-1"})
        assert len(k.runs[run_id]["signals"]) == 1
        assert k.runs[run_id]["signals"][0]["signal"] == "timeout"

    def test_signal_run_not_found(self) -> None:
        k = _make_kernel()
        with pytest.raises(ValueError, match="not found"):
            k.signal_run("nonexistent", "test")


# ---------------------------------------------------------------------------
# Trace runtime (methods 10-11)
# ---------------------------------------------------------------------------


class TestTraceRuntime:
    def test_query_trace_runtime(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.open_stage("S1")
        snapshot = k.query_trace_runtime(run_id)
        assert snapshot["run"]["run_id"] == run_id
        assert "S1" in snapshot["stages"]

    @pytest.mark.asyncio
    async def test_stream_run_events(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.open_stage("S1")
        k.signal_run(run_id, "test_signal")
        events = []
        async for event in k.stream_run_events(run_id):
            events.append(event)
        assert len(events) >= 1
        event_types = {e["event_type"] for e in events}
        assert "RunStarted" in event_types

    @pytest.mark.asyncio
    async def test_stream_run_events_not_found(self) -> None:
        k = _make_kernel()
        with pytest.raises(ValueError, match="not found"):
            async for _ in k.stream_run_events("nonexistent"):
                pass  # pragma: no cover


# ---------------------------------------------------------------------------
# Branch lifecycle (methods 12-13)
# ---------------------------------------------------------------------------


class TestBranchLifecycle:
    def test_open_branch(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        key = (run_id, "S1", "b-1")
        assert k.branches[key]["state"] == "proposed"

    def test_open_branch_idempotent(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        k.open_branch(run_id, "S1", "b-1")
        assert len(k.get_events_of_type("BranchOpened")) == 1

    def test_mark_branch_state_happy_path(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        k.mark_branch_state(run_id, "S1", "b-1", "active")
        key = (run_id, "S1", "b-1")
        assert k.branches[key]["state"] == "active"

    def test_mark_branch_state_idempotent(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        k.mark_branch_state(run_id, "S1", "b-1", "active")
        k.mark_branch_state(run_id, "S1", "b-1", "active")
        events = k.get_events_of_type("BranchStateChanged")
        assert len(events) == 1

    def test_mark_branch_state_illegal_transition(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        k.mark_branch_state(run_id, "S1", "b-1", "active")
        k.mark_branch_state(run_id, "S1", "b-1", "succeeded")
        with pytest.raises(IllegalStateTransitionError):
            k.mark_branch_state(run_id, "S1", "b-1", "active")

    def test_mark_branch_state_with_failure_code(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        k.mark_branch_state(
            run_id, "S1", "b-1", "failed", failure_code="exploration_budget_exhausted"
        )
        key = (run_id, "S1", "b-1")
        assert k.branches[key]["failure_code"] == "exploration_budget_exhausted"

    def test_mark_branch_not_found(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        with pytest.raises(ValueError, match="Branch not found"):
            k.mark_branch_state(run_id, "S1", "b-999", "active")

    def test_branch_full_lifecycle(self) -> None:
        """proposed -> active -> waiting -> active -> succeeded."""
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        for state in ["active", "waiting", "active", "succeeded"]:
            k.mark_branch_state(run_id, "S1", "b-1", state)
        key = (run_id, "S1", "b-1")
        assert k.branches[key]["state"] == "succeeded"

    def test_branch_illegal_from_pruned(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        k.mark_branch_state(run_id, "S1", "b-1", "pruned")
        with pytest.raises(IllegalStateTransitionError):
            k.mark_branch_state(run_id, "S1", "b-1", "active")

    def test_branch_illegal_from_failed(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        _open_branch(k, run_id)
        k.mark_branch_state(run_id, "S1", "b-1", "failed")
        with pytest.raises(IllegalStateTransitionError):
            k.mark_branch_state(run_id, "S1", "b-1", "active")


# ---------------------------------------------------------------------------
# Human gate (methods 14-15)
# ---------------------------------------------------------------------------


class TestHumanGate:
    def _open_gate(
        self,
        k: MockKernel,
        run_id: str,
        gate_type: str = "contract_correction",
        gate_ref: str = "g-1",
    ) -> None:
        k.open_human_gate(
            HumanGateRequest(
                run_id=run_id,
                gate_type=gate_type,
                gate_ref=gate_ref,
                context={"info": "test"},
            )
        )

    def test_open_human_gate(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        assert k.gates["g-1"]["status"] == "pending"
        assert k.gates["g-1"]["gate_type"] == "contract_correction"

    def test_open_human_gate_idempotent(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        self._open_gate(k, run_id)
        assert len(k.get_events_of_type("HumanGateOpened")) == 1

    def test_open_human_gate_invalid_type(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        with pytest.raises(ValueError, match="Unknown gate_type"):
            self._open_gate(k, run_id, gate_type="invalid_type")

    def test_open_human_gate_run_not_found(self) -> None:
        k = _make_kernel()
        with pytest.raises(ValueError, match="not found"):
            self._open_gate(k, "nonexistent")

    def test_submit_approval_approved(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        k.submit_approval(
            ApprovalRequest(
                gate_ref="g-1",
                decision="approved",
                reviewer_id="user-42",
                comment="LGTM",
            )
        )
        assert k.gates["g-1"]["status"] == "resolved"
        assert k.gates["g-1"]["decision"] == "approved"
        assert k.gates["g-1"]["reviewer_id"] == "user-42"

    def test_submit_approval_rejected(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        k.submit_approval(
            ApprovalRequest(gate_ref="g-1", decision="rejected")
        )
        assert k.gates["g-1"]["decision"] == "rejected"

    def test_submit_approval_idempotent(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        k.submit_approval(
            ApprovalRequest(gate_ref="g-1", decision="approved")
        )
        k.submit_approval(
            ApprovalRequest(gate_ref="g-1", decision="approved")
        )
        assert len(k.get_events_of_type("HumanGateResolved")) == 1

    def test_submit_approval_conflict(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        k.submit_approval(
            ApprovalRequest(gate_ref="g-1", decision="approved")
        )
        with pytest.raises(ValueError, match="already resolved"):
            k.submit_approval(
                ApprovalRequest(gate_ref="g-1", decision="rejected")
            )

    def test_submit_approval_gate_not_found(self) -> None:
        k = _make_kernel()
        with pytest.raises(ValueError, match="not found"):
            k.submit_approval(
                ApprovalRequest(gate_ref="missing", decision="approved")
            )

    def test_submit_approval_invalid_decision(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        with pytest.raises(ValueError, match="Invalid decision"):
            k.submit_approval(
                ApprovalRequest(gate_ref="g-1", decision="maybe")
            )

    def test_all_four_gate_types(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        for gate_type in [
            "contract_correction",
            "route_direction",
            "artifact_review",
            "final_approval",
        ]:
            self._open_gate(
                k, run_id, gate_type=gate_type, gate_ref=f"g-{gate_type}"
            )
            assert k.gates[f"g-{gate_type}"]["gate_type"] == gate_type

    def test_full_gate_lifecycle(self) -> None:
        """Open gate -> submit approval -> verify resolved."""
        k = _make_kernel()
        run_id = _start_run(k)
        self._open_gate(k, run_id)
        assert k.gates["g-1"]["status"] == "pending"
        k.submit_approval(
            ApprovalRequest(
                gate_ref="g-1",
                decision="approved",
                reviewer_id="reviewer-1",
                comment="All good",
            )
        )
        assert k.gates["g-1"]["status"] == "resolved"
        assert k.gates["g-1"]["decision"] == "approved"
        assert k.gates["g-1"]["comment"] == "All good"


# ---------------------------------------------------------------------------
# Plan & manifest (methods 16-17)
# ---------------------------------------------------------------------------


class TestPlanAndManifest:
    def test_get_manifest(self) -> None:
        k = _make_kernel()
        manifest = k.get_manifest()
        assert manifest["name"] == "mock_kernel"
        assert "open_human_gate" in manifest["supported_methods"]
        assert "submit_approval" in manifest["supported_methods"]
        assert "stream_run_events" in manifest["supported_methods"]
        assert len(manifest["supported_methods"]) == 17

    def test_submit_plan(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        k.submit_plan(run_id, {"steps": ["gather", "analyze"]})
        assert k.runs[run_id]["plan"] == {"steps": ["gather", "analyze"]}

    def test_submit_plan_invalid_type(self) -> None:
        k = _make_kernel()
        run_id = _start_run(k)
        with pytest.raises(ValueError, match="plan must be a dict"):
            k.submit_plan(run_id, "not a dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Contract enum coverage
# ---------------------------------------------------------------------------


class TestContractEnums:
    def test_run_state_values(self) -> None:
        assert len(RunState) == 7
        expected = {
            "created", "active", "waiting", "recovering",
            "completed", "failed", "aborted",
        }
        assert {s.value for s in RunState} == expected

    def test_branch_state_values(self) -> None:
        assert len(BranchState) == 6
        expected = {
            "proposed", "active", "waiting",
            "pruned", "succeeded", "failed",
        }
        assert {s.value for s in BranchState} == expected

    def test_branch_state_matches_mock_transitions(self) -> None:
        """Every BranchState value should appear in mock transition table."""
        from hi_agent.runtime_adapter.mock_kernel import _BRANCH_TRANSITIONS

        for state in BranchState:
            assert state.value in _BRANCH_TRANSITIONS
