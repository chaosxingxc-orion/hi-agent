"""Integration tests for HttpKernelClient auth/idempotency headers."""

from __future__ import annotations

from typing import Any

from hi_agent.runtime_adapter.kernel_client import HttpKernelClient


class _DummyResponse:
    """Minimal response stub."""

    status = 200

    def read(self) -> bytes:
        return b"{}"


def test_http_kernel_client_includes_bearer_authorization_header_when_token_provided() -> None:
    """Configured auth token should be sent as a bearer Authorization header."""
    captured_headers: dict[str, str] = {}

    def opener(request, *, timeout: float):
        _ = timeout
        captured_headers.update({key.lower(): value for key, value in request.header_items()})
        return _DummyResponse()

    client = HttpKernelClient(
        "http://kernel.local/api",
        opener=opener,
        auth_token="secret-token",
    )

    client.open_stage({"stage_id": "S1"})

    assert captured_headers["authorization"] == "Bearer secret-token"


def test_http_kernel_client_includes_idempotency_header_when_factory_returns_key() -> None:
    """Configured idempotency factory should provide request header value."""
    captured_headers: dict[str, str] = {}
    captured_factory_inputs: list[tuple[str, dict[str, Any]]] = []

    def key_factory(operation: str, payload: dict[str, Any]) -> str | None:
        captured_factory_inputs.append((operation, payload))
        return "idem-123"

    def opener(request, *, timeout: float):
        _ = timeout
        captured_headers.update({key.lower(): value for key, value in request.header_items()})
        return _DummyResponse()

    client = HttpKernelClient(
        "http://kernel.local/api",
        opener=opener,
        idempotency_key_factory=key_factory,
    )

    payload = {"task_view_id": "tv-1", "content": {"x": 1}}
    client.record_task_view(payload)

    assert captured_factory_inputs == [("record_task_view", payload)]
    assert captured_headers["idempotency-key"] == "idem-123"


def test_http_kernel_client_skips_idempotency_header_when_factory_returns_none() -> None:
    """No idempotency key should be added when factory returns None."""
    captured_headers: dict[str, str] = {}

    def opener(request, *, timeout: float):
        _ = timeout
        captured_headers.update({key.lower(): value for key, value in request.header_items()})
        return _DummyResponse()

    client = HttpKernelClient(
        "http://kernel.local/api",
        opener=opener,
        idempotency_key_factory=lambda operation, payload: None,
    )

    client.mark_stage_state({"stage_id": "S1", "target": "active"})

    assert "idempotency-key" not in captured_headers
