"""Core LLM Gateway protocol and data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


@dataclass
class TokenUsage:
    """Token consumption counters for a single LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMRequest:
    """Structured request to LLM Gateway.

    Attributes:
        messages: Conversation messages.  Each entry is a dict with ``role``
            and ``content``.  ``content`` may be a plain string *or* a list
            of content blocks (text / image) for multimodal requests.
        model: Model identifier; ``"default"`` lets the gateway choose.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate.
        stop_sequences: Optional stop sequences.
        metadata: Trace context forwarded through the gateway (run_id,
            stage_id, purpose, budget_remaining, complexity, etc.).
        thinking_budget: When > 0, enable extended thinking with this many
            budget tokens.  ``None`` defers to the gateway default
            (``default_thinking_budget`` constructor argument).  Set to 0
            to explicitly disable thinking even when a gateway default is
            configured.
    """

    messages: list[dict[str, Any]]
    model: str = "default"
    temperature: float = 0.7
    max_tokens: int = 4096
    stop_sequences: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    thinking_budget: int | None = None


@dataclass
class LLMResponse:
    """Structured response from LLM Gateway.

    Attributes:
        content: Generated text (concatenation of all text blocks).
        model: Model that produced the response.
        usage: Token consumption for this call.
        finish_reason: Why generation stopped (``stop``, ``length``,
            ``content_filter``).
        thinking: Extended-thinking content when thinking mode was active;
            empty string when not used.
        raw: Provider-specific raw payload, kept for debugging.
    """

    content: str
    model: str
    usage: TokenUsage
    finish_reason: str = "stop"
    thinking: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming LLM response.

    Attributes:
        delta: Incremental text generated in this chunk.
        thinking_delta: Incremental thinking content (empty when thinking
            mode is off or not yet active in this chunk).
        finish_reason: Non-None on the final chunk; indicates why
            generation stopped.
        usage: Token counts; populated only on the final chunk.
        model: Model identifier; populated on the first or final chunk.
    """

    delta: str = ""
    thinking_delta: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    model: str = ""


class AsyncLLMGateway(Protocol):
    """Async version of LLMGateway for use with asyncio contexts."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the response."""
        ...

    def supports_model(self, model: str) -> bool:
        """Return whether this gateway can serve the given model."""
        ...


class LLMGateway(Protocol):
    """Provider-decoupled LLM Gateway protocol.

    All LLM calls in hi-agent go through this gateway.
    Implementations can wrap OpenAI, Anthropic, local models, etc.

    The ``stream()`` method is optional; callers should check
    ``hasattr(gateway, "stream")`` before using it.
    """

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the full response."""
        ...

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamChunk]:
        """Stream the response token-by-token.

        Yields :class:`LLMStreamChunk` objects; the final chunk carries
        ``finish_reason`` and ``usage``.  Not all gateway implementations
        are required to implement this method.
        """
        ...

    def supports_model(self, model: str) -> bool:
        """Return whether this gateway can serve the given model."""
        ...
