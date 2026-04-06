"""Tests for KernelFacadeAdapter -- the real agent-kernel integration layer.

All tests use mock facades so agent-kernel does NOT need to be installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter
from hi_agent.runtime_adapter.temporal_health import (
    SubstrateHealthChecker,
    SubstrateNetworkState,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class _MinimalFacade:
    """Mock facade that records calls and returns configurable results."""

    def __init__(self) -> None:
        """Initialize call recorder."""
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._results: dict[str, Any] = {}

    def _record(self, method: str, *args: Any) -> Any:
        """Record method call and return configured result."""
        self.calls.append((method, args))
        return self._results.get(method)

    def set_result(self, method: str, value: Any) -> None:
        """Set a return value for a given method name."""
        self._results[method] = value

    def open_stage(self, *a: Any) -> Any:
        """Forward open_stage."""
        return self._record("open_stage", *a)

    def mark_stage_state(self, *a: Any) -> Any:
        """Forward mark_stage_state."""
        return self._record("mark_stage_state", *a)

    def record_task_view(self, *a: Any) -> Any:
        """Forward record_task_view."""
        return self._record("record_task_view", *a)

    def bind_task_view_to_decision(self, *a: Any) -> Any:
        """Forward bind_task_view_to_decision."""
        return self._record("bind_task_view_to_decision", *a)

    def start_run(self, *a: Any) -> Any:
        """Forward start_run."""
        return self._record("start_run", *a)

    def query_run(self, *a: Any) -> Any:
        """Forward query_run."""
        return self._record("query_run", *a)

    def cancel_run(self, *a: Any) -> Any:
        """Forward cancel_run."""
        return self._record("cancel_run", *a)

    def resume_run(self, *a: Any) -> Any:
        """Forward resume_run."""
        return self._record("resume_run", *a)

    def signal_run(self, *a: Any) -> Any:
        """Forward signal_run."""
        return self._record("signal_run", *a)

    def query_trace_runtime(self, *a: Any) -> Any:
        """Forward query_trace_runtime."""
        return self._record("query_trace_runtime", *a)

    def open_branch(self, *a: Any) -> Any:
        """Forward open_branch."""
        return self._record("open_branch", *a)

    def mark_branch_state(self, *a: Any) -> Any:
        """Forward mark_branch_state."""
        return self._record("mark_branch_state", *a)

    def open_human_gate(self, *a: Any) -> Any:
        """Forward open_human_gate."""
        return self._record("open_human_gate", *a)

    def submit_approval(self, *a: Any) -> Any:
        """Forward submit_approval."""
        return self._record("submit_approval", *a)

    def get_manifest(self, *a: Any) -> Any:
        """Forward get_manifest."""
        return self._record("get_manifest", *a)

    def submit_plan(self, *a: Any) -> Any:
        """Forward submit_plan."""
        return self._record("submit_plan", *a)

    async def stream_run_events(self, run_id: str) -> AsyncIterator[dict]:
        """Yield events configured via set_result."""
        self.calls.append(("stream_run_events", (run_id,)))
        events = self._results.get("stream_run_events", [])
        for event in events:
            yield event


@pytest.fixture()
def facade() -> _MinimalFacade:
    """Create a fresh minimal facade."""
    return _MinimalFacade()


@pytest.fixture()
def adapter(facade: _MinimalFacade) -> KernelFacadeAdapter:
    """Create a KernelFacadeAdapter backed by the minimal facade."""
    return KernelFacadeAdapter(facade)


# ------------------------------------------------------------------
# Instantiation
# ------------------------------------------------------------------


def test_instantiate_with_mock_facade() -> None:
    """Adapter accepts any object as facade."""
    mock = MagicMock()
    ada = KernelFacadeAdapter(mock)
    assert ada._facade is mock


def test_instantiate_with_minimal_facade(facade: _MinimalFacade) -> None:
    """Adapter stores the facade reference."""
    ada = KernelFacadeAdapter(facade)
    assert ada._facade is facade


# ------------------------------------------------------------------
# Stage lifecycle
# ------------------------------------------------------------------


def test_open_stage_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """open_stage forwards stage_id to facade."""
    adapter.open_stage("S1")
    assert ("open_stage", ("S1",)) in facade.calls


def test_open_stage_rejects_empty() -> None:
    """open_stage raises ValueError on blank stage_id."""
    adapter = KernelFacadeAdapter(_MinimalFacade())
    with pytest.raises(ValueError, match="stage_id"):
        adapter.open_stage("  ")


def test_mark_stage_state_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """mark_stage_state passes enum .value string."""
    adapter.mark_stage_state("S1", StageState.ACTIVE)
    assert ("mark_stage_state", ("S1", "active")) in facade.calls


def test_mark_stage_state_rejects_empty(adapter: KernelFacadeAdapter) -> None:
    """mark_stage_state raises on blank stage_id."""
    with pytest.raises(ValueError, match="stage_id"):
        adapter.mark_stage_state("", StageState.ACTIVE)


# ------------------------------------------------------------------
# Run lifecycle
# ------------------------------------------------------------------


def test_start_run_returns_id(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """start_run returns the run_id string from the facade."""
    facade.set_result("start_run", "run-0001")
    assert adapter.start_run("task-1") == "run-0001"
    assert ("start_run", ("task-1",)) in facade.calls


def test_start_run_raises_on_empty_result(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """start_run raises when facade returns empty string."""
    facade.set_result("start_run", "")
    with pytest.raises(RuntimeAdapterBackendError, match="start_run"):
        adapter.start_run("task-1")


def test_start_run_raises_on_none_result(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """start_run raises when facade returns None."""
    facade.set_result("start_run", None)
    with pytest.raises(RuntimeAdapterBackendError, match="start_run"):
        adapter.start_run("task-1")


def test_start_run_rejects_empty_task_id(adapter: KernelFacadeAdapter) -> None:
    """start_run raises on blank task_id."""
    with pytest.raises(ValueError, match="task_id"):
        adapter.start_run("  ")


def test_query_run_returns_dict(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """query_run returns a dict snapshot."""
    expected = {"run_id": "run-0001", "status": "running"}
    facade.set_result("query_run", expected)
    assert adapter.query_run("run-0001") == expected


def test_query_run_raises_on_non_dict(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """query_run raises when facade returns non-dict."""
    facade.set_result("query_run", "not-a-dict")
    with pytest.raises(RuntimeAdapterBackendError, match="query_run"):
        adapter.query_run("run-0001")


def test_query_run_returns_copy(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """query_run returns a defensive copy."""
    original = {"run_id": "run-0001"}
    facade.set_result("query_run", original)
    result = adapter.query_run("run-0001")
    result["injected"] = True
    assert "injected" not in original


def test_cancel_run_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """cancel_run forwards run_id and reason."""
    adapter.cancel_run("run-0001", "budget exhausted")
    assert ("cancel_run", ("run-0001", "budget exhausted")) in facade.calls


def test_resume_run_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """resume_run forwards run_id."""
    adapter.resume_run("run-0001")
    assert ("resume_run", ("run-0001",)) in facade.calls


def test_signal_run_with_payload(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """signal_run forwards signal type and payload."""
    adapter.signal_run("run-0001", "wake_up", {"key": "val"})
    assert (
        "signal_run",
        ("run-0001", "wake_up", {"key": "val"}),
    ) in facade.calls


def test_signal_run_defaults_empty_payload(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """signal_run defaults to empty dict when payload omitted."""
    adapter.signal_run("run-0001", "wake_up")
    assert ("signal_run", ("run-0001", "wake_up", {})) in facade.calls


# ------------------------------------------------------------------
# Branch lifecycle
# ------------------------------------------------------------------


def test_open_branch_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """open_branch forwards run_id, stage_id, branch_id."""
    adapter.open_branch("run-0001", "S1", "B1")
    assert ("open_branch", ("run-0001", "S1", "B1")) in facade.calls


def test_mark_branch_state_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """mark_branch_state forwards state with None failure_code."""
    adapter.mark_branch_state("run-0001", "S1", "B1", "active")
    assert (
        "mark_branch_state",
        ("run-0001", "S1", "B1", "active", None),
    ) in facade.calls


def test_mark_branch_state_with_failure_code(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """mark_branch_state passes failure_code when provided."""
    adapter.mark_branch_state("run-0001", "S1", "B1", "failed", "no_progress")
    assert (
        "mark_branch_state",
        ("run-0001", "S1", "B1", "failed", "no_progress"),
    ) in facade.calls


# ------------------------------------------------------------------
# Trace runtime
# ------------------------------------------------------------------


def test_query_trace_runtime_returns_dict(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """query_trace_runtime returns a dict snapshot."""
    expected = {"run_id": "run-0001", "stages": {}}
    facade.set_result("query_trace_runtime", expected)
    assert adapter.query_trace_runtime("run-0001") == expected


# ------------------------------------------------------------------
# Task view
# ------------------------------------------------------------------


def test_record_task_view_returns_id(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """record_task_view returns task_view_id from facade."""
    facade.set_result("record_task_view", "tv-001")
    assert adapter.record_task_view("tv-001", {"model": "gpt-4"}) == "tv-001"


def test_record_task_view_falls_back(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """record_task_view falls back to input id when facade returns None."""
    facade.set_result("record_task_view", None)
    assert adapter.record_task_view("tv-001", {"model": "gpt-4"}) == "tv-001"


def test_record_task_view_rejects_non_dict(
    adapter: KernelFacadeAdapter,
) -> None:
    """record_task_view raises on non-dict content."""
    with pytest.raises(ValueError, match="content must be a dict"):
        adapter.record_task_view("tv-001", "not-a-dict")  # type: ignore[arg-type]


def test_bind_task_view_to_decision_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """bind_task_view_to_decision forwards both IDs."""
    adapter.bind_task_view_to_decision("tv-001", "decision-ref-1")
    assert (
        "bind_task_view_to_decision",
        ("tv-001", "decision-ref-1"),
    ) in facade.calls


# ------------------------------------------------------------------
# Human gate
# ------------------------------------------------------------------


def test_open_human_gate_delegates_request(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """open_human_gate passes the HumanGateRequest object directly."""
    request = HumanGateRequest(
        run_id="run-0001",
        gate_type="final_approval",
        gate_ref="gate-001",
        context={"artifact": "report.pdf"},
    )
    adapter.open_human_gate(request)
    assert len(facade.calls) == 1
    assert facade.calls[0][0] == "open_human_gate"
    assert facade.calls[0][1][0] is request


def test_submit_approval_delegates_request(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """submit_approval passes the ApprovalRequest object directly."""
    request = ApprovalRequest(
        gate_ref="gate-001",
        decision="approved",
        reviewer_id="user-42",
    )
    adapter.submit_approval(request)
    assert len(facade.calls) == 1
    assert facade.calls[0][0] == "submit_approval"
    assert facade.calls[0][1][0] is request


# ------------------------------------------------------------------
# Stream run events
# ------------------------------------------------------------------


def test_stream_yields_dict_events(facade: _MinimalFacade) -> None:
    """stream_run_events yields dict events from the facade."""
    events = [
        {"event_type": "RunStarted", "run_id": "run-0001"},
        {"event_type": "StageOpened", "run_id": "run-0001"},
    ]
    facade.set_result("stream_run_events", events)
    ada = KernelFacadeAdapter(facade)
    collected: list[dict] = []

    async def _collect() -> None:
        async for event in ada.stream_run_events("run-0001"):
            collected.append(event)

    asyncio.run(_collect())
    assert collected == events


def test_stream_converts_dataclass_events(facade: _MinimalFacade) -> None:
    """stream_run_events converts dataclass events to dicts."""

    @dataclass
    class _FakeEvent:
        """Minimal event dataclass."""

        event_type: str
        run_id: str

    facade.set_result("stream_run_events", [_FakeEvent("RunStarted", "run-0001")])
    ada = KernelFacadeAdapter(facade)
    collected: list[dict] = []

    async def _collect() -> None:
        async for event in ada.stream_run_events("run-0001"):
            collected.append(event)

    asyncio.run(_collect())
    assert len(collected) == 1
    assert collected[0]["event_type"] == "RunStarted"


def test_stream_raises_on_missing_method() -> None:
    """stream_run_events raises when facade lacks the method."""

    class _NoStream:
        """Facade without stream_run_events."""

    ada = KernelFacadeAdapter(_NoStream())

    async def _collect() -> None:
        async for _ in ada.stream_run_events("run-0001"):
            pass  # pragma: no cover

    with pytest.raises(RuntimeAdapterBackendError, match="stream_run_events"):
        asyncio.run(_collect())


# ------------------------------------------------------------------
# Plan & manifest
# ------------------------------------------------------------------


def test_get_manifest_returns_dict(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """get_manifest returns dict from facade."""
    manifest = {"name": "kernel", "version": "0.2.0"}
    facade.set_result("get_manifest", manifest)
    assert adapter.get_manifest() == manifest


def test_get_manifest_converts_dataclass(facade: _MinimalFacade) -> None:
    """get_manifest converts a dataclass result to dict."""

    @dataclass
    class _FakeManifest:
        """Minimal manifest dataclass."""

        name: str
        version: str

    facade.set_result("get_manifest", _FakeManifest("kernel", "0.2.0"))
    ada = KernelFacadeAdapter(facade)
    result = ada.get_manifest()
    assert result["name"] == "kernel"
    assert result["version"] == "0.2.0"


def test_submit_plan_delegates(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """submit_plan forwards run_id and plan dict."""
    plan = {"steps": ["gather", "build"]}
    adapter.submit_plan("run-0001", plan)
    assert ("submit_plan", ("run-0001", plan)) in facade.calls


def test_submit_plan_rejects_non_dict(adapter: KernelFacadeAdapter) -> None:
    """submit_plan raises on non-dict plan."""
    with pytest.raises(ValueError, match="plan must be a dict"):
        adapter.submit_plan("run-0001", "not-a-dict")  # type: ignore[arg-type]


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------


def test_wraps_facade_exception() -> None:
    """Adapter wraps arbitrary facade exceptions in RuntimeAdapterBackendError."""

    class _FailingFacade:
        """Facade that raises ConnectionError."""

        def start_run(self, task_id: str) -> str:
            raise ConnectionError("network down")

    ada = KernelFacadeAdapter(_FailingFacade())
    with pytest.raises(RuntimeAdapterBackendError, match="start_run"):
        ada.start_run("task-1")


def test_raises_on_missing_method() -> None:
    """Adapter raises RuntimeAdapterBackendError for missing methods."""

    class _EmptyFacade:
        """Facade with no methods."""

    ada = KernelFacadeAdapter(_EmptyFacade())
    with pytest.raises(RuntimeAdapterBackendError, match="open_stage"):
        ada.open_stage("S1")


def test_does_not_modify_request_objects(
    adapter: KernelFacadeAdapter, facade: _MinimalFacade
) -> None:
    """Adapter must not mutate HumanGateRequest or ApprovalRequest."""
    gate_req = HumanGateRequest(
        run_id="run-0001",
        gate_type="artifact_review",
        gate_ref="gate-001",
        context={"key": "value"},
    )
    approval_req = ApprovalRequest(
        gate_ref="gate-001",
        decision="approved",
        reviewer_id="user-1",
        comment="looks good",
    )
    adapter.open_human_gate(gate_req)
    adapter.submit_approval(approval_req)
    # Frozen dataclasses: verify adapter passes same object, no copy.
    assert facade.calls[0][1][0] is gate_req
    assert facade.calls[1][1][0] is approval_req


# ------------------------------------------------------------------
# Substrate health checker
# ------------------------------------------------------------------


def test_substrate_local_fsm_always_connected() -> None:
    """LocalFSM substrate reports connected without network dependency."""
    checker = SubstrateHealthChecker(substrate_type="local_fsm")
    report = checker.check()
    assert report.healthy is True
    assert report.network_state == SubstrateNetworkState.CONNECTED
    assert report.substrate_type == "local_fsm"


def test_substrate_remote_connected() -> None:
    """Remote substrate reports connected with low latency."""
    checker = SubstrateHealthChecker(
        substrate_type="temporal",
        ping_fn=lambda: 10.0,
        health_fn=lambda: {"status": "ok"},
    )
    report = checker.check()
    assert report.healthy is True
    assert report.network_state == SubstrateNetworkState.CONNECTED


def test_substrate_remote_degraded_by_latency() -> None:
    """Remote substrate reports degraded when latency exceeds threshold."""
    checker = SubstrateHealthChecker(
        substrate_type="temporal",
        ping_fn=lambda: 600.0,
        degraded_latency_ms=500.0,
    )
    report = checker.check()
    assert report.network_state == SubstrateNetworkState.DEGRADED


def test_substrate_remote_disconnected_on_ping_failure() -> None:
    """Remote substrate reports disconnected when ping raises."""

    def _failing_ping() -> float:
        raise ConnectionError("unreachable")

    checker = SubstrateHealthChecker(
        substrate_type="temporal",
        ping_fn=_failing_ping,
    )
    report = checker.check()
    assert report.healthy is False
    assert report.network_state == SubstrateNetworkState.DISCONNECTED
    assert report.error is not None


def test_substrate_local_unhealthy_via_health_fn() -> None:
    """LocalFSM can still be unhealthy if health_fn says so."""
    checker = SubstrateHealthChecker(
        substrate_type="local_fsm",
        health_fn=lambda: {"status": "unhealthy", "reason": "oom"},
    )
    report = checker.check()
    assert report.healthy is False
    assert report.network_state == SubstrateNetworkState.CONNECTED
    assert "oom" in (report.error or "")
