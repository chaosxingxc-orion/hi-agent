"""Tests for AsyncKernelFacadeAdapter."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest

from hi_agent.runtime_adapter.async_kernel_facade_adapter import (
    AsyncKernelFacadeAdapter,
)
from hi_agent.runtime_adapter.kernel_facade_adapter import _SimpleTurnResult


# ---------------------------------------------------------------------------
# Mock facade for tests
# ---------------------------------------------------------------------------

@dataclass
class _MockEvent:
    event_type: str
    run_id: str


class _MockFacade:
    """Lightweight mock facade with the methods AsyncKernelFacadeAdapter needs."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.stages: list[str] = []
        self.events: dict[str, list[_MockEvent]] = defaultdict(list)
        self.human_gates: list[Any] = []
        self.approvals: list[Any] = []

    async def start_run(
        self, *, run_id: str, session_id: str, metadata: dict
    ) -> str:
        self.runs[run_id] = {
            "run_id": run_id,
            "session_id": session_id,
            "metadata": metadata,
            "state": "running",
        }
        return run_id

    def open_stage(self, stage_id: str) -> None:
        self.stages.append(stage_id)

    def mark_stage_state(self, stage_id: str, target: str) -> None:
        pass

    def query_run(self, run_id: str) -> dict[str, Any]:
        if run_id in self.runs:
            return dict(self.runs[run_id])
        return {"run_id": run_id, "state": "unknown"}

    async def execute_turn(
        self,
        run_id: str,
        action: Any,
        handler: Any,
        *,
        idempotency_key: str,
    ) -> _SimpleTurnResult:
        output = await handler(action, None)
        return _SimpleTurnResult(outcome_kind="dispatched", result=output)

    async def subscribe_events(
        self, run_id: str
    ) -> AsyncIterator[_MockEvent]:
        for event in self.events.get(run_id, []):
            yield event

    def open_human_gate(self, request: Any) -> None:
        self.human_gates.append(request)

    def submit_approval(self, request: Any) -> None:
        self.approvals.append(request)

    def get_manifest(self) -> dict[str, Any]:
        return {"version": "mock-1.0"}

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        pass

    def cancel_run(self, run_id: str, reason: str) -> None:
        pass

    def resume_run(self, run_id: str) -> None:
        pass

    def signal_run(self, run_id: str, signal: str, payload: dict) -> None:
        pass

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id}

    async def stream_run_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        for event in self.events.get(run_id, []):
            if isinstance(event, dict):
                yield event
            else:
                yield event.__dict__.copy()

    def record_task_view(
        self, task_view_id: str, content: dict[str, Any]
    ) -> str:
        return task_view_id

    def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        pass

    def open_branch(
        self, run_id: str, stage_id: str, branch_id: str
    ) -> None:
        pass

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        pass


class _MinimalFacade:
    """Facade without execute_turn — tests fallback path."""

    def open_stage(self, stage_id: str) -> None:
        pass

    def mark_stage_state(self, stage_id: str, target: str) -> None:
        pass

    def query_run(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "state": "running"}

    def start_run(self, task_id: str) -> str:
        return task_id

    def cancel_run(self, run_id: str, reason: str) -> None:
        pass

    def resume_run(self, run_id: str) -> None:
        pass

    def signal_run(self, run_id: str, signal: str, payload: dict) -> None:
        pass

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id}

    async def stream_run_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "fallback", "run_id": run_id}

    def open_branch(
        self, run_id: str, stage_id: str, branch_id: str
    ) -> None:
        pass

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        pass

    def open_human_gate(self, request: Any) -> None:
        pass

    def submit_approval(self, request: Any) -> None:
        pass

    def get_manifest(self) -> dict[str, Any]:
        return {"version": "minimal"}

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        pass

    def record_task_view(
        self, task_view_id: str, content: dict[str, Any]
    ) -> str:
        return task_view_id

    def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_adapter_start_run():
    facade = _MockFacade()
    adapter = AsyncKernelFacadeAdapter(facade)
    run_id = await adapter.start_run("run-1", "sess-1", {"goal": "test"})
    assert run_id == "run-1"
    assert "run-1" in facade.runs


@pytest.mark.asyncio
async def test_async_adapter_open_stage():
    facade = _MockFacade()
    adapter = AsyncKernelFacadeAdapter(facade)
    await adapter.open_stage("stage-1")
    assert "stage-1" in facade.stages


@pytest.mark.asyncio
async def test_async_adapter_execute_turn():
    facade = _MockFacade()
    adapter = AsyncKernelFacadeAdapter(facade)

    async def handler(action, _ctx):
        return f"handled:{action}"

    result = await adapter.execute_turn(
        run_id="run-1",
        action="do_something",
        handler=handler,
        idempotency_key="key-1",
    )
    assert result.outcome_kind == "dispatched"
    assert result.result == "handled:do_something"


@pytest.mark.asyncio
async def test_async_adapter_execute_turn_fallback():
    """When facade lacks execute_turn, handler is called directly."""
    facade = _MinimalFacade()
    adapter = AsyncKernelFacadeAdapter(facade)

    async def handler(action, _ctx):
        return f"fallback:{action}"

    result = await adapter.execute_turn(
        run_id="run-1",
        action="action-x",
        handler=handler,
        idempotency_key="key-2",
    )
    assert isinstance(result, _SimpleTurnResult)
    assert result.outcome_kind == "dispatched"
    assert result.result == "fallback:action-x"


@pytest.mark.asyncio
async def test_async_adapter_subscribe_events():
    facade = _MockFacade()
    facade.events["run-1"] = [
        _MockEvent(event_type="step", run_id="run-1"),
        _MockEvent(event_type="done", run_id="run-1"),
    ]
    adapter = AsyncKernelFacadeAdapter(facade)

    events = []
    async for event in adapter.subscribe_events("run-1"):
        events.append(event)
    assert len(events) == 2
    assert events[0]["event_type"] == "step"
    assert events[1]["event_type"] == "done"


@pytest.mark.asyncio
async def test_async_adapter_query_run():
    facade = _MockFacade()
    facade.runs["run-1"] = {
        "run_id": "run-1",
        "session_id": "s",
        "metadata": {},
        "state": "running",
    }
    adapter = AsyncKernelFacadeAdapter(facade)
    snapshot = await adapter.query_run("run-1")
    assert snapshot["run_id"] == "run-1"
    assert snapshot["state"] == "running"


@pytest.mark.asyncio
async def test_async_adapter_human_gate():
    facade = _MockFacade()
    adapter = AsyncKernelFacadeAdapter(facade)

    gate_req = type("HumanGateRequest", (), {"gate_id": "g1", "run_id": "r1"})()
    await adapter.open_human_gate(gate_req)
    assert len(facade.human_gates) == 1

    approval_req = type("ApprovalRequest", (), {"gate_id": "g1", "approved": True})()
    await adapter.submit_approval(approval_req)
    assert len(facade.approvals) == 1
