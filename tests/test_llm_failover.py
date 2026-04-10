"""Tests for hi_agent.llm.failover — LLM Provider Failover Chain.

All tests use unittest.mock; no real API calls are made.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from hi_agent.llm.failover import (
    CredentialEntry,
    CredentialPool,
    FailoverChain,
    FailoverError,
    FailoverReason,
    RetryPolicy,
    classify_http_error,
    make_credential_pool_from_env,
)
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request() -> LLMRequest:
    """Return a minimal LLMRequest for testing."""
    return LLMRequest(messages=[{"role": "user", "content": "hello"}])


def _make_response(content: str = "ok") -> LLMResponse:
    """Return a minimal LLMResponse for testing."""
    return LLMResponse(
        content=content,
        model="test-model",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop",
    )


def _make_httpx_status_error(
    status_code: int,
    body: str = "",
    headers: dict[str, str] | None = None,
) -> httpx.HTTPStatusError:
    """Build a fake httpx.HTTPStatusError for a given status code."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = body
    response.headers = httpx.Headers(headers or {})
    request = MagicMock(spec=httpx.Request)
    return httpx.HTTPStatusError(
        message=f"HTTP {status_code}", request=request, response=response
    )


def _make_pool(*keys: str, provider: str = "test") -> CredentialPool:
    """Create a CredentialPool with the given keys."""
    entries = [CredentialEntry(api_key=k, provider=provider) for k in keys]
    return CredentialPool(entries)


def _make_policy(max_retries: int = 3, base_delay_ms: int = 0, jitter: bool = False) -> RetryPolicy:
    """Create a RetryPolicy with zero/minimal delays for fast tests."""
    return RetryPolicy(
        max_retries=max_retries,
        base_delay_ms=base_delay_ms,
        max_delay_ms=0,
        jitter=jitter,
    )


# ---------------------------------------------------------------------------
# 1. classify_http_error — rate limit
# ---------------------------------------------------------------------------


def test_classify_http_error_rate_limit() -> None:
    """HTTP 429 must map to FailoverReason.rate_limit."""
    reason = classify_http_error(429, "Too Many Requests")
    assert reason is FailoverReason.rate_limit


# ---------------------------------------------------------------------------
# 2. classify_http_error — auth
# ---------------------------------------------------------------------------


def test_classify_http_error_auth() -> None:
    """HTTP 401 without a 'permanent' body hint must map to FailoverReason.auth."""
    reason = classify_http_error(401, "Unauthorized")
    assert reason is FailoverReason.auth


def test_classify_http_error_auth_permanent() -> None:
    """HTTP 401 with 'invalid_api_key' in the body maps to auth_permanent."""
    reason = classify_http_error(401, '{"error": "invalid_api_key"}')
    assert reason is FailoverReason.auth_permanent


# ---------------------------------------------------------------------------
# 3. classify_http_error — overloaded
# ---------------------------------------------------------------------------


def test_classify_http_error_overloaded_503() -> None:
    """HTTP 503 must map to FailoverReason.overloaded."""
    reason = classify_http_error(503, "Service Unavailable")
    assert reason is FailoverReason.overloaded


def test_classify_http_error_overloaded_529() -> None:
    """HTTP 529 (Anthropic overload) must also map to FailoverReason.overloaded."""
    reason = classify_http_error(529, "Overloaded")
    assert reason is FailoverReason.overloaded


# ---------------------------------------------------------------------------
# Additional classify_http_error coverage
# ---------------------------------------------------------------------------


def test_classify_http_error_billing() -> None:
    """HTTP 402 must map to FailoverReason.billing."""
    assert classify_http_error(402, "") is FailoverReason.billing


def test_classify_http_error_server_error_500() -> None:
    """HTTP 500 maps to FailoverReason.server_error."""
    assert classify_http_error(500, "Internal Server Error") is FailoverReason.server_error


def test_classify_http_error_server_error_502() -> None:
    """HTTP 502 maps to FailoverReason.server_error."""
    assert classify_http_error(502, "Bad Gateway") is FailoverReason.server_error


def test_classify_http_error_server_error_504() -> None:
    """HTTP 504 maps to FailoverReason.server_error."""
    assert classify_http_error(504, "Gateway Timeout") is FailoverReason.server_error


def test_classify_http_error_timeout() -> None:
    """HTTP 408 maps to FailoverReason.timeout."""
    assert classify_http_error(408, "Request Timeout") is FailoverReason.timeout


def test_classify_http_error_model_not_found() -> None:
    """HTTP 404 maps to FailoverReason.model_not_found."""
    assert classify_http_error(404, "Not Found") is FailoverReason.model_not_found


def test_classify_http_error_unknown() -> None:
    """Unmapped status codes map to FailoverReason.unknown."""
    assert classify_http_error(418, "I'm a teapot") is FailoverReason.unknown


# ---------------------------------------------------------------------------
# 4. CredentialPool — rotation
# ---------------------------------------------------------------------------


