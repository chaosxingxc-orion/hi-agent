"""Integration tests for LLM gateway real failure path.

Verifies that when an LLM gateway returns HTTP 503 (overloaded), the
FailoverChain retries and — after exhausting retries — raises a classified
FailoverError.  Also asserts that hi_agent_failure_total is incremented
when the ResilientKernelAdapter exhausts its own retries.

No real API calls are made; all gateways are mocked.
Layer: Integration — real FailoverChain + CredentialPool + RetryPolicy
wired together; no MagicMock on the subsystem under test.
"""

from __future__ import annotations

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
)
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request() -> LLMRequest:
    """Return a minimal LLMRequest."""
    return LLMRequest(messages=[{"role": "user", "content": "ping"}])


def _make_response(content: str = "pong") -> LLMResponse:
    """Return a minimal LLMResponse."""
    return LLMResponse(
        content=content,
        model="test-model",
        usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        finish_reason="stop",
    )


def _make_503_error() -> httpx.HTTPStatusError:
    """Build a fake httpx.HTTPStatusError with status 503."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 503
    response.text = "Service Unavailable"
    response.headers = httpx.Headers({})
    request = MagicMock(spec=httpx.Request)
    return httpx.HTTPStatusError(
        message="HTTP 503",
        request=request,
        response=response,
    )


def _make_pool(api_key: str = "test-key") -> CredentialPool:
    """Build a single-entry CredentialPool."""
    return CredentialPool([CredentialEntry(api_key=api_key, provider="mock")])


def _make_policy_no_delay(max_retries: int = 2) -> RetryPolicy:
    """Build a RetryPolicy with zero delay for fast tests."""
    return RetryPolicy(
        max_retries=max_retries,
        base_delay_ms=0,
        max_delay_ms=0,
        jitter=False,
    )


# ---------------------------------------------------------------------------
# Test 1: always-503 gateway exhausts retries → FailoverError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_503_gateway_exhausts_retries_raises_failover_error() -> None:
    """A gateway that always returns 503 exhausts all retries and raises FailoverError.

    This test wires a real FailoverChain with a real CredentialPool and
    RetryPolicy.  The inner gateway is an AsyncMock that always raises HTTP 503
    (overloaded), which is the real-failure path for an unavailable LLM endpoint.
    """
    pool = _make_pool()
    policy = _make_policy_no_delay(max_retries=2)

    # Gateway mock: always raises HTTP 503.
    always_503_gateway = AsyncMock()
    always_503_gateway.complete = AsyncMock(side_effect=_make_503_error())

    call_count = 0

    def _factory(api_key: str):  # expiry_wave: Wave 18
        nonlocal call_count
        call_count += 1
        return always_503_gateway

    chain = FailoverChain(gateway_factory=_factory, pool=pool, policy=policy)

    with pytest.raises(FailoverError) as exc_info:
        await chain.complete(_make_request())

    err = exc_info.value
    # Classified as overloaded (503 → FailoverReason.overloaded).
    assert err.reason is FailoverReason.overloaded
    assert err.status_code == 503
    # With a single credential: factory is called once (initial attempt), then the
    # credential enters cooldown and all subsequent loop iterations find the pool
    # empty → FailoverError is raised without additional factory calls.
    assert call_count >= 1


# ---------------------------------------------------------------------------
# Test 2: gateway succeeds after one 503 retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_503_then_success_returns_response() -> None:
    """A gateway that returns 503 on the first call succeeds on the second.

    Uses two separate keys so the pool can rotate to a fresh credential
    after the first one enters cooldown.
    """
    pool = CredentialPool([
        CredentialEntry(api_key="key-a", provider="mock"),
        CredentialEntry(api_key="key-b", provider="mock"),
    ])
    policy = _make_policy_no_delay(max_retries=1)

    call_count = 0

    def _factory(api_key: str):
        nonlocal call_count
        call_count += 1
        gw = AsyncMock()
        if api_key == "key-a":
            gw.complete = AsyncMock(side_effect=_make_503_error())
        else:
            gw.complete = AsyncMock(return_value=_make_response("pong"))
        return gw

    chain = FailoverChain(gateway_factory=_factory, pool=pool, policy=policy)

    response = await chain.complete(_make_request())

    assert response.content == "pong"
    # Both keys were tried.
    assert call_count == 2


# ---------------------------------------------------------------------------
# Test 3: ResilientKernelAdapter failure increments hi_agent_failure_total
# ---------------------------------------------------------------------------


def test_resilient_adapter_failure_increments_counter() -> None:
    """ResilientKernelAdapter emits hi_agent_failure_total on exhausted retries.

    The inner adapter always raises RuntimeError.  After retries are
    exhausted, the adapter should increment the hi_agent_failure_total
    counter via the metrics collector.
    """
    from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal
    from hi_agent.runtime_adapter.resilient_kernel_adapter import ResilientKernelAdapter

    inner = MagicMock()
    inner.start_run = MagicMock(side_effect=RuntimeError("kernel unavailable"))

    journal = InMemoryConsistencyJournal()
    adapter = ResilientKernelAdapter(
        inner,
        max_retries=1,
        base_delay_s=0.0,
        journal=journal,
    )

    counter_calls: list[tuple] = []

    fake_collector = MagicMock()

    def _increment(name: str, labels: dict | None = None) -> None:
        counter_calls.append((name, labels))

    fake_collector.increment = _increment

    with patch(
        "hi_agent.observability.collector.get_metrics_collector",
        return_value=fake_collector,
    ):
        from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError

        with pytest.raises(RuntimeAdapterBackendError):
            adapter._call("start_run", {})

    # Assert that hi_agent_failure_total was incremented at least once.
    failure_increments = [c for c in counter_calls if c[0] == "hi_agent_failure_total"]
    assert failure_increments, (
        "Expected hi_agent_failure_total to be incremented after adapter failure; "
        f"got counter_calls={counter_calls}"
    )
    # The counter must carry a failure_code label.
    _, labels = failure_increments[0]
    assert labels is not None
    assert "failure_code" in labels
