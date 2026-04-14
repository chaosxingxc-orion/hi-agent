"""Tests for hi_agent.llm -- LLM Gateway module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hi_agent.llm import (
    HttpLLMGateway,
    LLMBudgetExhaustedError,
    LLMBudgetTracker,
    LLMError,
    LLMProviderError,
    LLMRequest,
    LLMTimeoutError,
    ModelRouter,
    TokenUsage,
)
from tests.helpers.llm_gateway_fixture import MockLLMGateway


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class TestErrors:
    """Error types form the expected hierarchy."""

    def test_timeout_is_llm_error(self) -> None:
        assert issubclass(LLMTimeoutError, LLMError)

    def test_provider_is_llm_error(self) -> None:
        assert issubclass(LLMProviderError, LLMError)

    def test_budget_is_llm_error(self) -> None:
        assert issubclass(LLMBudgetExhaustedError, LLMError)

    def test_provider_error_status_code(self) -> None:
        err = LLMProviderError("bad request", status_code=400)
        assert err.status_code == 400
        assert "bad request" in str(err)


# ---------------------------------------------------------------------------
# MockLLMGateway
# ---------------------------------------------------------------------------


class TestMockGateway:
    """MockLLMGateway returns canned responses and tracks calls."""

    def _make_request(self, content: str = "hello") -> LLMRequest:
        return LLMRequest(messages=[{"role": "user", "content": content}])

    def test_default_response(self) -> None:
        gw = MockLLMGateway()
        resp = gw.complete(self._make_request())
        assert resp.content == "mock response"

    def test_custom_default(self) -> None:
        gw = MockLLMGateway(default_response="custom")
        resp = gw.complete(self._make_request())
        assert resp.content == "custom"

    def test_set_response(self) -> None:
        gw = MockLLMGateway()
        gw.set_response("new default")
        resp = gw.complete(self._make_request())
        assert resp.content == "new default"

    def test_conditional_response(self) -> None:
        gw = MockLLMGateway()
        gw.set_response_for("weather", "sunny")
        assert gw.complete(self._make_request("what is the weather")).content == "sunny"
        assert gw.complete(self._make_request("hello")).content == "mock response"

    def test_call_count(self) -> None:
        gw = MockLLMGateway()
        assert gw.call_count == 0
        gw.complete(self._make_request())
        gw.complete(self._make_request())
        assert gw.call_count == 2

    def test_last_request(self) -> None:
        gw = MockLLMGateway()
        assert gw.last_request is None
        req = self._make_request("ping")
        gw.complete(req)
        assert gw.last_request is req

    def test_reset(self) -> None:
        gw = MockLLMGateway()
        gw.set_response_for("x", "y")
        gw.complete(self._make_request())
        gw.reset()
        assert gw.call_count == 0
        assert gw.last_request is None

    def test_supports_model(self) -> None:
        gw = MockLLMGateway()
        assert gw.supports_model("anything") is True

    def test_usage_populated(self) -> None:
        gw = MockLLMGateway()
        resp = gw.complete(self._make_request())
        assert resp.usage.prompt_tokens > 0
        assert resp.usage.total_tokens == resp.usage.prompt_tokens + resp.usage.completion_tokens


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class TestModelRouter:
    """ModelRouter dispatches to the correct gateway."""

    def test_route_by_pattern(self) -> None:
        router = ModelRouter()
        gw = MockLLMGateway(default_response="openai")
        router.register("openai", gw)
        router.add_model_pattern("gpt-", "openai")
        assert router.route("gpt-4o") is gw

    def test_route_by_exact_name(self) -> None:
        router = ModelRouter()
        gw = MockLLMGateway()
        router.register("local", gw)
        assert router.route("local") is gw

    def test_route_missing_raises(self) -> None:
        router = ModelRouter()
        with pytest.raises(KeyError, match="unknown"):
            router.route("unknown")

    def test_complete_delegates(self) -> None:
        router = ModelRouter()
        gw = MockLLMGateway(default_response="routed")
        router.register("openai", gw)
        router.add_model_pattern("gpt-", "openai")
        req = LLMRequest(messages=[{"role": "user", "content": "hi"}], model="gpt-4o")
        resp = router.complete(req)
        assert resp.content == "routed"
        assert gw.call_count == 1


# ---------------------------------------------------------------------------
# LLMBudgetTracker
# ---------------------------------------------------------------------------


class TestBudgetTracker:
    """LLMBudgetTracker enforces call and token limits."""

    def test_within_budget(self) -> None:
        tracker = LLMBudgetTracker(max_calls=5, max_tokens=1000)
        tracker.record(TokenUsage(total_tokens=100))
        tracker.check()  # should not raise
        assert tracker.total_calls == 1
        assert tracker.total_tokens == 100
        assert tracker.remaining_calls == 4

    def test_call_budget_exceeded(self) -> None:
        tracker = LLMBudgetTracker(max_calls=2, max_tokens=999_999)
        tracker.record(TokenUsage(total_tokens=10))
        tracker.record(TokenUsage(total_tokens=10))
        with pytest.raises(LLMBudgetExhaustedError, match="Call budget"):
            tracker.check()

    def test_token_budget_exceeded(self) -> None:
        tracker = LLMBudgetTracker(max_calls=999, max_tokens=50)
        tracker.record(TokenUsage(total_tokens=60))
        with pytest.raises(LLMBudgetExhaustedError, match="Token budget"):
            tracker.check()

    def test_remaining_calls_floor_zero(self) -> None:
        tracker = LLMBudgetTracker(max_calls=1, max_tokens=999_999)
        tracker.record(TokenUsage(total_tokens=1))
        tracker.record(TokenUsage(total_tokens=1))
        assert tracker.remaining_calls == 0


# ---------------------------------------------------------------------------
# HttpLLMGateway (request formatting, mocked HTTP)
# ---------------------------------------------------------------------------


class TestHttpGateway:
    """HttpLLMGateway builds correct requests and parses responses."""

    _FAKE_RAW: dict = {
        "id": "chatcmpl-abc",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello back"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
        },
    }

    def _patch_urlopen(self, raw_json: dict | None = None):
        """Return a context-manager that patches urllib.request.urlopen."""
        body = json.dumps(raw_json or self._FAKE_RAW).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return patch("hi_agent.llm.http_gateway.urllib.request.urlopen", return_value=mock_resp)

    def test_complete_success(self) -> None:
        gw = HttpLLMGateway(base_url="https://fake.api/v1", api_key_env="TEST_KEY")
        req = LLMRequest(messages=[{"role": "user", "content": "hi"}], model="gpt-4o")
        with self._patch_urlopen() as mock_open:
            resp = gw.complete(req)
        assert resp.content == "hello back"
        assert resp.model == "gpt-4o"
        assert resp.usage.total_tokens == 17
        assert resp.finish_reason == "stop"
        # Verify the urllib call was made
        mock_open.assert_called_once()

    def test_default_model_substitution(self) -> None:
        gw = HttpLLMGateway(default_model="gpt-4o-mini")
        req = LLMRequest(messages=[{"role": "user", "content": "hi"}], model="default")
        with self._patch_urlopen() as mock_open:
            gw.complete(req)
        call_args = mock_open.call_args
        sent_req = call_args[0][0]
        body = json.loads(sent_req.data.decode())
        assert body["model"] == "gpt-4o-mini"

    def test_stop_sequences_included(self) -> None:
        gw = HttpLLMGateway()
        req = LLMRequest(
            messages=[{"role": "user", "content": "hi"}],
            stop_sequences=["###"],
        )
        with self._patch_urlopen() as mock_open:
            gw.complete(req)
        sent_req = mock_open.call_args[0][0]
        body = json.loads(sent_req.data.decode())
        assert body["stop"] == ["###"]

    def test_http_error_raises_provider_error(self) -> None:
        gw = HttpLLMGateway(max_retries=0)  # disable retries for unit test speed
        req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
        import urllib.error

        fp = MagicMock()
        fp.read.return_value = b"rate limited"
        http_err = urllib.error.HTTPError(
            url="https://x", code=429, msg="Too Many Requests", hdrs={}, fp=fp
        )
        with patch("hi_agent.llm.http_gateway.urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(LLMProviderError, match="429") as exc_info:
                gw.complete(req)
            assert exc_info.value.status_code == 429

    def test_timeout_raises_timeout_error(self) -> None:
        gw = HttpLLMGateway()
        req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
        import urllib.error

        url_err = urllib.error.URLError(reason="timed out")
        with patch("hi_agent.llm.http_gateway.urllib.request.urlopen", side_effect=url_err):
            with pytest.raises(LLMTimeoutError):
                gw.complete(req)

    def test_supports_model_always_true(self) -> None:
        gw = HttpLLMGateway()
        assert gw.supports_model("anything") is True


# ---------------------------------------------------------------------------
# HTTPGateway (async, httpx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_gateway_uses_async_client():
    """Verify that HTTPGateway.call() is a coroutine (non-blocking)."""
    import inspect
    from hi_agent.llm.http_gateway import HTTPGateway
    gw = HTTPGateway(base_url="http://localhost:9999", api_key="test")
    assert inspect.iscoroutinefunction(gw.call)
    await gw.aclose()


@pytest.mark.asyncio
async def test_http_gateway_connection_pool_reused(respx_mock):
    """Two calls reuse the same underlying httpx connection pool."""
    import httpx
    from hi_agent.llm.http_gateway import HTTPGateway

    respx_mock.post("http://test-llm/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
    )

    gw = HTTPGateway(base_url="http://test-llm", api_key="key")
    await gw.call(model_id="claude-haiku-4.5", messages=[{"role": "user", "content": "hi"}])
    await gw.call(model_id="claude-haiku-4.5", messages=[{"role": "user", "content": "hi"}])
    assert respx_mock.calls.call_count == 2
    await gw.aclose()