def test_credential_pool_rotation() -> None:
    """When the first key is cooling down, next_eligible() returns the second."""
    pool = _make_pool("key-A", "key-B")
    # Put key-A in cooldown for 60 seconds.
    pool.mark_failed("key-A", cooldown_seconds=60.0)

    entry = pool.next_eligible()
    assert entry is not None
    assert entry.api_key == "key-B"


def test_credential_pool_rotation_returns_first_when_available() -> None:
    """When no credential is in cooldown, next_eligible() returns the first."""
    pool = _make_pool("key-A", "key-B")
    entry = pool.next_eligible()
    assert entry is not None
    assert entry.api_key == "key-A"


# ---------------------------------------------------------------------------
# 5. CredentialPool — all cooling down
# ---------------------------------------------------------------------------


def test_credential_pool_all_cooling() -> None:
    """When all credentials are cooling down, next_eligible() returns None."""
    pool = _make_pool("key-A", "key-B")
    pool.mark_failed("key-A", cooldown_seconds=60.0)
    pool.mark_failed("key-B", cooldown_seconds=60.0)

    assert pool.all_cooling_down() is True
    assert pool.next_eligible() is None


def test_credential_pool_mark_success_resets_cooldown() -> None:
    """mark_success() clears cooldown and failure_count."""
    pool = _make_pool("key-A")
    pool.mark_failed("key-A", cooldown_seconds=60.0)
    assert pool.all_cooling_down() is True

    pool.mark_success("key-A")
    assert pool.all_cooling_down() is False
    entry = pool.next_eligible()
    assert entry is not None
    assert entry.failure_count == 0
    assert entry.cooldown_until == 0.0


# ---------------------------------------------------------------------------
# 6. RetryPolicy — exponential backoff
# ---------------------------------------------------------------------------


def test_retry_policy_exponential_backoff() -> None:
    """delay_for(attempt) must follow the exponential formula (no jitter)."""
    policy = RetryPolicy(base_delay_ms=500, max_delay_ms=30_000, jitter=False)

    # attempt 0: 500 * 2^0 = 500 ms → 0.5 s
    assert policy.delay_for(0) == pytest.approx(0.5)
    # attempt 1: 500 * 2^1 = 1000 ms → 1.0 s
    assert policy.delay_for(1) == pytest.approx(1.0)
    # attempt 2: 500 * 2^2 = 2000 ms → 2.0 s
    assert policy.delay_for(2) == pytest.approx(2.0)
    # attempt 3: 500 * 2^3 = 4000 ms → 4.0 s
    assert policy.delay_for(3) == pytest.approx(4.0)


def test_retry_policy_respects_max_delay() -> None:
    """delay_for() must not exceed max_delay_ms (ignoring jitter)."""
    policy = RetryPolicy(base_delay_ms=500, max_delay_ms=1000, jitter=False)
    # attempt 10: 500 * 2^10 = 512_000 ms → clamped to 1000 ms → 1.0 s
    assert policy.delay_for(10) == pytest.approx(1.0)


def test_retry_policy_jitter_adds_non_negative_value() -> None:
    """With jitter=True, delay_for() must be >= the base exponential delay."""
    policy = RetryPolicy(base_delay_ms=100, max_delay_ms=30_000, jitter=True)
    # Run several times to guard against lucky random draws.
    for _ in range(20):
        delay = policy.delay_for(0)
        assert delay >= 0.1  # base is 100 ms = 0.1 s


