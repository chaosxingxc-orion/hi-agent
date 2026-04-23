"""Regression guard for the 2026-04-22 shared-gateway event-loop-lifetime defect.

The canonical path is the live Volces regression:

* Build one async ``HTTPGateway`` through the e2e live config fixture.
* Drive five sequential sync-facing calls through ``SyncBridge``.
* Assert that the gateway keeps the same ``_client`` object the whole time.
* Assert that each response returns non-empty content.

The file also keeps an explicit T2/offline MockTransport guard for local
regression checks when live credentials are unavailable.
"""

from __future__ import annotations

import json

import httpx
import pytest
from hi_agent.llm.protocol import LLMRequest
from hi_agent.runtime.sync_bridge import get_bridge


def _minimal_request(model: str, index: int) -> LLMRequest:
    """Build a small live-friendly request."""
    return LLMRequest(
        model=model,
        messages=[
            {
                "role": "user",
                "content": f"Final answer only, no analysis: ready {index}.",
            }
        ],
        temperature=0.0,
        max_tokens=1024,
    )


@pytest.mark.integration
@pytest.mark.live_api
def test_gateway_shared_across_five_sequential_real_calls(
    live_llm_config, volces_async_gateway
) -> None:
    """Five sequential live calls on one shared gateway must all succeed."""
    gateway = volces_async_gateway
    bridge = get_bridge()
    client_before = gateway._client

    responses = []
    for index in range(5):
        request = _minimal_request(live_llm_config.default_model, index)
        responses.append(bridge.call_sync(gateway.complete(request)))

    assert len(responses) == 5
    for idx, response in enumerate(responses):
        assert response is not None, f"call {idx} returned None"
        assert response.content.strip(), f"call {idx} returned empty content"

    assert gateway._client is client_before, (
        "HTTPGateway._client was replaced between live calls; the shared-pool "
        "invariant regressed and the 04-22 defect may recur."
    )


def _mock_openai_response(request: httpx.Request) -> httpx.Response:
    """Return a minimal OpenAI-compatible chat completion response."""
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "pong"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        "model": "mock-model",
    }
    return httpx.Response(200, content=json.dumps(payload).encode("utf-8"))


@pytest.mark.integration
def test_gateway_shared_across_three_sequential_mock_calls_t2_offline() -> None:
    """T2/offline regression: MockTransport path still keeps one AsyncClient."""
    from hi_agent.llm.http_gateway import HTTPGateway

    gateway = HTTPGateway(
        base_url="https://api.example.invalid/v1",
        api_key="sk-test-regression",
        default_model="mock-model",
        timeout=5.0,
        max_retries=0,
    )

    call_counter = {"n": 0}

    def _counting_handler(request: httpx.Request) -> httpx.Response:
        call_counter["n"] += 1
        return _mock_openai_response(request)

    gateway._client = httpx.AsyncClient(
        base_url="https://api.example.invalid/v1",
        headers={
            "Authorization": "Bearer sk-test-regression",
            "Content-Type": "application/json",
        },
        transport=httpx.MockTransport(_counting_handler),
        timeout=httpx.Timeout(5.0),
    )
    client_before = gateway._client
    bridge = get_bridge()

    results: list[object] = []
    for i in range(3):
        req = LLMRequest(
            model="mock-model",
            messages=[{"role": "user", "content": f"ping {i}"}],
        )
        results.append(bridge.call_sync(gateway.complete(req)))

    assert len(results) == 3
    for i, resp in enumerate(results):
        assert resp is not None, f"call {i} returned None"
        text = getattr(resp, "text", None) or getattr(resp, "content", None)
        assert text, f"call {i} returned empty response: {resp!r}"

    assert call_counter["n"] == 3, (
        f"MockTransport must have been hit 3 times; got {call_counter['n']}"
    )
    assert gateway._client is client_before, (
        "HTTPGateway._client was replaced between calls; the fix is no longer "
        "honoring the shared-pool invariant and the 04-22 defect may recur."
    )

    bridge.call_sync(gateway._client.aclose())
