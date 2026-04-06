"""Integration test for run lifecycle."""

import pytest
from hi_agent.contracts import StageState, TaskContract
from hi_agent.runner import STAGES, RunExecutor
from hi_agent.runtime_adapter.errors import IllegalStateTransitionError
from hi_agent.runtime_adapter.mock_kernel import MockKernel


def test_run_lifecycle_emits_expected_events() -> None:
    """Run should open and complete all stages with expected event shape."""
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(TaskContract(task_id="int-001", goal="lifecycle"), kernel)

    result = executor.execute()

    assert result == "completed"
    for stage_id in STAGES:
        kernel.assert_stage_state(stage_id, StageState.COMPLETED)
    assert len(kernel.get_events_of_type("StageOpened")) == len(STAGES)
    assert len(kernel.get_events_of_type("StageStateChanged")) == len(STAGES) * 2


def test_start_run_returns_deterministic_run_id() -> None:
    """Run IDs should be deterministic and monotonically increasing."""
    kernel = MockKernel(strict_mode=True)

    run_1 = kernel.start_run("task-alpha")
    run_2 = kernel.start_run("task-beta")

    assert run_1 == "run-0001"
    assert run_2 == "run-0002"
    assert kernel.query_run(run_1)["task_id"] == "task-alpha"
    assert kernel.query_run(run_2)["task_id"] == "task-beta"


def test_query_run_returns_snapshot_dict() -> None:
    """query_run should return the latest in-memory lifecycle snapshot."""
    kernel = MockKernel(strict_mode=True)
    run_id = kernel.start_run("task-query")

    queried = kernel.query_run(run_id)

    assert queried == {
        "run_id": run_id,
        "task_id": "task-query",
        "status": "running",
        "cancel_reason": None,
        "signals": [],
        "plan": None,
    }


def test_cancel_run_updates_status_and_reason() -> None:
    """Cancel should update run status and record the reason."""
    kernel = MockKernel(strict_mode=True)
    run_id = kernel.start_run("task-cancel")

    kernel.cancel_run(run_id, "manual stop")

    assert kernel.query_run(run_id)["status"] == "cancelled"
    assert kernel.query_run(run_id)["cancel_reason"] == "manual stop"


def test_run_lifecycle_validation_is_strict() -> None:
    """Lifecycle methods should reject empty identifiers and unknown runs."""
    kernel = MockKernel(strict_mode=True)
    run_id = kernel.start_run("task-strict")

    with pytest.raises(ValueError):
        kernel.start_run("")
    with pytest.raises(ValueError):
        kernel.start_run("   ")
    with pytest.raises(ValueError):
        kernel.query_run("")
    with pytest.raises(ValueError):
        kernel.query_run("run-9999")
    with pytest.raises(ValueError):
        kernel.cancel_run(run_id, "")
    with pytest.raises(ValueError):
        kernel.cancel_run(run_id, "   ")
    with pytest.raises(ValueError):
        kernel.cancel_run("run-9999", "manual stop")


def test_extended_runtime_lifecycle_methods_work_together() -> None:
    """Extended lifecycle hooks should produce a coherent trace runtime view."""
    kernel = MockKernel(strict_mode=True)
    run_id = kernel.start_run("task-extended")

    kernel.open_branch(run_id, "S1_understand", "branch-1")
    kernel.mark_branch_state(run_id, "S1_understand", "branch-1", "active")
    kernel.record_task_view("tv-extended", {"run_id": run_id, "stage_id": "S1_understand"})
    kernel.bind_task_view_to_decision("tv-extended", "decision-1")
    kernel.signal_run(run_id, "human_gate", {"gate_ref": "gate-1"})
    kernel.submit_plan(run_id, {"steps": ["S1_understand", "S2_gather"]})

    trace_runtime = kernel.query_trace_runtime(run_id)

    assert trace_runtime["run"]["run_id"] == run_id
    assert trace_runtime["branches"] == [
        {
            "run_id": run_id,
            "stage_id": "S1_understand",
            "branch_id": "branch-1",
            "state": "active",
            "failure_code": None,
        }
    ]
    assert trace_runtime["task_view_bindings"] == {"tv-extended": "decision-1"}
    assert trace_runtime["signals"] == [{"signal": "human_gate", "payload": {"gate_ref": "gate-1"}}]
    assert trace_runtime["plan"] == {"steps": ["S1_understand", "S2_gather"]}


def test_resume_run_rejects_terminal_state() -> None:
    """Resuming a terminal run should raise an illegal transition error."""
    kernel = MockKernel(strict_mode=True)
    run_id = kernel.start_run("task-terminal")
    kernel.runs[run_id]["status"] = "completed"

    with pytest.raises(IllegalStateTransitionError):
        kernel.resume_run(run_id)


def test_mark_branch_state_rejects_illegal_transition_in_strict_mode() -> None:
    """Branch transition model should block non-adjacent state jumps when strict."""
    kernel = MockKernel(strict_mode=True)
    run_id = kernel.start_run("task-branch-strict")
    kernel.open_branch(run_id, "S1_understand", "branch-1")

    with pytest.raises(IllegalStateTransitionError):
        kernel.mark_branch_state(run_id, "S1_understand", "branch-1", "succeeded")
