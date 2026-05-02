"""Async LLM gateway wrapper using ``api_key_env`` for configuration parity.

``HTTPGateway`` in ``http_gateway.py`` takes a resolved ``api_key`` string;
``HttpLLMGateway`` takes ``api_key_env`` (an env-var name).  This thin
wrapper matches the ``HttpLLMGateway`` constructor signature so that
``CognitionBuilder`` can instantiate either class with identical arguments
depending on ``compat_sync_llm``.
"""

from __future__ import annotations

import asyncio
import logging
import os

from hi_agent.llm.protocol import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class AsyncHTTPGateway:
    """Async LLM gateway that resolves the API key from an environment variable.

    Wraps :class:`hi_agent.llm.http_gateway.HTTPGateway` (httpx/async) and
    exposes the same constructor signature as :class:`HttpLLMGateway` so that
    :class:`CognitionBuilder` can branch on ``compat_sync_llm`` without
    duplicating argument lists.

    The retry loop uses ``await asyncio.sleep(delay)`` instead of the blocking
    ``time.sleep(delay)`` used in ``HttpLLMGateway``, making it safe for use
    inside an async event loop.
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        default_model: str = "gpt-4o",
        timeout_seconds: int = 120,
        max_retries: int = 3,
        retry_base_seconds: float = 1.0,
        failover_chain: object = None,
        cache_injector: object = None,
        budget_tracker: object = None,
        runtime_mode: str = "",
    ) -> None:
        """Initialize AsyncHTTPGateway.

        Args:
            base_url: Base URL for the OpenAI-compatible API endpoint.
            api_key_env: Name of the environment variable holding the API key.
            default_model: Model to use when the request specifies ``"default"``.
            timeout_seconds: HTTP request timeout.
            max_retries: Maximum retry attempts for transient errors.
            retry_base_seconds: Base delay for exponential back-off (async sleep).
            failover_chain: Optional FailoverChain forwarded to HTTPGateway.
            cache_injector: Optional PromptCacheInjector forwarded to HTTPGateway.
            budget_tracker: Optional LLMBudgetTracker forwarded to HTTPGateway.
            runtime_mode: Passed through for compatibility; not used by async path.
        """
        api_key = os.environ.get(api_key_env, "")
        from hi_agent.llm.http_gateway import HTTPGateway

        self._inner = HTTPGateway(
            base_url=base_url,
            api_key=api_key,
            timeout=float(timeout_seconds),
            default_model=default_model,
            max_retries=max_retries,
            retry_base_seconds=retry_base_seconds,
            failover_chain=failover_chain,  # type: ignore[arg-type]  expiry_wave: permanent
            cache_injector=cache_injector,  # type: ignore[arg-type]  expiry_wave: permanent  # scope: third-party-stub-gap — Optional[PromptCacheInjector] vs None union
            budget_tracker=budget_tracker,  # type: ignore[arg-type]  expiry_wave: permanent
        )
        self._retry_base = retry_base_seconds
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Sync protocol (LLMGateway) — runs the coroutine in the bridge
    # ------------------------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Synchronous entry-point: runs the async ``complete`` on the sync bridge."""
        from hi_agent.runtime.sync_bridge import get_bridge

        # P1-7 / Rule 12: route through the process-wide SyncBridge so the
        # httpx.AsyncClient pool inside ``HTTPGateway`` lives on a single,
        # durable event loop instead of a fresh loop per call (which would
        # close immediately and invalidate the pool).
        _inner_timeout = float(getattr(self._inner, "_timeout", 120) or 120)
        _bridge_timeout = _inner_timeout * max(1, self._max_retries + 1) + 10
        return get_bridge().call_sync(
            self._inner.complete(request), timeout=_bridge_timeout
        )

    # ------------------------------------------------------------------
    # Async protocol (AsyncLLMGateway) — native coroutine
    # ------------------------------------------------------------------

    async def async_complete(self, request: LLMRequest) -> LLMResponse:
        """Native async entry-point with async sleep in the retry loop."""
        from hi_agent.llm.errors import LLMProviderError
        from hi_agent.observability.fallback import record_llm_request

        record_llm_request(
            provider=getattr(self._inner, "_provider", "unknown"),
            model=request.model or "",
            run_id=request.metadata.get("run_id") if request.metadata else None,
        )
        last_exc: Exception | None = None
        for attempt in range(max(1, self._max_retries + 1)):
            try:
                return await self._inner.complete(request)
            except LLMProviderError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    if getattr(exc, "status_code", None) == 429:
                        _base_backoff = self._retry_base * (2**attempt)
                        _retry_after = float(
                            (getattr(exc, "headers", None) or {}).get("Retry-After", 0) or 0
                        )
                        delay = min(max(_retry_after, 0.0), 2 * _base_backoff) or _base_backoff
                    else:
                        delay = self._retry_base * (2**attempt)
                    logger.warning(
                        "AsyncHTTPGateway retry %d/%d after %.1fs: %s",
                        attempt + 1,
                        self._max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)  # non-blocking — avoids time.sleep
        from hi_agent.observability.fallback import record_fallback

        record_fallback(
            "llm",
            reason="async_retries_exhausted",
            run_id=(request.metadata or {}).get("run_id") or "unknown",
            extra={
                "provider": getattr(self._inner, "_provider", "unknown"),
                "model": request.model or "",
                "attempts": self._max_retries,
            },
        )
        raise last_exc  # type: ignore[misc]  expiry_wave: permanent
