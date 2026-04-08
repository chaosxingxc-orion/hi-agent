"""Core LLM Gateway protocol and data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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
        messages: Conversation messages in ``[{"role": ..., "content": ...}]`` format.
        model: Model identifier; ``"default"`` lets the gateway choose.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate.
        stop_sequences: Optional stop sequences.
        metadata: Trace context forwarded through the gateway (run_id, stage_id, etc.).
    """

    messages: list[dict[str, str]]
    model: str = "default"
    temperature: float = 0.7
    max_tokens: int = 4096
    stop_sequences: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Structured response from LLM Gateway.

    Attributes:
        content: Generated text.
        model: Model that produced the response.
        usage: Token consumption for this call.
        finish_reason: Why generation stopped (``stop``, ``length``, ``content_filter``).
        raw: Provider-specific raw payload, kept for debugging.
    """

    content: str
    model: str
    usage: TokenUsage
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)


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
    """

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the response."""
        ...

    def supports_model(self, model: str) -> bool:
        """Return whether this gateway can serve the given model."""
        ...
