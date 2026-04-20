"""Tests for hi_agent.llm.streaming — LLM streaming support.

Covers:
  - StreamDelta dataclass creation and immutability
  - SseParser line and event parsing for text, tool_use, and stop events
  - HTTPStreamingGateway.stream() end-to-end with mocked httpx responses
  - Stale-stream (90 s timeout) detection
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import httpx
import pytest
from hi_agent.llm.errors import LLMProviderError, LLMTimeoutError
from hi_agent.llm.protocol import LLMRequest, TokenUsage
from hi_agent.llm.streaming import (
    HTTPStreamingGateway,
    SseParser,
    StreamDelta,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse_lines(*events: tuple[str, dict]) -> list[str]:
    """Build a flat list of SSE text lines from (event_type, data_dict) pairs."""
    lines: list[str] = []
    for event_type, data in events:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")  # blank line = end of SSE event
    return lines


async def _async_lines(lines: list[str]) -> AsyncIterator[str]:
    """Yield strings as an async iterator (simulates httpx.Response.aiter_lines)."""
    for line in lines:
        yield line


# ---------------------------------------------------------------------------
# 1. StreamDelta creation
# ---------------------------------------------------------------------------


class TestStreamDeltaCreation:
    def test_text_delta(self):
        delta = StreamDelta(type="text", content="Hello")
        assert delta.type == "text"
        assert delta.content == "Hello"
        assert delta.tool_name is None
        assert delta.tool_id is None
        assert delta.finish_reason is None
        assert delta.usage is None

    def test_tool_use_delta(self):
        delta = StreamDelta(type="tool_use", tool_name="web_search", tool_id="tu_001")
        assert delta.type == "tool_use"
        assert delta.tool_name == "web_search"
        assert delta.tool_id == "tu_001"

    def test_stop_delta(self):
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        delta = StreamDelta(type="stop", finish_reason="end_turn", usage=usage)
        assert delta.type == "stop"
        assert delta.finish_reason == "end_turn"
        assert delta.usage is usage

    def test_usage_delta(self):
        usage = TokenUsage(prompt_tokens=20, completion_tokens=0, total_tokens=20)
        delta = StreamDelta(type="usage", usage=usage)
        assert delta.type == "usage"
        assert delta.usage.prompt_tokens == 20

    def test_thinking_delta(self):
        delta = StreamDelta(type="thinking", content="Let me think…")
        assert delta.type == "thinking"
        assert delta.content == "Let me think…"

    def test_frozen_immutability(self):
        delta = StreamDelta(type="text", content="abc")
        with pytest.raises((AttributeError, TypeError)):
            delta.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. SseParser — text delta
# ---------------------------------------------------------------------------


class TestSseParserTextDelta:
    def setup_method(self):
        self.parser = SseParser()

    def test_parse_line_event(self):
        result = self.parser.parse_line("event: content_block_delta")
        assert result == ("event", "content_block_delta")

    def test_parse_line_data(self):
        data_str = '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}'
        result = self.parser.parse_line(f"data: {data_str}")
        assert result == ("data", data_str)

    def test_parse_line_blank(self):
        assert self.parser.parse_line("") is None
        assert self.parser.parse_line("   ") is None

    def test_parse_line_comment(self):
        assert self.parser.parse_line(": keep-alive") is None

    def test_parse_event_text_delta(self):
        data = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello, world!"},
        }
        delta = self.parser.parse_event("content_block_delta", json.dumps(data))
        assert delta is not None
        assert delta.type == "text"
        assert delta.content == "Hello, world!"

    def test_parse_event_done_sentinel(self):
        assert self.parser.parse_event("content_block_delta", "[DONE]") is None

    def test_parse_event_invalid_json(self):
        assert self.parser.parse_event("content_block_delta", "not-json{") is None

    def test_parse_event_thinking_delta(self):
        data = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "Let me reason…"},
        }
        delta = self.parser.parse_event("content_block_delta", json.dumps(data))
        assert delta is not None
        assert delta.type == "thinking"
        assert delta.content == "Let me reason…"

    def test_parse_event_input_json_delta(self):
        data = {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
        }
        delta = self.parser.parse_event("content_block_delta", json.dumps(data))
        assert delta is not None
        assert delta.type == "tool_use"
        assert delta.content == '{"q":'


# ---------------------------------------------------------------------------
# 3. SseParser — tool_use
# ---------------------------------------------------------------------------


class TestSseParserToolUse:
    def setup_method(self):
        self.parser = SseParser()

    def test_parse_event_tool_use_block_start(self):
        data = {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_abc123",
                "name": "web_search",
                "input": {},
            },
        }
        delta = self.parser.parse_event("content_block_start", json.dumps(data))
        assert delta is not None
        assert delta.type == "tool_use"
        assert delta.tool_name == "web_search"
        assert delta.tool_id == "toolu_abc123"
        assert delta.content is None

    def test_parse_event_text_block_start_ignored(self):
        data = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        delta = self.parser.parse_event("content_block_start", json.dumps(data))
        assert delta is None


# ---------------------------------------------------------------------------
# 4. SseParser — stop / usage
# ---------------------------------------------------------------------------


class TestSseParserStop:
    def setup_method(self):
        self.parser = SseParser()

    def test_parse_event_message_delta_stop(self):
        data = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 42},
        }
        delta = self.parser.parse_event("message_delta", json.dumps(data))
        assert delta is not None
        assert delta.type == "stop"
        assert delta.finish_reason == "end_turn"
        assert delta.usage is not None
        assert delta.usage.completion_tokens == 42

    def test_parse_event_message_delta_usage_only(self):
        data = {
            "type": "message_delta",
            "delta": {},
            "usage": {"output_tokens": 10},
        }
        delta = self.parser.parse_event("message_delta", json.dumps(data))
        assert delta is not None
        assert delta.type == "usage"
        assert delta.usage.completion_tokens == 10

    def test_parse_event_message_start_usage(self):
        data = {
            "type": "message_start",
            "message": {
                "id": "msg_01",
                "type": "message",
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        }
        delta = self.parser.parse_event("message_start", json.dumps(data))
        assert delta is not None
        assert delta.type == "usage"
        assert delta.usage.prompt_tokens == 100

    def test_parse_event_message_stop(self):
        data = {"type": "message_stop"}
        delta = self.parser.parse_event("message_stop", json.dumps(data))
        assert delta is not None
        assert delta.type == "stop"
        assert delta.finish_reason == "end_turn"

    def test_parse_event_unknown_event_type(self):
        delta = self.parser.parse_event("ping", '{"type":"ping"}')
        assert delta is None


# ---------------------------------------------------------------------------
# 5. HTTPStreamingGateway.stream() — happy path
# ---------------------------------------------------------------------------


SSE_HAPPY_LINES = _sse_lines(
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_01",
                "role": "assistant",
                "usage": {"input_tokens": 50, "output_tokens": 0},
            },
        },
    ),
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": " world"},
        },
    ),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 2},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
)


class _FakeResponse:
    """Minimal fake for httpx.Response used in stream context manager."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self.status_code = status_code
        self._lines = lines

    async def aread(self) -> bytes:
        return b"error body"

    def aiter_lines(self) -> AsyncIterator[str]:
        return _async_lines(self._lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
class TestHTTPStreamingGatewayStream:
    def _make_gateway(self) -> HTTPStreamingGateway:
        gw = HTTPStreamingGateway(
            base_url="https://api.anthropic.com",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
        )
        return gw

    async def test_happy_path_yields_correct_deltas(self):
        gw = self._make_gateway()
        fake_response = _FakeResponse(SSE_HAPPY_LINES)

        # Patch the AsyncClient.stream context manager
        gw._client.stream = MagicMock(return_value=fake_response)

        request = LLMRequest(
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-3-5-sonnet-20241022",
        )

        deltas: list[StreamDelta] = []
        async for delta in gw.stream(request):
            deltas.append(delta)

        types = [d.type for d in deltas]
        # Expect: usage (message_start), text x2, stop (message_delta), stop (message_stop)
        assert "text" in types
        assert "stop" in types

        text_deltas = [d for d in deltas if d.type == "text"]
        assert len(text_deltas) == 2
        assert text_deltas[0].content == "Hello"
        assert text_deltas[1].content == " world"

        stop_deltas = [d for d in deltas if d.type == "stop"]
        assert len(stop_deltas) >= 1
        assert stop_deltas[0].finish_reason == "end_turn"

    async def test_http_error_raises_provider_error(self):
        gw = self._make_gateway()
        fake_response = _FakeResponse([], status_code=401)
        gw._client.stream = MagicMock(return_value=fake_response)

        request = LLMRequest(messages=[{"role": "user", "content": "Hi"}])

        with pytest.raises(LLMProviderError) as exc_info:
            async for _ in gw.stream(request):
                pass
        assert "401" in str(exc_info.value)

    async def test_network_error_raises_provider_error(self):
        gw = self._make_gateway()

        class _ErrorResponse:
            status_code = 200

            def aiter_lines(self):
                raise httpx.NetworkError("Connection reset")

            async def aread(self):
                return b""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        gw._client.stream = MagicMock(return_value=_ErrorResponse())
        request = LLMRequest(messages=[{"role": "user", "content": "Hi"}])

        with pytest.raises(LLMProviderError):
            async for _ in gw.stream(request):
                pass

    async def test_tool_use_stream(self):
        lines = _sse_lines(
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_xyz",
                        "name": "calculator",
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"x":1}'},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 5},
                },
            ),
        )
        gw = self._make_gateway()
        gw._client.stream = MagicMock(return_value=_FakeResponse(lines))

        request = LLMRequest(messages=[{"role": "user", "content": "Calculate"}])
        deltas = [d async for d in gw.stream(request)]

        tool_deltas = [d for d in deltas if d.type == "tool_use"]
        assert len(tool_deltas) >= 1
        # First tool_use delta should have tool_name and tool_id
        block_start = tool_deltas[0]
        assert block_start.tool_name == "calculator"
        assert block_start.tool_id == "toolu_xyz"

        stop_deltas = [d for d in deltas if d.type == "stop"]
        assert stop_deltas[0].finish_reason == "tool_use"


