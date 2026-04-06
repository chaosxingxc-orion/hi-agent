"""HTTP-based LLM gateway using stdlib urllib."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from hi_agent.llm.errors import LLMProviderError, LLMTimeoutError
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage


class HttpLLMGateway:
    """HTTP-based LLM gateway using stdlib ``urllib``.

    Works with any OpenAI-compatible API endpoint (``/v1/chat/completions``).
    Reads the API key from the environment variable specified by *api_key_env*.

    Args:
        base_url: Base URL for the API (no trailing slash).
        api_key_env: Environment variable that holds the API key.
        default_model: Model to use when the request specifies ``"default"``.
        timeout_seconds: HTTP request timeout.
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        default_model: str = "gpt-4o",
        timeout_seconds: int = 120,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key_env = api_key_env
        self._default_model = default_model
        self._timeout = timeout_seconds

    # -- LLMGateway protocol --------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a chat-completion request and return a structured response.

        Raises:
            LLMTimeoutError: If the HTTP call exceeds *timeout_seconds*.
            LLMProviderError: On any non-200 HTTP response or connection failure.
        """
        model = request.model if request.model != "default" else self._default_model
        payload = self._build_payload(request, model)
        raw = self._post(payload)
        return self._parse_response(raw, model)

    def supports_model(self, model: str) -> bool:  # noqa: ARG002
        """Return ``True``; the HTTP gateway delegates model validation to the provider."""
        return True

    # -- internals -------------------------------------------------------------

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.stop_sequences:
            body["stop"] = request.stop_sequences
        return body

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = os.environ.get(self._api_key_env, "")
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
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
        choices = raw.get("choices", [])
        if not choices:
            raise LLMProviderError("Empty choices in provider response")
        choice = choices[0]
        message = choice.get("message", {})
        usage_raw = raw.get("usage", {})
        return LLMResponse(
            content=message.get("content", ""),
            model=raw.get("model", model),
            usage=TokenUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=raw,
        )
