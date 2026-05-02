"""LLM Streaming support for hi-agent.

Provides async streaming protocol and HTTP SSE implementation on top of httpx.
Designed to complement HTTPGateway without modifying it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from hi_agent.llm.errors import LLMProviderError, LLMTimeoutError
from hi_agent.llm.protocol import LLMRequest, TokenUsage
from hi_agent.observability.silent_degradation import record_silent_degradation

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

StreamDeltaType = Literal["text", "tool_use", "thinking", "usage", "stop"]

# Seconds of silence before we declare the stream stale
_STALE_STREAM_TIMEOUT = 90.0


# ---------------------------------------------------------------------------
# StreamDelta — immutable event emitted by the streaming gateway
# ---------------------------------------------------------------------------


# W31 T-24' decision: in-process streaming delta; tenant-agnostic.
# scope: process-internal
@dataclass(frozen=True)
class StreamDelta:
    """A single delta event from a streaming LLM response.

    Attributes:
        type: Category of this delta event.
        content: Text content or tool input delta (when applicable).
        tool_name: Name of the tool being called (type="tool_use").
        tool_id: Provider-assigned tool call identifier (type="tool_use").
        finish_reason: Why the stream stopped (type="stop").
        usage: Token usage snapshot (type="usage").
    """

    type: StreamDeltaType
    content: str | None = None
    tool_name: str | None = None
    tool_id: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class AsyncStreamingLLMGateway(Protocol):
    """Protocol for async streaming LLM gateways."""

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamDelta]:
        """Stream deltas for a given request.

        Yields:
            :class:`StreamDelta` events until the stream is complete.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# SSE parser helpers
# ---------------------------------------------------------------------------


class SseParser:
    """Stateless helper that converts raw SSE lines into :class:`StreamDelta` objects.

    The Anthropic Messages streaming API emits events like::

        event: content_block_delta
        data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

    This parser operates per-line and is designed for use inside an async
    line-iteration loop.
    """

    @staticmethod
    def parse_line(line: str) -> tuple[str, str] | None:
        """Parse a single raw SSE line.

        Args:
            line: A single text line from the SSE stream (without trailing newline).

        Returns:
            A ``(field, value)`` tuple where *field* is one of ``"event"`` or
            ``"data"``, or ``None`` if the line should be ignored (comments,
            blank lines, unknown fields).
        """
        line = line.strip()
        if not line or line.startswith(":"):
            return None
        if line.startswith("event:"):
            return ("event", line[len("event:") :].strip())
        if line.startswith("data:"):
            return ("data", line[len("data:") :].strip())
        return None

    @staticmethod
    def parse_event(event_type: str, data_str: str) -> StreamDelta | None:
        """Convert a fully-assembled SSE event into a :class:`StreamDelta`.

        Args:
            event_type: The value from the ``event:`` line (e.g. ``"content_block_delta"``).
            data_str: The raw JSON string from the corresponding ``data:`` line.

        Returns:
            A :class:`StreamDelta` if the event carries actionable information,
            otherwise ``None``.
        """
        if data_str in ("[DONE]", ""):
            return None

        try:
            data: dict[str, Any] = json.loads(data_str)
        except json.JSONDecodeError as exc:
            record_silent_degradation(
                component="llm.streaming.StreamParser._parse_event",
                reason="sse_json_decode_failed",
                exc=exc,
            )
            return None

        # ---- text delta ---------------------------------------------------
        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")
            if delta_type == "text_delta":
                return StreamDelta(type="text", content=delta.get("text", ""))
            if delta_type == "thinking_delta":
                return StreamDelta(type="thinking", content=delta.get("thinking", ""))
            if delta_type == "input_json_delta":
                # Partial tool input JSON
                return StreamDelta(type="tool_use", content=delta.get("partial_json", ""))
            return None

        # ---- tool_use block start -----------------------------------------
        if event_type == "content_block_start":
            cb = data.get("content_block", {})
            if cb.get("type") == "tool_use":
                return StreamDelta(
                    type="tool_use",
                    tool_name=cb.get("name"),
                    tool_id=cb.get("id"),
                    content=None,
                )
            return None

        # ---- message_delta (stop + usage) ---------------------------------
        if event_type == "message_delta":
            delta = data.get("delta", {})
            usage_raw = data.get("usage", {})
            finish_reason = delta.get("stop_reason")

            usage: TokenUsage | None = None
            if usage_raw:
                usage = TokenUsage(
                    prompt_tokens=usage_raw.get("input_tokens", 0),
                    completion_tokens=usage_raw.get("output_tokens", 0),
                    total_tokens=usage_raw.get("input_tokens", 0)
                    + usage_raw.get("output_tokens", 0),
                )

            if finish_reason:
                return StreamDelta(
                    type="stop",
                    finish_reason=finish_reason,
                    usage=usage,
                )
            if usage:
                return StreamDelta(type="usage", usage=usage)
            return None

        # ---- message_start (initial usage) --------------------------------
        if event_type == "message_start":
            msg = data.get("message", {})
            usage_raw = msg.get("usage", {})
            if usage_raw:
                usage = TokenUsage(
                    prompt_tokens=usage_raw.get("input_tokens", 0),
                    completion_tokens=usage_raw.get("output_tokens", 0),
                    total_tokens=usage_raw.get("input_tokens", 0)
                    + usage_raw.get("output_tokens", 0),
                )
                return StreamDelta(type="usage", usage=usage)
            return None

        # ---- message_stop -------------------------------------------------
        if event_type == "message_stop":
            return StreamDelta(type="stop", finish_reason="end_turn")

        return None