# ---------------------------------------------------------------------------
# 6. Stale stream timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStaleStreamTimeout:
    async def test_stale_stream_raises_timeout(self):
        """When a line takes longer than _STALE_STREAM_TIMEOUT to arrive,
        stream() must raise LLMTimeoutError.
        """

        async def _hanging_lines():
            yield "event: content_block_delta"
            # Simulate a hang longer than the stale timeout
            await asyncio.sleep(200)  # will be cancelled by wait_for
            yield 'data: {"delta":{"type":"text_delta","text":"late"}}'

        class _HangingResponse:
            status_code = 200

            def aiter_lines(self):
                return _hanging_lines()

            async def aread(self):
                return b""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        gw = HTTPStreamingGateway(api_key="test-key")
        gw._client.stream = MagicMock(return_value=_HangingResponse())

        request = LLMRequest(messages=[{"role": "user", "content": "Hi"}])

        # Patch _STALE_STREAM_TIMEOUT to a very short value so the test is fast
        import hi_agent.llm.streaming as streaming_mod

        original_timeout = streaming_mod._STALE_STREAM_TIMEOUT
        streaming_mod._STALE_STREAM_TIMEOUT = 0.05  # 50 ms

        try:
            with pytest.raises(LLMTimeoutError, match="stale"):
                async for _ in gw.stream(request):
                    pass
        finally:
            streaming_mod._STALE_STREAM_TIMEOUT = original_timeout

    async def test_normal_stream_does_not_timeout(self):
        """A fast-arriving stream must complete without raising LLMTimeoutError."""
        lines = _sse_lines(
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "fast"},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        gw = HTTPStreamingGateway(api_key="test-key")
        gw._client.stream = MagicMock(return_value=_FakeResponse(lines))

        request = LLMRequest(messages=[{"role": "user", "content": "Hi"}])
        deltas = [d async for d in gw.stream(request)]
        text_deltas = [d for d in deltas if d.type == "text"]
        assert text_deltas[0].content == "fast"
