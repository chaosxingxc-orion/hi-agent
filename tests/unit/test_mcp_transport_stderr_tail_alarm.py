"""Unit test: mcp/transport.py increments Rule 7 counter on stderr tail failure.

Layer 1 — Unit: the method under test is MCPTransport.get_stderr_tail().
We inject a broken _stderr_buf to force the exception path, then assert
the MetricsCollector singleton was incremented.
"""

from __future__ import annotations

import collections

import pytest
from hi_agent.observability.collector import MetricsCollector, set_metrics_collector


@pytest.fixture(autouse=True)
def clean_metrics_singleton():
    """Install a fresh MetricsCollector singleton and clean up after each test."""
    collector = MetricsCollector()
    set_metrics_collector(collector)
    yield collector
    set_metrics_collector(None)


def test_stderr_tail_failure_increments_counter(clean_metrics_singleton: MetricsCollector) -> None:
    """When _stderr_buf raises during list(), get_stderr_tail increments the alarm counter."""
    from hi_agent.mcp.transport import StdioMCPTransport

    transport = StdioMCPTransport.__new__(StdioMCPTransport)
    # Inject a broken buffer that raises when iterated.
    class _BrokenBuf:
        def __iter__(self):
            raise RuntimeError("simulated buffer failure")

    transport._stderr_buf = _BrokenBuf()  # type: ignore[attr-defined]  expiry_wave: Wave 26

    result = transport.get_stderr_tail(n=10)
    assert result == []

    snapshot = clean_metrics_singleton.snapshot()
    counter = snapshot.get("hi_agent_mcp_stderr_tail_failure_total", {})
    total = sum(counter.values()) if counter else 0
    assert total >= 1, f"Expected counter increment, got snapshot: {snapshot}"


def test_stderr_tail_no_failure_does_not_increment(
    clean_metrics_singleton: MetricsCollector,
) -> None:
    """Normal get_stderr_tail() execution does NOT increment the failure counter."""
    from hi_agent.mcp.transport import StdioMCPTransport

    transport = StdioMCPTransport.__new__(StdioMCPTransport)
    transport._stderr_buf = collections.deque(["line1", "line2", "line3"], maxlen=100)

    result = transport.get_stderr_tail(n=2)
    assert result == ["line2", "line3"]

    snapshot = clean_metrics_singleton.snapshot()
    counter = snapshot.get("hi_agent_mcp_stderr_tail_failure_total", {})
    total = sum(counter.values()) if counter else 0
    assert total == 0, f"Unexpected counter increment: {snapshot}"
