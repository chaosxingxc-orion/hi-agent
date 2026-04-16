"""LLM Gateway for Anthropic Claude API.

Uses stdlib urllib -- no anthropic SDK dependency.
Anthropic API differs from OpenAI:
- POST to /v1/messages (not /v1/chat/completions)
- Uses x-api-key header (not Bearer token)
- Different request/response format
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from hi_agent.llm.errors import LLMProviderError, LLMTimeoutError
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage

_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
_ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicLLMGateway:
    """LLM Gateway for Anthropic Claude API.

    Uses stdlib urllib -- no anthropic SDK dependency.
    Anthropic API differs from OpenAI:

    - POST to ``/v1/messages`` (not ``/v1/chat/completions``)
    - Uses ``x-api-key`` header (not Bearer token)
    - Different request/response format

    Args:
        api_key_env: Environment variable that holds the Anthropic API key.
        default_model: Model to use when the request specifies ``"default"``.
        timeout_seconds: HTTP request timeout.
    """

    def __init__(
        self,
        api_key_env: str = "ANTHROPIC_API_KEY",
        default_model: str = "claude-sonnet-4-20250514",
        timeout_seconds: int = 120,
        base_url: str = _ANTHROPIC_BASE_URL,
    ) -> None:
        """Initialize AnthropicLLMGateway."""
        self._api_key_env = api_key_env
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._base_url = base_url.rstrip("/")

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

    def supports_model(self, model: str) -> bool:
        """Return ``True`` if *model* looks like a Claude model identifier."""
        return model.startswith("claude-")

    # -- internals -------------------------------------------------------------

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        """Build Anthropic /v1/messages request body.

        Anthropic expects:
        - ``model`` at top level
        - ``max_tokens`` (required)
        - ``messages`` list with ``role`` and ``content``
        - Optional ``system`` as a top-level string (not inside messages)
        """
        # Separate system message from conversation messages.
        system_text: str | None = None
        messages: list[dict[str, str]] = []

        for msg in request.messages:
            if msg.get("role") == "system":
                # Anthropic: system goes in a top-level field, not in messages.
                system_text = msg.get("content", "")
            else:
                messages.append(msg)

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if system_text is not None:
            body["system"] = system_text
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences
        return body

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run _post."""
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

        Anthropic response structure::

            {
                "id": "msg_...",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "..."}],
                "model": "claude-...",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": N, "output_tokens": M}
            }
        """
        # Extract text from content blocks.
        content_blocks = raw.get("content", [])
        text_parts: list[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        content = "\n".join(text_parts) if text_parts else ""

        usage_raw = raw.get("usage", {})
        input_tokens = usage_raw.get("input_tokens", 0)
        output_tokens = usage_raw.get("output_tokens", 0)

        # Map Anthropic stop_reason to OpenAI-style finish_reason.
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
            raw=raw,
        )
