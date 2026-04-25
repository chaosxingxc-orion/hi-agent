"""Verify HTTPGateway preserves base_url path segments across v1/v2/custom.

Regression guard for the 2026-04-21 incident where
``self._client.post("/v1/chat/completions", ...)`` overrode the base_url path
for MaaS glm-5.1 (base_url ends in ``/v2``) and returned 404.

Also guards the P0-2 dev-smoke clamp — HttpLLMGateway must not clamp the
timeout/retries when an API key is present.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from hi_agent.llm.http_gateway import HTTPGateway, HttpLLMGateway


def _capture_url(captured: list[str]) -> httpx.MockTransport:
    """Build a MockTransport that records the request URL and returns a stub."""

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "id": "x",
                "model": "m",
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    return httpx.MockTransport(_handler)


@pytest.mark.parametrize(
    "base_url,expected_suffix",
    [
        ("https://api.openai.com/v1", "/v1/chat/completions"),
        ("https://api.modelarts-maas.com/v2", "/v2/chat/completions"),
        ("https://example.com/custom/path", "/custom/path/chat/completions"),
    ],
)
def test_base_url_path_is_preserved(base_url: str, expected_suffix: str) -> None:
    """HTTPGateway must call {base_url}/chat/completions regardless of path segment."""
    gw = HTTPGateway(base_url=base_url, api_key="k")
    captured: list[str] = []
    gw._client = httpx.AsyncClient(base_url=gw._base_url, transport=_capture_url(captured))

    from hi_agent.llm.protocol import LLMRequest

    req = LLMRequest(model="default", messages=[{"role": "user", "content": "hi"}])

    asyncio.run(gw._direct_complete(req))

    assert captured, "no request captured"
    assert captured[0].endswith(expected_suffix), (
        f"expected URL to end with {expected_suffix!r}, got {captured[0]!r}"
    )


def test_dev_smoke_clamp_skipped_when_api_key_present(monkeypatch) -> None:
    """HttpLLMGateway must not clamp timeout/retries when credentials are set."""
    monkeypatch.setenv("OPENAI_API_KEY", "present")
    gw = HttpLLMGateway(timeout_seconds=120, max_retries=3, runtime_mode="dev-smoke")
    assert gw._timeout == 120
    assert gw._max_retries == 3


def test_dev_smoke_clamp_applies_when_api_key_absent(monkeypatch) -> None:
    """HttpLLMGateway clamps to 3s/0-retries only when credentials are missing."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gw = HttpLLMGateway(timeout_seconds=120, max_retries=3, runtime_mode="dev-smoke")
    assert gw._timeout == 3
    assert gw._max_retries == 0
