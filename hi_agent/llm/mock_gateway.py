"""Deterministic mock gateway for testing."""

from __future__ import annotations

from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage


class MockLLMGateway:
    """Deterministic mock for testing.  Returns canned responses.

    By default every ``complete`` call returns *default_response*.  Use
    :meth:`set_response_for` to return different content when the last
    user message contains a given substring.
    """

    def __init__(self, default_response: str = "mock response") -> None:
        self._default_response = default_response
        self._conditional: list[tuple[str, str]] = []
        self._call_count = 0
        self._last_request: LLMRequest | None = None

    # -- LLMGateway protocol --------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a canned response, recording the call for assertions."""
        self._call_count += 1
        self._last_request = request

        content = self._resolve(request)
        return LLMResponse(
            content=content,
            model=request.model,
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=len(content),
                total_tokens=10 + len(content),
            ),
        )

    def supports_model(self, model: str) -> bool:  # noqa: ARG002
        """Mock gateway claims support for every model."""
        return True

    # -- Test helpers ----------------------------------------------------------

    def set_response(self, content: str) -> None:
        """Override the default response text."""
        self._default_response = content

    def set_response_for(self, message_contains: str, content: str) -> None:
        """Return *content* when the last user message contains *message_contains*."""
        self._conditional.append((message_contains, content))

    @property
    def call_count(self) -> int:
        """Number of ``complete`` calls made so far."""
        return self._call_count

    @property
    def last_request(self) -> LLMRequest | None:
        """The most recent request, or ``None`` if no calls yet."""
        return self._last_request

    def reset(self) -> None:
        """Clear call history and conditional responses."""
        self._call_count = 0
        self._last_request = None
        self._conditional.clear()

    # -- internals -------------------------------------------------------------

    def _resolve(self, request: LLMRequest) -> str:
        """Pick the response string based on conditional rules."""
        last_user = ""
        for msg in reversed(request.messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break
        for substr, content in self._conditional:
            if substr in last_user:
                return content
        return self._default_response