# ---------------------------------------------------------------------------
# 7. FailoverChain — retries on rate limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failover_chain_retries_on_rate_limit() -> None:
    """The chain should retry after a 429 and succeed on the second attempt.

    We patch time.time() so that after the first failure the cooldown
    window is considered expired, allowing the same credential to be
    reused on the next attempt.
    """
    pool = _make_pool("key-A")
    policy = _make_policy(max_retries=3, base_delay_ms=0, jitter=False)

    call_count = 0

    async def _complete(_request: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_httpx_status_error(429, "rate limited")
        return _make_response("success")

    mock_gateway = MagicMock()
    mock_gateway.complete = _complete

    def factory(_api_key: str) -> Any:
        return mock_gateway

    chain = FailoverChain(gateway_factory=factory, pool=pool, policy=policy)

    # Simulate that time advances past the 60-second cooldown between retries.
    # We use a counter so that the first call (at failure) sets the cooldown,
    # and subsequent calls (at the retry eligibility check) see a time far in
    # the future.
    _real_time = time.time
    time_calls: list[float] = []

    def _fake_time() -> float:
        # Return an ever-increasing timestamp; jump past cooldown after call 1.
        t = _real_time() + len(time_calls) * 120.0
        time_calls.append(t)
        return t

    with (
        patch("hi_agent.llm.failover.time") as mock_time,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_time.time.side_effect = _fake_time
        response = await chain.complete(_make_request())

    assert response.content == "success"
    assert call_count == 2


@pytest.mark.asyncio
async def test_failover_chain_succeeds_on_first_try() -> None:
    """When the gateway succeeds immediately, no retry is attempted."""
    pool = _make_pool("key-A")
    policy = _make_policy(max_retries=3)

    mock_gateway = MagicMock()
    mock_gateway.complete = AsyncMock(return_value=_make_response("first-try"))

    chain = FailoverChain(gateway_factory=lambda k: mock_gateway, pool=pool, policy=policy)
    response = await chain.complete(_make_request())

    assert response.content == "first-try"
    mock_gateway.complete.assert_awaited_once()


# ---------------------------------------------------------------------------
# 8. FailoverChain — exhausts all credentials on auth_permanent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failover_chain_exhausts_credentials() -> None:
    """When every credential hits auth_permanent, FailoverError must be raised."""
    pool = _make_pool("key-A", "key-B")
    policy = _make_policy(max_retries=5, base_delay_ms=0, jitter=False)

    async def _complete(_request: LLMRequest) -> LLMResponse:
        # "invalid_api_key" in body triggers auth_permanent classification.
        raise _make_httpx_status_error(401, '{"error": "invalid_api_key"}')

    mock_gateway = MagicMock()
    mock_gateway.complete = _complete

    chain = FailoverChain(gateway_factory=lambda k: mock_gateway, pool=pool, policy=policy)

    with pytest.raises(FailoverError) as exc_info:
        await chain.complete(_make_request())

    err = exc_info.value
    assert err.reason in (FailoverReason.auth_permanent, FailoverReason.auth)
    assert pool.all_cooling_down() is True


@pytest.mark.asyncio
async def test_failover_chain_raises_when_pool_starts_empty() -> None:
    """If pool has all credentials in cooldown from the start, raise immediately."""
    pool = _make_pool("key-A")
    # Pre-warm the cooldown so next_eligible() returns None immediately.
    pool.mark_failed("key-A", cooldown_seconds=3600.0)

    policy = _make_policy(max_retries=3)
    chain = FailoverChain(gateway_factory=lambda k: MagicMock(), pool=pool, policy=policy)

    with pytest.raises(FailoverError):
        await chain.complete(_make_request())


# ---------------------------------------------------------------------------
# make_credential_pool_from_env
# ---------------------------------------------------------------------------


def test_make_credential_pool_from_env_single_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single key in ANTHROPIC_API_KEY produces a pool with one entry."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-single")
    pool = make_credential_pool_from_env()
    entry = pool.next_eligible()
    assert entry is not None
    assert entry.api_key == "sk-single"
    assert entry.provider == "anthropic"


def test_make_credential_pool_from_env_multiple_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comma-separated keys in ANTHROPIC_API_KEY produce multiple pool entries."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-one,sk-two,sk-three")
    pool = make_credential_pool_from_env()
    # All three should be eligible initially.
    keys_seen: list[str] = []
    for _ in range(3):
        entry = pool.next_eligible()
        assert entry is not None
        keys_seen.append(entry.api_key)
        pool.mark_failed(entry.api_key, cooldown_seconds=3600.0)
    assert "sk-one" in keys_seen


def test_make_credential_pool_from_env_missing_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing environment variable must raise ValueError."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        make_credential_pool_from_env()


def test_make_credential_pool_from_env_custom_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom env_var and provider arguments are respected."""
    monkeypatch.setenv("MY_LLM_KEY", "custom-key")
    pool = make_credential_pool_from_env(env_var="MY_LLM_KEY", provider="custom-provider")
    entry = pool.next_eligible()
    assert entry is not None
    assert entry.api_key == "custom-key"
    assert entry.provider == "custom-provider"


# ---------------------------------------------------------------------------
# FailoverChain — stream fallback (gateway without stream method)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failover_chain_stream_fallback_to_complete() -> None:
    """stream() falls back to complete() when the gateway has no stream() method."""
    pool = _make_pool("key-A")
    policy = _make_policy(max_retries=1)

    expected_response = _make_response("streamed-via-complete")
    mock_gateway = MagicMock(spec=["complete", "supports_model"])
    mock_gateway.complete = AsyncMock(return_value=expected_response)
    # Explicitly ensure no 'stream' attribute.
    assert not hasattr(mock_gateway, "stream")

    chain = FailoverChain(gateway_factory=lambda k: mock_gateway, pool=pool, policy=policy)

    chunks = []
    async for chunk in chain.stream(_make_request()):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0] is expected_response


# ---------------------------------------------------------------------------
# CredentialPool — failure_count increment
# ---------------------------------------------------------------------------


def test_credential_pool_failure_count_increments() -> None:
    """Each mark_failed() call increments failure_count."""
    pool = _make_pool("key-A")
    pool.mark_failed("key-A", cooldown_seconds=0.001)
    pool.mark_failed("key-A", cooldown_seconds=0.001)
    entry = pool._entries[0]
    assert entry.failure_count == 2


def test_credential_pool_permanent_cooldown() -> None:
    """Passing float('inf') as cooldown_seconds suspends the credential permanently."""
    pool = _make_pool("key-A")
    pool.mark_failed("key-A", cooldown_seconds=float("inf"))
    assert pool.all_cooling_down() is True
    assert pool.next_eligible() is None
