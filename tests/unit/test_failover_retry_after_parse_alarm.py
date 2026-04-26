"""Unit test: failover.py increments Rule 7 counter on Retry-After parse failure.

Layer 1 — Unit: the method under test is FailoverChain._parse_retry_after().
MetricsCollector singleton is set so the lazy get_metrics_collector() call
inside the except block returns a real collector whose counters can be asserted.
"""

from __future__ import annotations

import httpx
import pytest
from hi_agent.observability.collector import MetricsCollector, set_metrics_collector


@pytest.fixture(autouse=True)
def clean_metrics_singleton():
    """Install a fresh MetricsCollector singleton and clean up after each test."""
    collector = MetricsCollector()
    set_metrics_collector(collector)
    yield collector
    set_metrics_collector(None)


def _make_http_error_with_retry_after(header_value: str) -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError with a Retry-After header of the given value."""
    response = httpx.Response(
        status_code=429,
        headers={"retry-after": header_value},
        request=httpx.Request("POST", "https://example.com/v1"),
    )
    return httpx.HTTPStatusError(
        "429 Too Many Requests",
        request=response.request,
        response=response,
    )


def test_invalid_retry_after_increments_counter(clean_metrics_singleton: MetricsCollector) -> None:
    """Non-numeric Retry-After header value causes hi_agent_retry_after_parse_total to increment."""
    from hi_agent.llm.failover import FailoverChain

    exc = _make_http_error_with_retry_after("next-tuesday")
    result = FailoverChain._parse_retry_after(exc)

    assert result is None
    snapshot = clean_metrics_singleton.snapshot()
    counter = snapshot.get("hi_agent_retry_after_parse_total", {})
    # The label set is outcome=invalid; key format is 'outcome="invalid"'
    total = sum(counter.values())
    assert total >= 1, f"Expected counter increment, got snapshot: {snapshot}"


def test_valid_retry_after_does_not_increment_counter(
    clean_metrics_singleton: MetricsCollector,
) -> None:
    """A parseable numeric Retry-After header does NOT increment the failure counter."""
    from hi_agent.llm.failover import FailoverChain

    exc = _make_http_error_with_retry_after("30")
    result = FailoverChain._parse_retry_after(exc)

    assert result == 30.0
    snapshot = clean_metrics_singleton.snapshot()
    counter = snapshot.get("hi_agent_retry_after_parse_total", {})
    total = sum(counter.values()) if counter else 0
    assert total == 0, f"Unexpected counter increment: {snapshot}"


def test_absent_retry_after_does_not_increment_counter(
    clean_metrics_singleton: MetricsCollector,
) -> None:
    """Absent Retry-After header returns None without incrementing the counter."""
    from hi_agent.llm.failover import FailoverChain

    response = httpx.Response(
        status_code=429,
        request=httpx.Request("POST", "https://example.com/v1"),
    )
    exc = httpx.HTTPStatusError(
        "429",
        request=response.request,
        response=response,
    )
    result = FailoverChain._parse_retry_after(exc)

    assert result is None
    snapshot = clean_metrics_singleton.snapshot()
    counter = snapshot.get("hi_agent_retry_after_parse_total", {})
    total = sum(counter.values()) if counter else 0
    assert total == 0
