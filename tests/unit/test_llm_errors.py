"""Unit tests for LLM error type hierarchy (Wave 1, W1-4).

Verifies that LLMTimeoutError is a subclass of LLMProviderError so that
retry loops in async_http_gateway and http_gateway catch timeouts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hi_agent.llm.errors import LLMProviderError, LLMTimeoutError


class TestLLMTimeoutErrorInheritance:
    """LLMTimeoutError must be a subclass of LLMProviderError."""

    def test_timeout_is_subclass_of_provider_error(self) -> None:
        """issubclass(LLMTimeoutError, LLMProviderError) must be True."""
        assert issubclass(LLMTimeoutError, LLMProviderError)

    def test_timeout_is_catchable_as_provider_error(self) -> None:
        """A raised LLMTimeoutError must be caught by except LLMProviderError."""
        caught = False
        try:
            raise LLMTimeoutError("timed out", status_code=None)
        except LLMProviderError:
            caught = True
        assert caught, "LLMTimeoutError was not caught by except LLMProviderError"

    def test_timeout_preserves_message(self) -> None:
        """LLMTimeoutError should carry the message through LLMProviderError.__init__."""
        exc = LLMTimeoutError("request timed out after 30s")
        assert "request timed out after 30s" in str(exc)

    def test_async_http_gateway_retries_on_timeout(self) -> None:
        """AsyncHTTPGateway retry loop must fire when LLMTimeoutError is raised.

        Mocks the inner gateway to simulate a real transient fault (timeout)
        followed by a successful response — fault injection is a legitimate
        mock use per P3 policy.
        """
        from hi_agent.llm.async_http_gateway import AsyncHTTPGateway
        from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage

        ok_response = LLMResponse(content="ok", model="m", usage=TokenUsage())
        inner = MagicMock()
        inner.complete = AsyncMock(side_effect=[LLMTimeoutError("timed out"), ok_response])

        gw = AsyncHTTPGateway.__new__(AsyncHTTPGateway)
        gw._inner = inner
        gw._max_retries = 1
        gw._retry_base = 0.0  # no actual sleep in test

        req = LLMRequest(messages=[], model="test-model")
        result = asyncio.run(gw.async_complete(req))
        assert result.content == "ok"
        assert inner.complete.call_count == 2, "Expected exactly 2 calls (1 initial + 1 retry)"
