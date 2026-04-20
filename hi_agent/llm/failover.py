"""LLM Provider Failover Chain for hi-agent.

Implements HTTP-error-aware failover, credential pool rotation,
and exponential backoff. Operates at the LLM level (not action level —
action-level circuit breaking is handled by agent-kernel).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import httpx

from hi_agent.llm.protocol import AsyncLLMGateway, LLMRequest, LLMResponse

if TYPE_CHECKING:
    # StreamDelta is defined in hi_agent.llm.streaming (parallel development).
    # Guard import so it doesn't break when that module isn't yet present.
    try:
        from hi_agent.llm.streaming import StreamDelta
    except ImportError:
        StreamDelta = object  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FailoverReason
# ---------------------------------------------------------------------------


class FailoverReason(StrEnum):
    """Categorised reason why a single provider attempt failed."""

    auth = "auth"
    """Temporary auth failure (may succeed with another credential)."""
    auth_permanent = "auth_permanent"
    """Permanent auth failure (credential is definitively invalid)."""
    billing = "billing"
    """Payment / quota issue — treat like permanent for this key."""
    rate_limit = "rate_limit"
    """Provider is throttling; back off and retry."""
    overloaded = "overloaded"
    """Provider is overloaded (503/529); back off and retry."""
    server_error = "server_error"
    """5xx error that is not overloaded; back off and retry."""
    timeout = "timeout"
    """HTTP timeout reached."""
    context_overflow = "context_overflow"
    """Input exceeded the model's context window."""
    model_not_found = "model_not_found"
    """The requested model endpoint does not exist."""
    unknown = "unknown"
    """Any other failure."""


# ---------------------------------------------------------------------------
# FailoverError
# ---------------------------------------------------------------------------


