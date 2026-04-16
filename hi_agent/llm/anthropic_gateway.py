"""LLM Gateway for Anthropic Claude API (and compatible endpoints).

Uses stdlib urllib for non-streaming requests and httpx for streaming.
No anthropic SDK dependency.

Anthropic API specifics:
- POST to /v1/messages (not /v1/chat/completions)
- Uses x-api-key header (not Bearer token)
- Streaming via SSE with typed event objects
- Extended thinking via "thinking" top-level field
- Multimodal via content block lists in messages
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Iterator

import httpx

from hi_agent.llm.errors import LLMProviderError, LLMTimeoutError
from hi_agent.llm.protocol import LLMRequest, LLMResponse, LLMStreamChunk, TokenUsage

_logger = logging.getLogger(__name__)

_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
_ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicLLMGateway:
    """LLM Gateway for Anthropic Claude API and compatible endpoints.

    Features:
    - Synchronous ``complete()`` via stdlib urllib
    - Streaming ``stream()`` via httpx SSE parsing
    - Extended thinking via ``thinking_budget`` (per-request or gateway default)
    - Multimodal inputs: ``messages[].content`` may be a list of content blocks
      (``{"type": "text", "text": "..."}`` or ``{"type": "image", "source": {...}}``)

    Args:
        api_key_env: Environment variable that holds the API key.
        default_model: Model to use when the request specifies ``"default"``.
        timeout_seconds: HTTP request timeout.
        base_url: Base URL for the API endpoint (no trailing slash).
            Override for third-party Anthropic-compatible proxies.
        default_thinking_budget: Default budget tokens for extended thinking.
            ``None`` means thinking is off by default.  Per-request
            ``LLMRequest.thinking_budget`` takes precedence.
    """

    def __init__(
        self,
        api_key_env: str = "ANTHROPIC_API_KEY",
        default_model: str = "claude-sonnet-4-6",
        timeout_seconds: int = 120,
        base_url: str = _ANTHROPIC_BASE_URL,
        default_thinking_budget: int | None = None,
    ) -> None:
        """Initialize AnthropicLLMGateway."""
        self._api_key_env = api_key_env
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._base_url = base_url.rstrip("/")
        self._default_thinking_budget = default_thinking_budget

    # -- LLMGateway protocol --------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a messages request and return a structured response.

        Raises:
            LLMTimeoutError: If the HTTP call exceeds *timeout_seconds*.
            LLMProviderError: On any non-200 HTTP response or connection failure.
        """
        model = request.model if request.model != "default" else self._default_model
        payload = self._build_payload(request, model)
        raw = self._post(payload)
        return self._parse_response(raw, model)

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamChunk]:
        """Stream the response via SSE.

        Uses httpx for proper chunked transfer support.  Yields
        :class:`LLMStreamChunk` objects; the final chunk carries
        ``finish_reason`` and ``usage``.

        Raises:
            LLMTimeoutError: On connection timeout.
            LLMProviderError: On HTTP error responses.
        """
        model = request.model if request.model != "default" else self._default_model
        payload = self._build_payload(request, model)
        payload["stream"] = True

        api_key = os.environ.get(self._api_key_env, "")
        url = f"{self._base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "accept": "text/event-stream",
        }

        # Per-chunk timeout: connect fast, never cut off a long stream.
        timeout = httpx.Timeout(connect=30.0, read=self._timeout, write=30.0, pool=5.0)
        input_tokens: int = 0

        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code >= 400:
                        body = resp.read().decode(errors="replace")
                        raise LLMProviderError(
                            f"HTTP {resp.status_code}: {body}",
                            status_code=resp.status_code,
                        )
                    for line in resp.iter_lines():
                        # SSE format: "data: {...}" (RFC) or "data:{...}" (some proxies)
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].lstrip(" ")
                        if data_str == "[DONE]":
                            break
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        if event_type == "message_start":
                            usage_raw = event.get("message", {}).get("usage", {})
                            input_tokens = usage_raw.get("input_tokens", 0)
                            model_id = event.get("message", {}).get("model", model)
                            yield LLMStreamChunk(model=model_id)

                        elif event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            delta_type = delta.get("type", "")
                            if delta_type == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield LLMStreamChunk(delta=text)
                            elif delta_type == "thinking_delta":
                                thinking = delta.get("thinking", "")
                                if thinking:
                                    yield LLMStreamChunk(thinking_delta=thinking)

                        elif event_type == "message_delta":
                            delta = event.get("delta", {})
                            usage_raw = event.get("usage", {})
                            output_tokens = usage_raw.get("output_tokens", 0)
                            yield LLMStreamChunk(
                                finish_reason=delta.get("stop_reason") or "stop",
                                usage=TokenUsage(
                                    prompt_tokens=input_tokens,
                                    completion_tokens=output_tokens,
                                    total_tokens=input_tokens + output_tokens,
                                ),
                            )

        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(str(exc), status_code=exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(str(exc)) from exc

    def supports_model(self, model: str) -> bool:
        """Return ``True`` for any model (delegate validation to provider)."""
        return True

    # -- internals -------------------------------------------------------------

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        """Build Anthropic /v1/messages request body.

        Handles:
        - System message extraction (top-level field, not in messages)
        - Multimodal content blocks (list vs plain string)
        - Extended thinking configuration
        """
        system_text: str | None = None
        messages: list[dict[str, Any]] = []

        for msg in request.messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Extract text from content block list
                    system_text = " ".join(
                        b.get("text", "") for b in content if b.get("type") == "text"
                    )
                else:
                    system_text = str(content)
            else:
                messages.append(msg)

        # Resolve thinking budget: per-request overrides gateway default.
        thinking_budget = (
            request.thinking_budget
            if request.thinking_budget is not None
            else self._default_thinking_budget
        )
        thinking_enabled = thinking_budget is not None and thinking_budget > 0

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if system_text is not None:
            body["system"] = system_text
        if thinking_enabled:
            body["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            # Anthropic requires temperature=1 when extended thinking is active.
            body["temperature"] = 1
        else:
            body["temperature"] = request.temperature
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences
        return body

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST payload to /v1/messages via urllib (sync, non-streaming)."""
        api_key = os.environ.get(self._api_key_env, "")
        url = f"{self._base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = ""
            if exc.fp:
                body = exc.fp.read().decode(errors="replace")
            raise LLMProviderError(
                f"HTTP {exc.code}: {body}",
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason):
                raise LLMTimeoutError(str(exc.reason)) from exc
            raise LLMProviderError(str(exc.reason)) from exc
        except TimeoutError as exc:
            raise LLMTimeoutError(str(exc)) from exc

    @staticmethod
    def _parse_response(raw: dict[str, Any], model: str) -> LLMResponse:
        """Parse Anthropic Messages API response.

        Extracts text and thinking blocks separately.  Anthropic response::

            {
                "content": [
                    {"type": "thinking", "thinking": "..."},   # when thinking active
                    {"type": "text", "text": "..."}
                ],
                "model": "...",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": N, "output_tokens": M}
            }
        """
        content_blocks = raw.get("content", [])
        text_parts: list[str] = []
        thinking_parts: list[str] = []

        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "thinking":
                thinking_parts.append(block.get("thinking", ""))

        content = "\n".join(text_parts) if text_parts else ""
        thinking = "\n".join(thinking_parts) if thinking_parts else ""

        usage_raw = raw.get("usage", {})
        input_tokens = usage_raw.get("input_tokens", 0)
        output_tokens = usage_raw.get("output_tokens", 0)

        stop_reason = raw.get("stop_reason", "end_turn")
        finish_reason_map = {
            "end_turn": "stop",
            "max_tokens": "length",
            "stop_sequence": "stop",
        }
        finish_reason = finish_reason_map.get(stop_reason, stop_reason)

        return LLMResponse(
            content=content,
            model=raw.get("model", model),
            usage=TokenUsage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            finish_reason=finish_reason,
            thinking=thinking,
            raw=raw,
        )
