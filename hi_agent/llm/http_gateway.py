"""HTTP-based LLM gateway — sync (urllib) and async (httpx) variants."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import random
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Iterator

import httpx

from hi_agent.llm.errors import LLMProviderError, LLMTimeoutError
from hi_agent.llm.protocol import LLMRequest, LLMResponse, LLMStreamChunk, TokenUsage
from hi_agent.runtime.async_bridge import AsyncBridgeService

if TYPE_CHECKING:
    from hi_agent.llm.failover import FailoverChain
    from hi_agent.llm.cache import PromptCacheInjector
    from hi_agent.llm.budget_tracker import LLMBudgetTracker

logger = logging.getLogger(__name__)


class HttpLLMGateway:
    """HTTP-based LLM gateway using stdlib ``urllib``.

    Works with any OpenAI-compatible API endpoint (``/v1/chat/completions``).
    Reads the API key from the environment variable specified by *api_key_env*.

    Args:
        base_url: Base URL for the API (no trailing slash).
        api_key_env: Environment variable that holds the API key.
        default_model: Model to use when the request specifies ``"default"``.
        timeout_seconds: HTTP request timeout.
        max_retries: Maximum number of retry attempts for transient errors.
        retry_base_seconds: Base delay in seconds for exponential backoff.
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        default_model: str = "gpt-4o",
        timeout_seconds: int = 120,
        max_retries: int = 3,
        retry_base_seconds: float = 1.0,
        failover_chain: "FailoverChain | None" = None,
        cache_injector: "PromptCacheInjector | None" = None,
        budget_tracker: "LLMBudgetTracker | None" = None,
        runtime_mode: str = "",
    ) -> None:
        """Initialize HttpLLMGateway.

        .. deprecated::
            ``HttpLLMGateway`` (urllib/sync) is the compatibility layer.  Use
            ``HTTPGateway`` (httpx/async) for production profiles.  Set
            ``compat_sync_llm=True`` in ``TraceConfig`` to opt into this class
            explicitly and suppress the deprecation warning.
        """
        import warnings

        if runtime_mode in ("prod-real", "local-real"):
            warnings.warn(
                "HttpLLMGateway (sync/urllib) is deprecated for production profiles. "
                "Use HTTPGateway (async/httpx) by setting compat_sync_llm=False in TraceConfig.",
                DeprecationWarning,
                stacklevel=2,
            )
        self._base_url = base_url.rstrip("/")
        self._api_key_env = api_key_env
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_base = retry_base_seconds
        # dev-smoke: skip slow LLM wait, fall through to heuristic immediately
        if runtime_mode == "dev-smoke":
            self._timeout = min(self._timeout, 3)
            self._max_retries = 0
        self._failover_chain = failover_chain
        self._cache_injector = cache_injector
        self._budget_tracker = budget_tracker

    # -- LLMGateway protocol --------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a chat-completion request and return a structured response.

        When a :class:`PromptCacheInjector` is configured, cache_control markers
        are injected into the message list before sending.  When a
        :class:`FailoverChain` is configured, the request is routed through it
        instead of the direct HTTP path.

        Raises:
            LLMTimeoutError: If the HTTP call exceeds *timeout_seconds*.
            LLMProviderError: On any non-200 HTTP response or connection failure.
            LLMBudgetExhaustedError: If the configured budget tracker signals exhaustion.
        """
        if self._budget_tracker is not None:
            self._budget_tracker.check()
            # Inject real-time remaining budget ratio into request metadata so
            # that TierAwareLLMGateway can make accurate per-request tier
            # downgrade decisions instead of relying on the caller-supplied
            # default of 1.0.
            _snap = self._budget_tracker.snapshot()
            remaining_calls = _snap["remaining_calls"]
            max_calls = _snap["max_calls"]
            remaining_tokens = _snap["remaining_tokens"]
            max_tokens = _snap["max_tokens"]
            calls_ratio = remaining_calls / max_calls if max_calls > 0 else 1.0
            tokens_ratio = remaining_tokens / max_tokens if max_tokens > 0 else 1.0
            budget_ratio = min(calls_ratio, tokens_ratio)
            request = LLMRequest(
                model=request.model,
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stop_sequences=request.stop_sequences,
                metadata={**request.metadata, "budget_remaining": budget_ratio},
            )
        try:
            # 1. Inject prompt cache markers if configured.
            if self._cache_injector is not None:
                try:
                    messages = self._cache_injector.inject(list(request.messages))
                    request = LLMRequest(
                        model=request.model,
                        messages=messages,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        stop_sequences=request.stop_sequences,
                        metadata=request.metadata,
                    )
                except Exception as exc:  # pragma: no cover
                    logger.warning("PromptCacheInjector.inject failed, skipping: %s", exc)

            # 2. Route through failover chain if configured.
            if self._failover_chain is not None:
                import asyncio as _asyncio
                try:
                    loop = _asyncio.get_event_loop()
                    if loop.is_running():
                        # Use shared bridge executor rather than creating a per-call pool.
                        future = AsyncBridgeService.get_executor().submit(
                            _asyncio.run, self._failover_chain.complete(request)
                        )
                        return future.result()
                    else:
                        return loop.run_until_complete(
                            self._failover_chain.complete(request)
                        )
                except Exception as exc:
                    logger.warning(
                        "FailoverChain.complete failed (%s), falling back to direct HTTP.", exc
                    )

        except Exception as exc:  # pragma: no cover
            logger.warning("http_gateway integration error (%s), using direct path.", exc)

        # 3. Fallback: original direct HTTP logic.
        response = self._direct_complete(request)
        if self._budget_tracker is not None:
            self._budget_tracker.record(response.usage)
        return response

    def _direct_complete(self, request: LLMRequest) -> LLMResponse:
        """Execute the request directly via urllib (no failover)."""
        model = request.model if request.model != "default" else self._default_model
        payload = self._build_payload(request, model)
        raw = self._post(payload)
        return self._parse_response(raw, model)

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamChunk]:
        """Stream the response via SSE (OpenAI format).

        Uses httpx for chunked transfer.  Yields :class:`LLMStreamChunk`
        objects; the final chunk carries ``finish_reason`` and ``usage``.

        Raises:
            LLMTimeoutError: On connection timeout.
            LLMProviderError: On HTTP error responses.
        """
        model = request.model if request.model != "default" else self._default_model
        payload = self._build_payload(request, model)
        payload["stream"] = True

        api_key = os.environ.get(self._api_key_env, "")
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "accept": "text/event-stream",
        }

        timeout = httpx.Timeout(connect=30.0, read=self._timeout, write=30.0, pool=5.0)

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
                        choices = event.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        text = delta.get("content") or ""
                        finish_reason = choice.get("finish_reason")
                        usage_raw = event.get("usage", {})
                        usage = None
                        if usage_raw:
                            usage = TokenUsage(
                                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                                completion_tokens=usage_raw.get("completion_tokens", 0),
                                total_tokens=usage_raw.get("total_tokens", 0),
                            )
                        if text or finish_reason or usage:
                            yield LLMStreamChunk(
                                delta=text,
                                finish_reason=finish_reason,
                                usage=usage,
                                model=event.get("model", model),
                            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(str(exc), status_code=exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(str(exc)) from exc

    def supports_model(self, model: str) -> bool:
        """Return ``True``; the HTTP gateway delegates model validation to the provider."""
        return True

    # -- internals -------------------------------------------------------------

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        """Run _build_payload."""
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
        """Run _post with retry logic for transient errors."""
        api_key = os.environ.get(self._api_key_env, "")
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        data = json.dumps(payload).encode()

        last_exc: LLMProviderError | None = None
        for attempt in range(self._max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                body = ""
                if exc.fp:
                    body = exc.fp.read().decode(errors="replace")
                provider_exc = LLMProviderError(
                    f"HTTP {exc.code}: {body}",
                    status_code=exc.code,
                )
                # Don't retry client errors (4xx) except 429 (rate limit)
                if exc.code < 500 and exc.code != 429:
                    raise provider_exc from exc
                last_exc = provider_exc
                if attempt < self._max_retries:
                    delay = self._retry_base * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
            except urllib.error.URLError as exc:
                if "timed out" in str(exc.reason):
                    raise LLMTimeoutError(str(exc.reason)) from exc
                # Network unreachable: no point retrying, fail immediately
                if isinstance(exc.reason, OSError) and exc.reason.errno == errno.ENETUNREACH:
                    raise LLMProviderError(str(exc.reason)) from exc
                last_exc = LLMProviderError(str(exc.reason))
                if attempt < self._max_retries:
                    delay = self._retry_base * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
            except TimeoutError as exc:
                raise LLMTimeoutError(str(exc)) from exc
        try:
            from hi_agent.observability.fallback import (  # noqa: PLC0415
                FallbackTaxonomy,
                record_fallback,
            )
            record_fallback(
                FallbackTaxonomy.DEPENDENCY_UNAVAILABLE,
                "http_llm_gateway",
                "all_retries_exhausted",
            )
        except Exception:
            pass
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _parse_response(raw: dict[str, Any], model: str) -> LLMResponse:
        """Run _parse_response."""
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


class HTTPGateway:
    """OpenAI-compatible async LLM gateway using httpx connection pool.

    Implements :class:`AsyncLLMGateway` protocol for use in async contexts.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
        default_model: str = "gpt-4o",
        max_retries: int = 3,
        retry_base_seconds: float = 1.0,
        failover_chain: "FailoverChain | None" = None,
        cache_injector: "PromptCacheInjector | None" = None,
        budget_tracker: "LLMBudgetTracker | None" = None,
    ) -> None:
        """Initialize HTTPGateway."""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._retry_base = retry_base_seconds
        self._failover_chain = failover_chain
        self._cache_injector = cache_injector
        self._budget_tracker = budget_tracker
        # Shared AsyncClient = connection pool reused across all calls
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    # -- AsyncLLMGateway protocol ----------------------------------------------

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Implement AsyncLLMGateway protocol with cache injection and failover.

        When a :class:`PromptCacheInjector` is configured, cache_control markers
        are injected into the message list before sending.  When a
        :class:`FailoverChain` is configured, the request is routed through it
        instead of the direct HTTP path.

        Raises:
            LLMBudgetExhaustedError: If the configured budget tracker signals exhaustion.
        """
        if self._budget_tracker is not None:
            self._budget_tracker.check()
            # Inject real-time remaining budget ratio into request metadata so
            # that TierAwareLLMGateway can make accurate per-request tier
            # downgrade decisions instead of relying on the caller-supplied
            # default of 1.0.
            _snap = self._budget_tracker.snapshot()
            remaining_calls = _snap["remaining_calls"]
            max_calls = _snap["max_calls"]
            remaining_tokens = _snap["remaining_tokens"]
            max_tokens = _snap["max_tokens"]
            calls_ratio = remaining_calls / max_calls if max_calls > 0 else 1.0
            tokens_ratio = remaining_tokens / max_tokens if max_tokens > 0 else 1.0
            budget_ratio = min(calls_ratio, tokens_ratio)
            request = LLMRequest(
                model=request.model,
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stop_sequences=request.stop_sequences,
                metadata={**request.metadata, "budget_remaining": budget_ratio},
            )
        try:
            # 1. Inject prompt cache markers if configured.
            if self._cache_injector is not None:
                try:
                    messages = self._cache_injector.inject(list(request.messages))
                    request = LLMRequest(
                        model=request.model,
                        messages=messages,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        stop_sequences=request.stop_sequences,
                        metadata=request.metadata,
                    )
                except Exception as exc:  # pragma: no cover
                    logger.warning("PromptCacheInjector.inject failed, skipping: %s", exc)

            # 2. Route through failover chain if configured.
            if self._failover_chain is not None:
                try:
                    return await self._failover_chain.complete(request)
                except Exception as exc:
                    logger.warning(
                        "FailoverChain.complete failed (%s), falling back to direct HTTP.", exc
                    )

        except Exception as exc:  # pragma: no cover
            logger.warning("HTTPGateway integration error (%s), using direct path.", exc)

        # 3. Fallback: original direct HTTP logic.
        response = await self._direct_complete(request)
        if self._budget_tracker is not None:
            self._budget_tracker.record(response.usage)
        return response

    async def _direct_complete(self, request: LLMRequest) -> LLMResponse:
        """Execute the request directly via httpx (no failover)."""
        model = request.model if request.model != "default" else self._default_model
        payload: dict[str, Any] = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()
                raw = response.json()
                return HttpLLMGateway._parse_response(raw, model)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                # Don't retry client errors (4xx) except 429 (rate limit)
                if status < 500 and status != 429:
                    raise LLMProviderError(
                        f"HTTP {status}: {exc.response.text}",
                        status_code=status,
                    ) from exc
                last_exc = LLMProviderError(
                    f"HTTP {status}: {exc.response.text}",
                    status_code=status,
                )
                if attempt < self._max_retries:
                    delay = self._retry_base * (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(str(exc)) from exc
            except httpx.RequestError as exc:
                last_exc = LLMProviderError(str(exc))
                if attempt < self._max_retries:
                    delay = self._retry_base * (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def supports_model(self, model: str) -> bool:
        """Return ``True``; the HTTP gateway delegates model validation to the provider."""
        return True

    # -- Legacy call interface -------------------------------------------------

    async def call(self, model_id: str, messages: list[dict], **kwargs) -> dict:
        """Legacy call method for backward compatibility."""
        payload = {"model": model_id, "messages": messages, **kwargs}
        response = await self._client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        """Run aclose."""
        await self._client.aclose()
