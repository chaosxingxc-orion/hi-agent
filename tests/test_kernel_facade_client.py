"""Tests for KernelFacadeClient -- direct mode and HTTP mode."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeFacade:
    """Minimal in-memory facade compatible with KernelFacadeClient direct mode."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._run_counter = 0
        self._task_views: dict[str, dict] = {}

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def start_run(self, task_id: str) -> str:
        self._record("start_run", task_id)
        self._run_counter += 1
        return f"run-{self._run_counter:04d}"

    def open_stage(self, stage_id: str) -> None:
        self._record("open_stage", stage_id)

    def mark_stage_state(self, stage_id: str, target: str) -> None:
        self._record("mark_stage_state", stage_id, target)

    def record_task_view(self, task_view_id: str, content: dict) -> str:
        self._record("record_task_view", task_view_id, content)
        self._task_views[task_view_id] = content
        return task_view_id

    def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        self._record("bind_task_view_to_decision", task_view_id, decision_ref)

    def query_run(self, run_id: str) -> dict[str, Any]:
        self._record("query_run", run_id)
        return {"run_id": run_id, "status": "running"}

    def cancel_run(self, run_id: str, reason: str) -> None:
        self._record("cancel_run", run_id, reason)

    def resume_run(self, run_id: str) -> None:
        self._record("resume_run", run_id)

    def signal_run(
        self, run_id: str, signal: str, payload: dict[str, Any]
    ) -> None:
        self._record("signal_run", run_id, signal, payload)

    def open_branch(
        self, run_id: str, stage_id: str, branch_id: str
    ) -> None:
        self._record("open_branch", run_id, stage_id, branch_id)

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        self._record(
            "mark_branch_state", run_id, stage_id, branch_id, state, failure_code
        )

    def open_human_gate(self, request: HumanGateRequest) -> None:
        self._record("open_human_gate", request)

    def submit_approval(self, request: ApprovalRequest) -> None:
        self._record("submit_approval", request)

    def get_manifest(self) -> dict[str, Any]:
        self._record("get_manifest")
        return {"name": "fake_facade", "version": "0.1.0"}

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        self._record("submit_plan", run_id, plan)

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        self._record("query_trace_runtime", run_id)
        return {"run_id": run_id, "stages": {}}

    async def stream_run_events(self, run_id: str):
        self._record("stream_run_events", run_id)
        yield {"event_type": "RunStarted", "run_id": run_id}


# ---------------------------------------------------------------------------
# Direct mode tests
# ---------------------------------------------------------------------------


