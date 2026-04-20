"""Tests for hi_agent.llm.anthropic_gateway -- Anthropic Claude API gateway."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from hi_agent.llm import AnthropicLLMGateway, LLMProviderError, LLMTimeoutError
from hi_agent.llm.protocol import LLMRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_ANTHROPIC_RESPONSE: dict = {
    "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "Hello! How can I help you?"}],
    "model": "claude-sonnet-4-20250514",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 25, "output_tokens": 10},
}


def _patch_urlopen(raw_json: dict | None = None):
    """Return a context-manager that patches urllib.request.urlopen."""
    body = json.dumps(raw_json or _FAKE_ANTHROPIC_RESPONSE).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return patch(
        "hi_agent.llm.anthropic_gateway.urllib.request.urlopen",
        return_value=mock_resp,
    )


def _make_request(**kwargs) -> LLMRequest:
    defaults = {"messages": [{"role": "user", "content": "hi"}]}
    defaults.update(kwargs)
    return LLMRequest(**defaults)


# ---------------------------------------------------------------------------
# Request formatting
# ---------------------------------------------------------------------------


class TestRequestFormatting:
    """AnthropicLLMGateway builds correct Anthropic API requests."""

    def test_basic_request_payload(self) -> None:
        gw = AnthropicLLMGateway()
        req = _make_request(model="claude-sonnet-4-20250514")
        with _patch_urlopen() as mock_open:
            gw.complete(req)
        sent_req = mock_open.call_args[0][0]
        body = json.loads(sent_req.data.decode())
        assert body["model"] == "claude-sonnet-4-20250514"
        assert body["max_tokens"] == 4096
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert "system" not in body

    def test_system_message_extracted(self) -> None:
        """System message should be a top-level field, not in messages."""
        gw = AnthropicLLMGateway()
        req = _make_request(
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hi"},
            ]
        )
        with _patch_urlopen() as mock_open:
            gw.complete(req)
        body = json.loads(mock_open.call_args[0][0].data.decode())
        assert body["system"] == "You are helpful."
        assert all(m["role"] != "system" for m in body["messages"])

    def test_stop_sequences_included(self) -> None:
        gw = AnthropicLLMGateway()
        req = _make_request(stop_sequences=["###", "END"])
        with _patch_urlopen() as mock_open:
            gw.complete(req)
        body = json.loads(mock_open.call_args[0][0].data.decode())
        assert body["stop_sequences"] == ["###", "END"]

    def test_default_model_substitution(self) -> None:
        gw = AnthropicLLMGateway(default_model="claude-haiku-3")
        req = _make_request(model="default")
        with _patch_urlopen() as mock_open:
            gw.complete(req)
        body = json.loads(mock_open.call_args[0][0].data.decode())
        assert body["model"] == "claude-haiku-3"

    def test_x_api_key_header(self) -> None:
        gw = AnthropicLLMGateway(api_key_env="MY_KEY")
        req = _make_request()
        with patch.dict("os.environ", {"MY_KEY": "sk-ant-test123"}), _patch_urlopen() as mock_open:
            gw.complete(req)
        sent_req = mock_open.call_args[0][0]
        assert sent_req.get_header("X-api-key") == "sk-ant-test123"
        assert sent_req.get_header("Anthropic-version") == "2023-06-01"

    def test_url_endpoint(self) -> None:
        gw = AnthropicLLMGateway()
        req = _make_request()
        with _patch_urlopen() as mock_open:
            gw.complete(req)
        sent_req = mock_open.call_args[0][0]
        assert sent_req.full_url == "https://api.anthropic.com/v1/messages"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestResponseParsing:
    """AnthropicLLMGateway correctly parses Anthropic API responses."""

    def test_parse_content(self) -> None:
        gw = AnthropicLLMGateway()
        with _patch_urlopen():
            resp = gw.complete(_make_request())
        assert resp.content == "Hello! How can I help you?"

    def test_parse_model(self) -> None:
        gw = AnthropicLLMGateway()
        with _patch_urlopen():
            resp = gw.complete(_make_request())
        assert resp.model == "claude-sonnet-4-20250514"

    def test_parse_token_usage(self) -> None:
        gw = AnthropicLLMGateway()
        with _patch_urlopen():
            resp = gw.complete(_make_request())
        assert resp.usage.prompt_tokens == 25
        assert resp.usage.completion_tokens == 10
        assert resp.usage.total_tokens == 35

    def test_parse_end_turn_as_stop(self) -> None:
        gw = AnthropicLLMGateway()
        with _patch_urlopen():
            resp = gw.complete(_make_request())
        assert resp.finish_reason == "stop"

    def test_parse_max_tokens_as_length(self) -> None:
        raw = dict(_FAKE_ANTHROPIC_RESPONSE, stop_reason="max_tokens")
        gw = AnthropicLLMGateway()
        with _patch_urlopen(raw):
            resp = gw.complete(_make_request())
        assert resp.finish_reason == "length"

    def test_parse_stop_sequence(self) -> None:
        raw = dict(_FAKE_ANTHROPIC_RESPONSE, stop_reason="stop_sequence")
        gw = AnthropicLLMGateway()
        with _patch_urlopen(raw):
            resp = gw.complete(_make_request())
        assert resp.finish_reason == "stop"

    def test_multiple_content_blocks(self) -> None:
        raw = dict(
            _FAKE_ANTHROPIC_RESPONSE,
            content=[
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ],
        )
        gw = AnthropicLLMGateway()
        with _patch_urlopen(raw):
            resp = gw.complete(_make_request())
        assert resp.content == "Part 1\nPart 2"

    def test_empty_content_blocks(self) -> None:
        raw = dict(_FAKE_ANTHROPIC_RESPONSE, content=[])
        gw = AnthropicLLMGateway()
        with _patch_urlopen(raw):
            resp = gw.complete(_make_request())
        assert resp.content == ""

    def test_raw_preserved(self) -> None:
        gw = AnthropicLLMGateway()
        with _patch_urlopen():
            resp = gw.complete(_make_request())
        assert resp.raw["id"] == "msg_01XFDUDYJgAACzvnptvVoYEL"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """AnthropicLLMGateway raises appropriate errors."""

    def test_http_error_raises_provider_error(self) -> None:
        import urllib.error

        gw = AnthropicLLMGateway()
        fp = MagicMock()
        fp.read.return_value = b"rate limited"
        http_err = urllib.error.HTTPError(
            url="https://x", code=429, msg="Too Many Requests", hdrs={}, fp=fp
        )
        with patch(
            "hi_agent.llm.anthropic_gateway.urllib.request.urlopen",
            side_effect=http_err,
        ):
            with pytest.raises(LLMProviderError, match="429") as exc_info:
                gw.complete(_make_request())
            assert exc_info.value.status_code == 429

    def test_timeout_raises_timeout_error(self) -> None:
        import urllib.error

        gw = AnthropicLLMGateway()
        url_err = urllib.error.URLError(reason="timed out")
        with patch(
            "hi_agent.llm.anthropic_gateway.urllib.request.urlopen",
            side_effect=url_err,
        ), pytest.raises(LLMTimeoutError):
            gw.complete(_make_request())

    def test_connection_error_raises_provider_error(self) -> None:
        import urllib.error

        gw = AnthropicLLMGateway()
        url_err = urllib.error.URLError(reason="connection refused")
        with patch(
            "hi_agent.llm.anthropic_gateway.urllib.request.urlopen",
            side_effect=url_err,
        ), pytest.raises(LLMProviderError, match="connection refused"):
            gw.complete(_make_request())


# ---------------------------------------------------------------------------
# supports_model
# ---------------------------------------------------------------------------


class TestSupportsModel:
    """supports_model filters on claude- prefix."""

    def test_claude_model(self) -> None:
        gw = AnthropicLLMGateway()
        assert gw.supports_model("claude-sonnet-4-20250514") is True
        assert gw.supports_model("claude-3-opus-20240229") is True

    def test_non_claude_model(self) -> None:
        # supports_model() delegates validation to the provider, enabling use with
        # proxy endpoints (DashScope, etc.) that accept non-Claude model names.
        gw = AnthropicLLMGateway()
        assert gw.supports_model("gpt-4o") is True
        assert gw.supports_model("llama-3") is True
