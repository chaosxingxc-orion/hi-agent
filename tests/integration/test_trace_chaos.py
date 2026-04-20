"""Minimal chaos regression tests for TRACE run + journal/replay behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.events import append_event, load_events
from hi_agent.replay import ReplayEngine
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


@dataclass(slots=True)
class _ChaosCase:
    name: str
    expected_result: str
    expected_replay_success: bool


class _BackendFailInvoker:
    """Invoker that simulates backend call failures for one capability."""

    def __init__(self, fail_capability: str) -> None:
        self.fail_capability = fail_capability

    def invoke(self, capability_name: str, payload: dict) -> dict:
        if capability_name == self.fail_capability:
            raise RuntimeError(f"backend_failure:{capability_name}")
        return {
            "success": True,
            "score": 1.0,
            "reason": "ok",
            "evidence_hash": f"ev_{payload.get('stage_id', 'unknown')}",
        }


@pytest.mark.parametrize(
    "case",
    [
        _ChaosCase(
            name="capability_failure",
            expected_result="failed",
            expected_replay_success=False,
        ),
        _ChaosCase(
            name="backend_failure",
            expected_result="failed",
            expected_replay_success=False,
        ),
        _ChaosCase(
            name="bad_event_line",
            expected_result="completed",
            expected_replay_success=True,
        ),
    ],
    ids=["capability_failure", "backend_failure", "bad_event_line"],
)
def test_trace_chaos_minimal_regression(case: _ChaosCase, tmp_path) -> None:
    """Three fault classes should remain explainable and non-crashing."""
    constraints = []
    invoker = None

    if case.name == "capability_failure":
        constraints = ["fail_action:build_draft"]
    elif case.name == "backend_failure":
        invoker = _BackendFailInvoker("build_draft")

    contract = TaskContract(
        task_id=f"chaos-{case.name}",
        goal="chaos regression",
        constraints=constraints,
    )
    executor = RunExecutor(contract, MockKernel(strict_mode=True), invoker=invoker)
    result = executor.execute()

    if case.name == "bad_event_line":
        event_path = tmp_path / "chaos_events.jsonl"
        for envelope in executor.event_emitter.events:
            append_event(event_path, envelope)
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write("{not-valid-json}\n")

        loaded_events, bad_line_count = load_events(event_path)
        report = ReplayEngine().replay(loaded_events)

        assert bad_line_count == 1
        assert len(loaded_events) == len(executor.event_emitter.events)
        assert report.stage_states["S5_review"] == "completed"
    else:
        report = ReplayEngine().replay(executor.event_emitter.events)
        assert report.stage_states["S3_build"] == "failed"

        if case.name == "capability_failure":
            assert any(
                event.event_type == "ActionExecuted"
                and event.payload.get("action_kind") == "build_draft"
                and event.payload.get("success") is False
                for event in executor.event_emitter.events
            )
        elif case.name == "backend_failure":
            assert any(
                event.event_type == "ActionExecutionFailed"
                and event.payload.get("action_kind") == "build_draft"
                for event in executor.event_emitter.events
            )

    assert result == case.expected_result
    assert report.success is case.expected_replay_success
    assert len(executor.event_emitter.events) > 0
