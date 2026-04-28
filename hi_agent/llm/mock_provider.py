"""Deterministic mock LLM provider for replay testing.

This module provides a synchronous ``MockLLMProvider`` that satisfies the
``LLMGateway`` protocol without making any real network calls.  When a
``seed`` is supplied, the same seed + same last message always returns the
same response text, enabling byte-stable replay tests.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

from hi_agent.llm.protocol import LLMRequest, LLMResponse, LLMStreamChunk, TokenUsage


class MockLLMProvider:
    """Deterministic mock LLM gateway for unit and integration tests.

    Args:
        seed: Optional integer seed.  When set, ``complete()`` derives its
            response text deterministically from ``seed`` and the content of
            the last message, so identical inputs always produce identical
            outputs.  When ``None``, a fixed generic response is returned.
        model: Model string reported in every response.
    """

    def __init__(self, seed: int | None = None, model: str = "mock-model") -> None:
        self._seed = seed
        self._model = model

    def _derive_response(self, request: LLMRequest) -> str:
        if self._seed is None:
            return "mock response"
        last_msg = request.messages[-1] if request.messages else {}
        # Non-security fingerprint used only for test determinism:
        msg_digest = hashlib.md5(str(last_msg).encode()).hexdigest()[:8]
        return f"mock_response_seed_{self._seed}_input_{msg_digest}"

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a deterministic mock response."""
        text = self._derive_response(request)
        wc = len(text.split())
        return LLMResponse(
            content=text,
            model=self._model,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=wc, total_tokens=10 + wc),
            finish_reason="stop",
        )

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamChunk]:
        """Yield a single chunk containing the full deterministic response."""
        text = self._derive_response(request)
        wc = len(text.split())
        yield LLMStreamChunk(
            delta=text,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=wc, total_tokens=10 + wc),
            model=self._model,
        )

    def supports_model(self, model: str) -> bool:
        """Accept any model string."""
        return True
