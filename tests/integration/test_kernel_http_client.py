"""Integration tests for HttpKernelClient transport behavior."""

from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest
from hi_agent.runtime_adapter.kernel_client import HttpKernelClient


class _DummyResponse:
    """Minimal context-managed response stub."""

    def __init__(self, *, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> _DummyResponse:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        _ = (exc_type, exc, traceback)
        return False

    def read(self) -> bytes:
        return self._body


def test_http_kernel_client_posts_json_to_operation_paths() -> None:
    """Default endpoint mode should post JSON to /<operation> paths."""
    captured: list[tuple[str, str, dict[str, object], float]] = []

    def opener(request, *, timeout: float):
        body = json.loads(request.data.decode("utf-8"))
        captured.append((request.full_url, request.get_method(), body, timeout))
        return _DummyResponse(status=200, body=b'{"ok": true}')

    client = HttpKernelClient("http://kernel.local/api", timeout_seconds=2.5, opener=opener)

    assert client.open_stage({"stage_id": "S1"}) == {"ok": True}
    assert client.mark_stage_state({"stage_id": "S1", "target": "active"}) == {"ok": True}
    assert client.record_task_view({"task_view_id": "tv-1", "content": {"x": 1}}) == {"ok": True}

    assert captured == [
        (
            "http://kernel.local/api/open_stage",
            "POST",
            {"stage_id": "S1"},
            2.5,
        ),
        (
            "http://kernel.local/api/mark_stage_state",
            "POST",
            {"stage_id": "S1", "target": "active"},
            2.5,
        ),
        (
            "http://kernel.local/api/record_task_view",
            "POST",
            {"task_view_id": "tv-1", "content": {"x": 1}},
            2.5,
        ),
    ]


def test_http_kernel_client_uses_generic_operations_endpoint() -> None:
    """Endpoints ending with /operations should carry operation in payload."""
    captured: list[tuple[str, dict[str, object]]] = []

    def opener(request, *, timeout: float):
        _ = timeout
        body = json.loads(request.data.decode("utf-8"))
        captured.append((request.full_url, body))
        return _DummyResponse(status=200, body=b'{"accepted": true}')

    client = HttpKernelClient("http://kernel.local/operations", timeout_seconds=1.0, opener=opener)

    assert client.open_stage({"stage_id": "S1"}) == {"accepted": True}

    assert captured == [
        (
            "http://kernel.local/operations",
            {"operation": "open_stage", "payload": {"stage_id": "S1"}},
        )
    ]


def test_http_kernel_client_maps_http_errors_to_runtime_error() -> None:
    """HTTP transport failures should be normalized with deterministic messages."""

    def opener(request, *, timeout: float):
        _ = timeout
        raise HTTPError(
            url=request.full_url,
            code=503,
            msg="service unavailable",
            hdrs=None,
            fp=None,
        )

    client = HttpKernelClient("http://kernel.local/api", timeout_seconds=1.0, opener=opener)

    with pytest.raises(RuntimeError) as exc_info:
        client.open_stage({"stage_id": "S1"})

    assert str(exc_info.value) == "Kernel HTTP client request failed during 'open_stage': HTTP 503."


def test_http_kernel_client_maps_invalid_json_response() -> None:
    """Invalid JSON in response body should raise normalized RuntimeError."""

    def opener(request, *, timeout: float):
        _ = (request, timeout)
        return _DummyResponse(status=200, body=b"{not-json")

    client = HttpKernelClient("http://kernel.local/api", timeout_seconds=1.0, opener=opener)

    with pytest.raises(RuntimeError) as exc_info:
        client.record_task_view({"task_view_id": "tv-1", "content": {"x": 1}})

    assert str(exc_info.value) == (
        "Kernel HTTP client request failed during 'record_task_view': invalid JSON response."
    )