class FailoverError(Exception):
    """Raised when the failover chain has exhausted all retry options.

    Attributes:
        reason: The primary reason the chain gave up.
        status_code: Last HTTP status code seen, if any.
        provider: Name / identifier of the last provider attempted.
        retry_after_seconds: Value from the ``Retry-After`` header, if parsed.
        message: Human-readable description.
    """

    def __init__(
        self,
        reason: FailoverReason,
        message: str,
        *,
        status_code: int | None = None,
        provider: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FailoverError(reason={self.reason!r}, status_code={self.status_code!r},"
            f" provider={self.provider!r}, message={self.message!r})"
        )


# ---------------------------------------------------------------------------
# classify_http_error
# ---------------------------------------------------------------------------

# Response-body substrings that hint at permanent auth failure.
_PERMANENT_AUTH_HINTS: tuple[str, ...] = (
    "invalid_api_key",
    "invalid api key",
    "no such user",
    "account deactivated",
    "account has been disabled",
)

# Response-body substrings that hint at context-length overflow.
_CONTEXT_OVERFLOW_HINTS: tuple[str, ...] = (
    "context_length_exceeded",
    "maximum context length",
    "too many tokens",
    "context window",
)


def classify_http_error(status_code: int, response_body: str) -> FailoverReason:
    """Map an HTTP status code (and body) to a :class:`FailoverReason`.

    Args:
        status_code: The HTTP response status code.
        response_body: Raw response body text (used for body-based hints).

    Returns:
        A :class:`FailoverReason` value appropriate for the error.
    """
    body_lower = response_body.lower()

    if status_code in (401, 403):
        # Distinguish permanent vs. transient auth failures.
        if any(hint in body_lower for hint in _PERMANENT_AUTH_HINTS):
            return FailoverReason.auth_permanent
        return FailoverReason.auth

    if status_code == 402:
        return FailoverReason.billing

    if status_code == 404:
        return FailoverReason.model_not_found

    if status_code == 408:
        return FailoverReason.timeout

    if status_code == 429:
        return FailoverReason.rate_limit

    if status_code in (500, 502, 504):
        # Check whether body hints at a context-overflow scenario first.
        if any(hint in body_lower for hint in _CONTEXT_OVERFLOW_HINTS):
            return FailoverReason.context_overflow
        return FailoverReason.server_error

    if status_code in (503, 529):
        return FailoverReason.overloaded

    return FailoverReason.unknown


# ---------------------------------------------------------------------------
# CredentialEntry
# ---------------------------------------------------------------------------


@dataclass
class CredentialEntry:
    """A single API credential with cooldown state.

    Attributes:
        api_key: The actual API key string.
        provider: Human-readable provider name (e.g. ``"anthropic"``).
        cooldown_until: Unix timestamp after which this credential may be used again.
        failure_count: Cumulative number of failures recorded for this credential.
    """

    api_key: str
    provider: str
    cooldown_until: float = 0.0
    failure_count: int = 0


# ---------------------------------------------------------------------------
# CredentialPool
# ---------------------------------------------------------------------------


class CredentialPool:
    """Manages a set of :class:`CredentialEntry` objects with round-trip rotation.

    Credentials that are in their cooldown period are skipped by
    :meth:`next_eligible`. When every credential is cooling down,
    :meth:`all_cooling_down` returns ``True`` and :meth:`next_eligible`
    returns ``None``.
    """

    def __init__(self, entries: list[CredentialEntry]) -> None:
        if not entries:
            raise ValueError("CredentialPool requires at least one CredentialEntry.")
        self._entries: list[CredentialEntry] = list(entries)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def next_eligible(self) -> CredentialEntry | None:
        """Return the first credential whose cooldown has expired.

        Credentials are checked in insertion order. Returns ``None`` when
        all credentials are still cooling down.
        """
        now = time.time()
        for entry in self._entries:
            if entry.cooldown_until < now:
                return entry
        return None

    def mark_failed(
        self, api_key: str, cooldown_seconds: float = 60.0
    ) -> None:
        """Record a failure for *api_key* and apply a cooldown.

        Args:
            api_key: The key to penalise.
            cooldown_seconds: How long (in seconds) the credential is
                suspended.  Pass ``float("inf")`` to suspend permanently.
        """
        for entry in self._entries:
            if entry.api_key == api_key:
                entry.failure_count += 1
                if cooldown_seconds == float("inf"):
                    entry.cooldown_until = float("inf")
                else:
                    entry.cooldown_until = time.time() + cooldown_seconds
                logger.debug(
                    "Credential for provider=%s marked failed (count=%d, cooldown=%.1fs)",
                    entry.provider,
                    entry.failure_count,
                    cooldown_seconds,
                )
                return

    def mark_success(self, api_key: str) -> None:
        """Reset failure state for *api_key* after a successful call."""
        for entry in self._entries:
            if entry.api_key == api_key:
                entry.failure_count = 0
                entry.cooldown_until = 0.0
                return

    def all_cooling_down(self) -> bool:
        """Return ``True`` if every credential is currently in cooldown."""
        now = time.time()
        return all(entry.cooldown_until >= now for entry in self._entries)

    def __len__(self) -> int:  # pragma: no cover
        return len(self._entries)


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------


@dataclass
class RetryPolicy:
    """Exponential back-off policy for the failover chain.

    Attributes:
        max_retries: Total number of retry attempts (not counting the first).
        base_delay_ms: Base delay in milliseconds for attempt 0.
        max_delay_ms: Upper bound on computed delay (before jitter).
        jitter: When ``True``, add uniform random jitter in ``[0, base_delay_ms)``.
    """

    max_retries: int = 3
    base_delay_ms: int = 500
    max_delay_ms: int = 30_000
    jitter: bool = True

    def delay_for(self, attempt: int) -> float:
        """Compute the delay (in seconds) before *attempt* (0-indexed).

        The formula is::

            delay = min(base_delay_ms * 2**attempt, max_delay_ms)

        Optionally adds uniform jitter in ``[0, base_delay_ms)`` ms.

        Args:
            attempt: Zero-indexed attempt number.

        Returns:
            Delay in seconds as a float.
        """
        raw_ms = self.base_delay_ms * (2 ** attempt)
        clamped_ms = min(raw_ms, self.max_delay_ms)
        if self.jitter:
            clamped_ms += random.uniform(0, self.base_delay_ms)
        return clamped_ms / 1000.0


# ---------------------------------------------------------------------------
# FailoverChain
# ---------------------------------------------------------------------------

# Reasons that are definitively terminal for a given credential — we will not
# retry with the same key after seeing these.
_PERMANENT_REASONS: frozenset[FailoverReason] = frozenset(
    {FailoverReason.auth_permanent, FailoverReason.billing}
)

# Reasons where we should back off before trying the next eligible credential.
_BACKOFF_REASONS: frozenset[FailoverReason] = frozenset(
    {
        FailoverReason.rate_limit,
        FailoverReason.overloaded,
        FailoverReason.server_error,
        FailoverReason.timeout,
    }
)

# Default cooldown applied when a credential hits a permanent failure.
_PERMANENT_COOLDOWN: float = float("inf")

# Default cooldown for transient failures (rate limit / overload / server).
_TRANSIENT_COOLDOWN: float = 60.0


class FailoverChain:
    """Async LLM gateway wrapper that transparently fails over across providers.

    The chain picks the next eligible credential from the pool, instantiates
    a gateway via *gateway_factory*, and calls the underlying LLM.  On
    failure it classifies the HTTP error, applies the appropriate cooldown to
    the credential, optionally backs off, then loops until it either succeeds
    or exhausts all retries.

    Args:
        gateway_factory: Callable that accepts an API key string and returns an
            :class:`AsyncLLMGateway` instance.
        pool: The :class:`CredentialPool` to draw credentials from.
        policy: The :class:`RetryPolicy` governing back-off delays.
    """

    def __init__(
        self,
        gateway_factory: Callable[[str], AsyncLLMGateway],
        pool: CredentialPool,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._factory = gateway_factory
        self._pool = pool
        self._policy = policy or RetryPolicy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send *request* to an LLM, retrying across providers on failure.

        Returns:
            The first successful :class:`LLMResponse`.

        Raises:
            FailoverError: When all retry attempts and credentials are
                exhausted, or when a permanent failure is encountered and
                no further credentials are available.
        """
        last_reason = FailoverReason.unknown
        last_status: int | None = None
        last_provider: str | None = None

        for attempt in range(self._policy.max_retries + 1):
            entry = self._pool.next_eligible()
            if entry is None:
                raise FailoverError(
                    reason=last_reason,
                    message=(
                        "All LLM credentials are in cooldown. "
                        f"Last failure: {last_reason} (HTTP {last_status})"
                    ),
                    status_code=last_status,
                    provider=last_provider,
                )

            last_provider = entry.provider
            gateway = self._factory(entry.api_key)

            try:
                response = await gateway.complete(request)
                self._pool.mark_success(entry.api_key)
                logger.debug(
                    "LLM call succeeded via provider=%s on attempt=%d",
                    entry.provider,
                    attempt,
                )
                return response

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = exc.response.text
                reason = classify_http_error(status, body)
                last_reason = reason
                last_status = status

                retry_after = self._parse_retry_after(exc)

                logger.warning(
                    "LLM HTTP error: provider=%s status=%d reason=%s attempt=%d",
                    entry.provider,
                    status,
                    reason,
                    attempt,
                )

                if reason in _PERMANENT_REASONS:
                    # This key is definitely dead; suspend it permanently.
                    self._pool.mark_failed(entry.api_key, _PERMANENT_COOLDOWN)
                    if self._pool.all_cooling_down():
                        raise FailoverError(
                            reason=reason,
                            message=(
                                f"Permanent failure ({reason}) from provider={entry.provider}."
                                " No further credentials available."
                            ),
                            status_code=status,
                            provider=entry.provider,
                        ) from exc
                    # Try next credential immediately (no sleep).
                    continue

                # Transient failure — apply cooldown then back off.
                cooldown = retry_after if retry_after is not None else _TRANSIENT_COOLDOWN
                self._pool.mark_failed(entry.api_key, cooldown)

                if attempt < self._policy.max_retries:
                    delay = (
                        retry_after
                        if retry_after is not None
                        else self._policy.delay_for(attempt)
                    )
                    logger.debug("Backing off %.2fs before retry %d", delay, attempt + 1)
                    await asyncio.sleep(delay)

            except httpx.TimeoutException as exc:
                last_reason = FailoverReason.timeout
                logger.warning(
                    "LLM timeout: provider=%s attempt=%d", entry.provider, attempt
                )
                self._pool.mark_failed(entry.api_key, _TRANSIENT_COOLDOWN)
                if attempt < self._policy.max_retries:
                    await asyncio.sleep(self._policy.delay_for(attempt))
                    continue
                raise FailoverError(
                    reason=FailoverReason.timeout,
                    message=f"LLM request timed out after {attempt + 1} attempt(s).",
                    provider=entry.provider,
                ) from exc

            except httpx.RequestError as exc:
                last_reason = FailoverReason.unknown
                logger.warning(
                    "LLM request error: provider=%s attempt=%d error=%s",
                    entry.provider,
                    attempt,
                    exc,
                )
                self._pool.mark_failed(entry.api_key, _TRANSIENT_COOLDOWN)
                if attempt < self._policy.max_retries:
                    await asyncio.sleep(self._policy.delay_for(attempt))
                    continue
                raise FailoverError(
                    reason=FailoverReason.unknown,
                    message=f"LLM request failed: {exc}",
                    provider=entry.provider,
                ) from exc

        raise FailoverError(
            reason=last_reason,
            message=(
                f"LLM failover chain exhausted after {self._policy.max_retries + 1} attempt(s)."
                f" Last failure: {last_reason} (HTTP {last_status})"
            ),
            status_code=last_status,
            provider=last_provider,
        )

    async def stream(
        self, request: LLMRequest
    ) -> AsyncIterator[object]:
        """Stream *request* to an LLM with the same failover logic as :meth:`complete`.

        Yields:
            ``StreamDelta`` objects (typed via ``TYPE_CHECKING`` guard) from
            the first gateway that successfully begins streaming.

        Raises:
            FailoverError: Same conditions as :meth:`complete`.

        Note:
            The stream is yielded incrementally.  If a streaming connection
            drops *mid-stream* this method does **not** retry the partial
            stream — it only retries at the start of the connection.
        """
        last_reason = FailoverReason.unknown
        last_status: int | None = None
        last_provider: str | None = None

        for attempt in range(self._policy.max_retries + 1):
            entry = self._pool.next_eligible()
            if entry is None:
                raise FailoverError(
                    reason=last_reason,
                    message=(
                        "All LLM credentials are in cooldown (stream). "
                        f"Last failure: {last_reason} (HTTP {last_status})"
                    ),
                    status_code=last_status,
                    provider=last_provider,
                )

            last_provider = entry.provider
            gateway = self._factory(entry.api_key)

            # Check whether the gateway supports streaming.
            stream_fn = getattr(gateway, "stream", None)
            if stream_fn is None:
                # Fallback: wrap complete() as a single-chunk stream.
                try:
                    response = await gateway.complete(request)
                    self._pool.mark_success(entry.api_key)
                    yield response  # yield the full LLMResponse as the single item
                    return
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    reason = classify_http_error(status, exc.response.text)
                    last_reason = reason
                    last_status = status
                    self._pool.mark_failed(
                        entry.api_key,
                        _PERMANENT_COOLDOWN if reason in _PERMANENT_REASONS else _TRANSIENT_COOLDOWN,
                    )
                    if reason in _PERMANENT_REASONS and self._pool.all_cooling_down():
                        raise FailoverError(
                            reason=reason,
                            message=f"Permanent stream failure from provider={entry.provider}.",
                            status_code=status,
                            provider=entry.provider,
                        ) from exc
                    if attempt < self._policy.max_retries:
                        await asyncio.sleep(self._policy.delay_for(attempt))
                    continue

            # Gateway has a native stream() method.
            try:
                async for delta in stream_fn(request):
                    yield delta
                self._pool.mark_success(entry.api_key)
                return

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = exc.response.text
                reason = classify_http_error(status, body)
                last_reason = reason
                last_status = status
                retry_after = self._parse_retry_after(exc)

                logger.warning(
                    "LLM stream HTTP error: provider=%s status=%d reason=%s attempt=%d",
                    entry.provider,
                    status,
                    reason,
                    attempt,
                )

                cooldown = retry_after if retry_after is not None else _TRANSIENT_COOLDOWN
                if reason in _PERMANENT_REASONS:
                    cooldown = _PERMANENT_COOLDOWN

                self._pool.mark_failed(entry.api_key, cooldown)

                if reason in _PERMANENT_REASONS and self._pool.all_cooling_down():
                    raise FailoverError(
                        reason=reason,
                        message=f"Permanent stream failure from provider={entry.provider}.",
                        status_code=status,
                        provider=entry.provider,
                    ) from exc

                if attempt < self._policy.max_retries:
                    delay = retry_after if retry_after is not None else self._policy.delay_for(attempt)
                    await asyncio.sleep(delay)

            except httpx.TimeoutException as exc:
                last_reason = FailoverReason.timeout
                self._pool.mark_failed(entry.api_key, _TRANSIENT_COOLDOWN)
                if attempt < self._policy.max_retries:
                    await asyncio.sleep(self._policy.delay_for(attempt))
                    continue
                raise FailoverError(
                    reason=FailoverReason.timeout,
                    message=f"LLM stream request timed out after {attempt + 1} attempt(s).",
                    provider=entry.provider,
                ) from exc

        raise FailoverError(
            reason=last_reason,
            message=(
                f"LLM stream failover chain exhausted after {self._policy.max_retries + 1} attempt(s)."
            ),
            status_code=last_status,
            provider=last_provider,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_retry_after(exc: httpx.HTTPStatusError) -> float | None:
        """Extract the ``Retry-After`` value (in seconds) from a response header.

        Returns ``None`` if the header is absent or cannot be parsed.
        """
        header = exc.response.headers.get("retry-after") or exc.response.headers.get(
            "Retry-After"
        )
        if header is None:
            return None
        try:
            return float(header)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# make_credential_pool_from_env
# ---------------------------------------------------------------------------


def make_credential_pool_from_env(
    env_var: str = "ANTHROPIC_API_KEY",
    provider: str = "anthropic",
) -> CredentialPool:
    """Build a :class:`CredentialPool` from environment variables.

    Reads *env_var* from the environment.  The value may be a single API
    key or a comma-separated list of keys, each of which becomes its own
    :class:`CredentialEntry`.

    Args:
        env_var: Name of the environment variable holding the API key(s).
            Defaults to ``"ANTHROPIC_API_KEY"``.
        provider: Provider label applied to every created entry.
            Defaults to ``"anthropic"``.

    Returns:
        A :class:`CredentialPool` containing one entry per discovered key.

    Raises:
        ValueError: When the environment variable is unset or empty.
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        raise ValueError(
            f"Environment variable {env_var!r} is not set or is empty. "
            "Cannot build CredentialPool."
        )

    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise ValueError(
            f"Environment variable {env_var!r} contains no valid API keys."
        )

    entries = [CredentialEntry(api_key=key, provider=provider) for key in keys]
    logger.info(
        "Built CredentialPool with %d credential(s) for provider=%s", len(entries), provider
    )
    return CredentialPool(entries)