# ---------------------------------------------------------------------------
# HTTPStreamingGateway
# ---------------------------------------------------------------------------


class HTTPStreamingGateway:
    """Anthropic-compatible async streaming LLM gateway using httpx.

    Mirrors the constructor signature of :class:`~hi_agent.llm.http_gateway.HTTPGateway`
    so the two can be used interchangeably.  The underlying ``httpx.AsyncClient``
    reuses the same connection pool across calls.

    Args:
        base_url: Anthropic (or compatible) API base URL.
        api_key: Bearer token for authentication.
        model: Default model identifier.
        timeout: Per-request read timeout in seconds (also used as the pool
            connection timeout).
        pool_size: Maximum number of keep-alive connections in the pool.
    """

    def __init__(
        self,
        base_url: str = "https://api.anthropic.com",
        api_key: str = "",
        model: str = "claude-3-5-sonnet-20241022",
        timeout: float = 120.0,
        pool_size: int = 20,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = model
        self._timeout = timeout
        self._pool_size = pool_size
        # Rule 5: no self._client field — AsyncClient is constructed per-call
        # inside stream() via async with, so it is always loop-bound and never
        # shared across asyncio.run() boundaries (DF-18 class fix).
        self._parser = SseParser()

    def _make_client(self) -> httpx.AsyncClient:
        # Rule 5: per-call construction — caller must use this inside `async with`.
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=httpx.Timeout(self._timeout),
            limits=httpx.Limits(
                max_connections=self._pool_size * 5,
                max_keepalive_connections=self._pool_size,
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamDelta]:
        """Stream :class:`StreamDelta` events for *request*.

        Rule 5 (DF-18 class): AsyncClient is constructed per-call via
        ``async with`` so it is always bound to the running loop and never
        shared across event-loop boundaries.

        Yields:
            :class:`StreamDelta` events as they arrive from the provider.

        Raises:
            LLMTimeoutError: If no data is received for
                :data:`_STALE_STREAM_TIMEOUT` seconds, or on a hard httpx
                timeout.
            LLMProviderError: On HTTP 4xx/5xx or network errors.
        """
        from hi_agent.observability.spine_events import emit_llm_call

        model = request.model if request.model != "default" else self._default_model
        emit_llm_call(tenant_id="", profile_id="")
        payload = self._build_payload(request, model)

        # Rule 5: construct AsyncClient per-call inside the running loop
        # so no cross-loop resource is ever stored on self.  The previous
        # pattern stored self._client lazily and shared it across asyncio.run()
        # boundaries — DF-18 class bug.
        try:
            async with (
                self._make_client() as client,
                client.stream("POST", "/v1/messages", json=payload) as response,
            ):
                if response.status_code >= 400:
                    body = await response.aread()
                    raise LLMProviderError(
                        f"HTTP {response.status_code}: {body.decode(errors='replace')}",
                        status_code=response.status_code,
                    )

                async for delta in self._parse_sse_stream(response):
                    yield delta

        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Request timed out: {exc}") from exc
        except httpx.NetworkError as exc:
            raise LLMProviderError(f"Network error: {exc}") from exc
        except LLMProviderError:
            raise
        except LLMTimeoutError:
            raise

    async def aclose(self) -> None:
        """No-op: AsyncClient is now constructed per-call; nothing to close."""

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        """Build the Anthropic Messages API payload with stream=True."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.stop_sequences:
            payload["stop_sequences"] = request.stop_sequences
        return payload

    async def _parse_sse_stream(self, response: httpx.Response) -> AsyncIterator[StreamDelta]:
        """Iterate over raw SSE bytes and yield parsed :class:`StreamDelta` objects.

        Implements stale-stream detection: if no data arrives within
        :data:`_STALE_STREAM_TIMEOUT` seconds the iterator raises
        :class:`LLMTimeoutError`.
        """
        current_event: str = ""

        async def _next_line() -> str | None:
            """Return the next decoded line from the response, or None on EOF."""
            # aiter_lines() is a native httpx async iterator
            return None  # placeholder — replaced by direct iteration below

        # We iterate aiter_lines() ourselves so we can wrap each await with
        # asyncio.wait_for for stale-stream detection.
        line_iter = response.aiter_lines()
        while True:
            try:
                line: str = await asyncio.wait_for(
                    line_iter.__anext__(),
                    timeout=_STALE_STREAM_TIMEOUT,
                )
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise LLMTimeoutError(
                    f"Stream stale for {_STALE_STREAM_TIMEOUT}s — no data received"
                ) from exc

            parsed = self._parser.parse_line(line)
            if parsed is None:
                # Blank line = end of SSE event block; reset event name
                if line.strip() == "":
                    current_event = ""
                continue

            field, value = parsed
            if field == "event":
                current_event = value
            elif field == "data":
                if not current_event:
                    # Some providers send data-only events (OpenAI style)
                    current_event = "content_block_delta"
                delta = self._parser.parse_event(current_event, value)
                if delta is not None:
                    yield delta
                current_event = ""
