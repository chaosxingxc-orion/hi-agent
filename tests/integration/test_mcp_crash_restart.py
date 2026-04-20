"""Tests for MCP crash-restart with backoff (HI-W10-005)."""

import contextlib
from unittest.mock import patch

import pytest
from hi_agent.mcp.transport import _MAX_RESTART_ATTEMPTS, MCPTransportError, StdioMCPTransport


def _make_failing_transport():
    """Transport whose Popen always raises OSError."""
    transport = StdioMCPTransport(command=["nonexistent-cmd-xyz-abc"])
    return transport


def test_transport_marks_unavailable_after_max_restarts():
    """After _MAX_RESTART_ATTEMPTS OSErrors, transport._unavailable is True."""
    transport = _make_failing_transport()

    with (
        patch("hi_agent.mcp.transport.time.sleep"),
        patch("subprocess.Popen", side_effect=OSError("not found")),
    ):
        for _ in range(_MAX_RESTART_ATTEMPTS):
            with contextlib.suppress(MCPTransportError):
                transport._ensure_running()

    assert transport._unavailable is True


def test_unavailable_transport_raises_immediately():
    """Once marked unavailable, _ensure_running raises without spawning."""
    transport = _make_failing_transport()
    transport._unavailable = True
    with pytest.raises(MCPTransportError, match="permanently unavailable"):
        transport._ensure_running()


def test_restart_attempt_counter_increments():
    """Each failed spawn increments _restart_attempts."""
    transport = _make_failing_transport()
    with (
        patch("hi_agent.mcp.transport.time.sleep"),
        patch("subprocess.Popen", side_effect=OSError("not found")),
        contextlib.suppress(MCPTransportError),
    ):
        transport._ensure_running()
    assert transport._restart_attempts >= 1


def test_backoff_sleep_called_on_restart():
    """time.sleep is called with increasing delay on restart attempts."""
    transport = _make_failing_transport()
    transport._restart_attempts = 2  # simulate already tried twice

    sleep_calls = []
    with (
        patch("hi_agent.mcp.transport.time.sleep", side_effect=lambda d: sleep_calls.append(d)),
        patch("subprocess.Popen", side_effect=OSError("not found")),
        contextlib.suppress(MCPTransportError),
    ):
        transport._ensure_running()

    # Should have slept once with delay = 1.0 * 2^(2-1) = 2.0
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(2.0)
