"""Contract tests: verify adapter-to-kernel binding is consistent.

These tests assert:
- HTTP paths in KernelFacadeClient match the agent_kernel HTTP server route table
- HTTP body field names match serializer expectations
- Protocol signatures (run_id param ordering) are correct
- ResilientKernelAdapter buffers all mutating methods
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import patch

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient
from hi_agent.runtime_adapter.resilient_kernel_adapter import _WRITE_METHODS


class _FakeResponse:
    """Minimal urllib response stub."""

    def __init__(self, body: dict) -> None:
        self._data = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        pass


def _http_client() -> KernelFacadeClient:
    return KernelFacadeClient(mode="http", base_url="http://kernel-test:9090")


def _captured_request(mock_open: object) -> object:
    return mock_open.call_args[0][0]  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Stage lifecycle paths
# ---------------------------------------------------------------------------


def test_open_stage_http_path_and_method() -> None:
    client = _http_client()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.open_stage("run-1", "stage-A")
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/runs/run-1/stages/stage-A/open"
        assert req.method == "POST"


def test_mark_stage_state_http_path_and_method() -> None:
    client = _http_client()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.mark_stage_state("run-1", "stage-A", StageState.ACTIVE)
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/runs/run-1/stages/stage-A/state"
        assert req.method == "PUT"


# ---------------------------------------------------------------------------
# Branch lifecycle paths
# ---------------------------------------------------------------------------


def test_open_branch_http_path_and_method() -> None:
    client = _http_client()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.open_branch("run-1", "stage-A", "branch-X")
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/runs/run-1/branches"
        assert req.method == "POST"


def test_mark_branch_state_http_path_and_method() -> None:
    client = _http_client()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.mark_branch_state("run-1", "stage-A", "branch-X", "completed")
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/runs/run-1/branches/branch-X/state"
        assert req.method == "PUT"


# ---------------------------------------------------------------------------
# Signal body field names
# ---------------------------------------------------------------------------


def test_signal_run_http_body_field_names() -> None:
    client = _http_client()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.signal_run("run-1", "my_signal", {"k": "v"})
        req = _captured_request(mock_open)
        body = json.loads(req.data.decode())
        assert "signal_type" in body, "must send signal_type not signal"
        assert "signal_payload" in body, "must send signal_payload not payload"
        assert "signal" not in body
        assert "payload" not in body
        assert body["signal_type"] == "my_signal"
        assert body["signal_payload"] == {"k": "v"}


# ---------------------------------------------------------------------------
# Human gate paths
# ---------------------------------------------------------------------------


def test_open_human_gate_http_path() -> None:
    client = _http_client()
    gate_req = HumanGateRequest(
        run_id="run-1",
        gate_type="final_approval",
        gate_ref="gate-1",
        context={},
        timeout_s=300,
    )
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.open_human_gate(gate_req)
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/runs/run-1/human-gates"
        assert req.method == "POST"


def test_submit_approval_http_path() -> None:
    client = _http_client()
    appr = ApprovalRequest(
        run_id="run-1",
        gate_ref="gate-1",
        decision="approved",
        reviewer_id="u1",
        comment=None,
    )
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.submit_approval(appr)
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/runs/run-1/approval"
        assert req.method == "POST"


# ---------------------------------------------------------------------------
# Task view paths
# ---------------------------------------------------------------------------


def test_record_task_view_http_path() -> None:
    client = _http_client()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"task_view_id": "tv-1"})
        client.record_task_view("tv-1", {"run_id": "run-1", "selected_model_role": "heavy"})
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/runs/run-1/task-views"
        assert req.method == "POST"


def test_bind_task_view_to_decision_http_path_and_method() -> None:
    client = _http_client()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse({"ok": True})
        client.bind_task_view_to_decision("tv-1", "dec-ref-123")
        req = _captured_request(mock_open)
        assert req.full_url == "http://kernel-test:9090/task-views/tv-1/decision"
        assert req.method == "PUT"


# ---------------------------------------------------------------------------
# Protocol signature assertions
# ---------------------------------------------------------------------------


def test_open_stage_protocol_has_run_id_first() -> None:
    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

    sig = inspect.signature(RuntimeAdapter.open_stage)
    params = list(sig.parameters.keys())
    # params[0] is 'self'
    assert params[1] == "run_id", f"open_stage first param must be run_id, got {params}"
    assert params[2] == "stage_id"


def test_mark_stage_state_protocol_has_run_id_first() -> None:
    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

    sig = inspect.signature(RuntimeAdapter.mark_stage_state)
    params = list(sig.parameters.keys())
    assert params[1] == "run_id", f"mark_stage_state first param must be run_id, got {params}"
    assert params[2] == "stage_id"
    assert params[3] == "target"


def test_async_adapter_start_run_matches_protocol() -> None:
    from hi_agent.runtime_adapter.async_kernel_facade_adapter import AsyncKernelFacadeAdapter
    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

    proto_sig = inspect.signature(RuntimeAdapter.start_run)
    adapter_sig = inspect.signature(AsyncKernelFacadeAdapter.start_run)
    assert list(proto_sig.parameters.keys()) == list(adapter_sig.parameters.keys()), (
        f"AsyncKernelFacadeAdapter.start_run params {list(adapter_sig.parameters.keys())} "
        f"must match protocol {list(proto_sig.parameters.keys())}"
    )


# ---------------------------------------------------------------------------
# ResilientKernelAdapter write-method completeness
# ---------------------------------------------------------------------------


def test_resilient_adapter_write_methods_includes_all_mutating_ops() -> None:
    assert "resume_run" in _WRITE_METHODS
    assert "signal_run" in _WRITE_METHODS
    assert "open_stage" in _WRITE_METHODS
    assert "mark_stage_state" in _WRITE_METHODS
    assert "start_run" in _WRITE_METHODS
    assert "cancel_run" in _WRITE_METHODS
