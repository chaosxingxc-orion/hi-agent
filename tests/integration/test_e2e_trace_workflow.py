"""End-to-end TRACE workflow regression tests."""

from __future__ import annotations

import pytest
from hi_agent.contracts import StageState, TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.replay import ReplayEngine
from hi_agent.runner import STAGES, RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_e2e_trace_workflow_completed_replay_success() -> None:
    """Completed scenario should finish all stages and replay as success."""
    contract = TaskContract(task_id="e2e-trace-001", goal="e2e completed workflow")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

    result = executor.execute()
    report = ReplayEngine().replay(executor.event_emitter.events)

    assert result == "completed"
    for stage_id in STAGES:
        kernel.assert_stage_state(stage_id, StageState.COMPLETED)
    assert len(kernel.task_views) > 0
    assert report.success is True
    assert report.task_view_count > 0
    assert set(report.stage_states.keys()) == set(STAGES)
    assert all(state == "completed" for state in report.stage_states.values())


@pytest.mark.parametrize("action_max_retries", [0, 1])
def test_e2e_trace_workflow_failed_replay_failed(action_max_retries: int) -> None:
    """Forced action failure should fail run and replay for retries 0/1."""
    contract = TaskContract(
        task_id=f"e2e-trace-fail-{action_max_retries}",
        goal="e2e failed workflow",
        constraints=[
            "fail_action:build_draft",
            f"action_max_retries:{action_max_retries}",
        ],
    )
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

    result = executor.execute()
    report = ReplayEngine().replay(executor.event_emitter.events)

    assert result == "failed"
    kernel.assert_stage_state("S3_build", StageState.FAILED)
    assert report.success is False
    assert report.stage_states["S3_build"] == "failed"

    build_attempts = [
        event.payload["attempt"]
        for event in executor.event_emitter.events
        if event.event_type == "ActionExecuted"
        and event.payload.get("action_kind") == "build_draft"
    ]
    assert build_attempts == list(range(1, action_max_retries + 2))