class TestDirectMode:
    """Verify all 17 methods delegate correctly in direct mode."""

    @pytest.fixture()
    def facade(self) -> FakeFacade:
        return FakeFacade()

    @pytest.fixture()
    def client(self, facade: FakeFacade) -> KernelFacadeClient:
        return KernelFacadeClient(mode="direct", facade=facade)

    def test_start_run(self, client: KernelFacadeClient, facade: FakeFacade) -> None:
        run_id = client.start_run("task-1")
        assert run_id == "run-0001"
        assert facade.calls[-1] == ("start_run", ("task-1",))

    def test_open_stage(self, client: KernelFacadeClient, facade: FakeFacade) -> None:
        client.open_stage("S1")
        assert facade.calls[-1] == ("open_stage", ("S1",))

    def test_mark_stage_state(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.mark_stage_state("S1", StageState.ACTIVE)
        assert facade.calls[-1] == ("mark_stage_state", ("S1", "active"))

    def test_record_task_view(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        result = client.record_task_view("tv-1", {"key": "val"})
        assert result == "tv-1"
        assert facade.calls[-1] == (
            "record_task_view",
            ("tv-1", {"key": "val"}),
        )

    def test_bind_task_view_to_decision(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.bind_task_view_to_decision("tv-1", "dec-1")
        assert facade.calls[-1] == (
            "bind_task_view_to_decision",
            ("tv-1", "dec-1"),
        )

    def test_query_run(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        result = client.query_run("run-0001")
        assert result == {"run_id": "run-0001", "status": "running"}

    def test_cancel_run(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.cancel_run("run-0001", "budget")
        assert facade.calls[-1] == ("cancel_run", ("run-0001", "budget"))

    def test_resume_run(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.resume_run("run-0001")
        assert facade.calls[-1] == ("resume_run", ("run-0001",))

    def test_signal_run(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.signal_run("run-0001", "pause", {"info": "test"})
        assert facade.calls[-1] == (
            "signal_run",
            ("run-0001", "pause", {"info": "test"}),
        )

    def test_open_branch(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.open_branch("run-0001", "S1", "b-1")
        assert facade.calls[-1] == (
            "open_branch",
            ("run-0001", "S1", "b-1"),
        )

    def test_mark_branch_state(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.mark_branch_state("run-0001", "S1", "b-1", "active")
        assert facade.calls[-1] == (
            "mark_branch_state",
            ("run-0001", "S1", "b-1", "active", None),
        )

    def test_mark_branch_state_with_failure(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.mark_branch_state(
            "run-0001", "S1", "b-1", "failed", failure_code="exploration_budget_exhausted"
        )
        assert facade.calls[-1] == (
            "mark_branch_state",
            ("run-0001", "S1", "b-1", "failed", "exploration_budget_exhausted"),
        )

    def test_open_human_gate(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        req = HumanGateRequest(
            run_id="run-0001",
            gate_type="final_approval",
            gate_ref="gate-1",
        )
        client.open_human_gate(req)
        assert facade.calls[-1][0] == "open_human_gate"

    def test_submit_approval(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        req = ApprovalRequest(gate_ref="gate-1", decision="approved")
        client.submit_approval(req)
        assert facade.calls[-1][0] == "submit_approval"

    def test_get_manifest(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        result = client.get_manifest()
        assert result["name"] == "fake_facade"

    def test_submit_plan(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        client.submit_plan("run-0001", {"steps": [1, 2]})
        assert facade.calls[-1] == (
            "submit_plan",
            ("run-0001", {"steps": [1, 2]}),
        )

    def test_query_trace_runtime(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        result = client.query_trace_runtime("run-0001")
        assert result["run_id"] == "run-0001"

    def test_stream_run_events(
        self, client: KernelFacadeClient, facade: FakeFacade
    ) -> None:
        events = []

        async def _collect():
            async for ev in client.stream_run_events("run-0001"):
                events.append(ev)

        asyncio.run(_collect())
        assert len(events) == 1
        assert events[0]["event_type"] == "RunStarted"


# ---------------------------------------------------------------------------
# HTTP mode tests
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    """Minimal HTTP response mock for urllib.request.urlopen."""

    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestHTTPMode:
    """Verify HTTP mode request formatting and response handling."""

    @pytest.fixture()
    def client(self) -> KernelFacadeClient:
        return KernelFacadeClient(
            mode="http", base_url="http://localhost:9090", timeout_seconds=5
        )

    @patch("urllib.request.urlopen")
    def test_start_run_http(self, mock_urlopen, client: KernelFacadeClient) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({"run_id": "run-http-1"})
        run_id = client.start_run("task-http")
        assert run_id == "run-http-1"
        # Verify request was made
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "http://localhost:9090/runs/start"
        assert req.method == "POST"
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"task_id": "task-http"}

    @patch("urllib.request.urlopen")
    def test_query_run_http(self, mock_urlopen, client: KernelFacadeClient) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse(
            {"run_id": "r1", "status": "running"}
        )
        result = client.query_run("r1")
        assert result == {"run_id": "r1", "status": "running"}
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://localhost:9090/runs/r1"
        assert req.method == "GET"

    @patch("urllib.request.urlopen")
    def test_cancel_run_http(self, mock_urlopen, client: KernelFacadeClient) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.cancel_run("r1", "timeout")
        req = mock_urlopen.call_args[0][0]
        assert "/runs/r1/cancel" in req.full_url
        body = json.loads(req.data.decode("utf-8"))
        assert body["reason"] == "timeout"

    @patch("urllib.request.urlopen")
    def test_resume_run_http(self, mock_urlopen, client: KernelFacadeClient) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.resume_run("r1")
        req = mock_urlopen.call_args[0][0]
        assert "/runs/r1/resume" in req.full_url

    @patch("urllib.request.urlopen")
    def test_signal_run_http(self, mock_urlopen, client: KernelFacadeClient) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.signal_run("r1", "pause", {"k": "v"})
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["signal"] == "pause"
        assert body["payload"] == {"k": "v"}

    @patch("urllib.request.urlopen")
    def test_open_stage_http(self, mock_urlopen, client: KernelFacadeClient) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.open_stage("S1")
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["stage_id"] == "S1"

    @patch("urllib.request.urlopen")
    def test_mark_stage_state_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.mark_stage_state("S1", StageState.ACTIVE)
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["stage_id"] == "S1"
        assert body["target"] == "active"

    @patch("urllib.request.urlopen")
    def test_record_task_view_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({"task_view_id": "tv-1"})
        result = client.record_task_view("tv-1", {"data": True})
        assert result == "tv-1"

    @patch("urllib.request.urlopen")
    def test_bind_task_view_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.bind_task_view_to_decision("tv-1", "dec-1")
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["task_view_id"] == "tv-1"
        assert body["decision_ref"] == "dec-1"

    @patch("urllib.request.urlopen")
    def test_open_branch_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.open_branch("r1", "S1", "b-1")
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"run_id": "r1", "stage_id": "S1", "branch_id": "b-1"}

    @patch("urllib.request.urlopen")
    def test_mark_branch_state_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.mark_branch_state("r1", "S1", "b-1", "failed", "exploration_budget_exhausted")
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["state"] == "failed"
        assert body["failure_code"] == "exploration_budget_exhausted"

    @patch("urllib.request.urlopen")
    def test_open_human_gate_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        req = HumanGateRequest(
            run_id="r1", gate_type="final_approval", gate_ref="g1"
        )
        client.open_human_gate(req)
        http_req = mock_urlopen.call_args[0][0]
        body = json.loads(http_req.data.decode("utf-8"))
        assert body["gate_type"] == "final_approval"
        assert body["gate_ref"] == "g1"

    @patch("urllib.request.urlopen")
    def test_submit_approval_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        req = ApprovalRequest(gate_ref="g1", decision="approved")
        client.submit_approval(req)
        http_req = mock_urlopen.call_args[0][0]
        body = json.loads(http_req.data.decode("utf-8"))
        assert body["gate_ref"] == "g1"
        assert body["decision"] == "approved"

    @patch("urllib.request.urlopen")
    def test_get_manifest_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({"name": "kernel", "v": "1"})
        result = client.get_manifest()
        assert result["name"] == "kernel"

    @patch("urllib.request.urlopen")
    def test_submit_plan_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse({})
        client.submit_plan("r1", {"steps": [1]})
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["plan"] == {"steps": [1]}

    @patch("urllib.request.urlopen")
    def test_query_trace_runtime_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse(
            {"run_id": "r1", "stages": {}}
        )
        result = client.query_trace_runtime("r1")
        assert result["run_id"] == "r1"

    @patch("urllib.request.urlopen")
    def test_stream_run_events_http(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse(
            {"events": [{"type": "started"}, {"type": "completed"}]}
        )
        events = []

        async def _collect():
            async for ev in client.stream_run_events("r1"):
                events.append(ev)

        asyncio.run(_collect())
        assert len(events) == 2

    @patch("urllib.request.urlopen")
    def test_http_error_raises_backend_error(
        self, mock_urlopen, client: KernelFacadeClient
    ) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        with pytest.raises(RuntimeAdapterBackendError):
            client.start_run("task-fail")


# ---------------------------------------------------------------------------
# Mode validation and fallback tests
# ---------------------------------------------------------------------------


class TestModeValidation:
    """Test mode selection, validation, and fallback behavior."""

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="mode must be 'direct' or 'http'"):
            KernelFacadeClient(mode="grpc")

    def test_direct_mode_without_facade_and_no_kernel_raises(self) -> None:
        """When agent-kernel is not importable and no facade given, ImportError."""
        with patch.object(
            KernelFacadeClient,
            "_try_import_facade",
            return_value=None,
        ):
            with pytest.raises(ImportError, match="agent-kernel is not importable"):
                KernelFacadeClient(mode="direct")

    def test_direct_mode_with_explicit_facade(self) -> None:
        facade = FakeFacade()
        client = KernelFacadeClient(mode="direct", facade=facade)
        run_id = client.start_run("t1")
        assert run_id == "run-0001"

    def test_http_mode_ignores_facade(self) -> None:
        """HTTP mode does not require or use a facade object."""
        client = KernelFacadeClient(mode="http", facade="ignored")
        # Should be http mode regardless of facade
        assert client._mode == "http"


# ---------------------------------------------------------------------------
# Builder integration test
# ---------------------------------------------------------------------------


class TestBuilderIntegration:
    """Verify SystemBuilder creates the right adapter based on config."""

    def test_mock_kernel_when_url_is_mock(self) -> None:
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.runtime_adapter.mock_kernel import MockKernel

        config = TraceConfig(kernel_base_url="mock")
        builder = SystemBuilder(config)
        kernel = builder.build_kernel()
        assert isinstance(kernel, MockKernel)

    def test_facade_client_when_url_is_set(self) -> None:
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        config = TraceConfig(kernel_base_url="http://kernel:9090")
        builder = SystemBuilder(config)
        kernel = builder.build_kernel()
        assert isinstance(kernel, KernelFacadeClient)
        assert kernel._mode == "http"
        assert kernel._base_url == "http://kernel:9090"
