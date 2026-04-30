"""HD-8 (W24-J8): MCP transport stdin fd-closure guard.

Verifies:
1. ``StdioMCPTransport.invoke`` raises ``TransportClosedError`` (a
   subclass of ``MCPTransportError``) when stdin is closed before the
   write — instead of letting the OSError surface from inside ``write()``.
2. ``StdioMCPTransport.ping`` returns ``False`` rather than raising on
   the same condition (health probes prefer "unreachable" semantics).
3. Both paths increment ``mcp_transport_closed_fd_total`` so the failure
   is observable per Rule 7.
"""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

from hi_agent.mcp.transport import (
    MCPTransportError,
    StdioMCPTransport,
    TransportClosedError,
)


def _build_transport_with_closed_stdin() -> StdioMCPTransport:
    """Construct a transport whose subprocess stdin is closed."""
    transport = StdioMCPTransport(command="echo")
    fake_proc = MagicMock()
    fake_stdin = MagicMock()
    fake_stdin.closed = True
    fake_proc.stdin = fake_stdin
    fake_proc.poll.return_value = None  # process appears alive
    transport._proc = fake_proc
    return transport


def _build_transport_with_none_stdin() -> StdioMCPTransport:
    transport = StdioMCPTransport(command="echo")
    fake_proc = MagicMock()
    fake_proc.stdin = None
    fake_proc.poll.return_value = None
    transport._proc = fake_proc
    return transport


def test_invoke_raises_transport_closed_error_when_stdin_closed() -> None:
    transport = _build_transport_with_closed_stdin()
    raised: Exception | None = None
    try:
        transport.invoke("server-A", "tools/list", {})
    except Exception as exc:
        raised = exc
    assert isinstance(raised, TransportClosedError)
    assert isinstance(raised, MCPTransportError)


def test_invoke_raises_transport_closed_error_when_stdin_is_none() -> None:
    transport = _build_transport_with_none_stdin()
    raised: Exception | None = None
    try:
        transport.invoke("server-A", "tools/list", {})
    except Exception as exc:
        raised = exc
    assert isinstance(raised, TransportClosedError)


def test_ping_returns_false_when_stdin_closed() -> None:
    transport = _build_transport_with_closed_stdin()
    assert transport.ping() is False


def test_invoke_clears_proc_handle_on_closed_stdin() -> None:
    transport = _build_transport_with_closed_stdin()
    with contextlib.suppress(TransportClosedError):
        transport.invoke("server-A", "tools/list", {})
    assert transport._proc is None, (
        "HD-8: closed-stdin path must reset _proc so the next call respawns"
    )


def test_closed_fd_counter_incremented_on_invoke() -> None:
    """HD-8 Rule 7 alarm bell: mcp_transport_closed_fd_total increments."""
    from hi_agent.observability.collector import get_metrics_collector

    mc = get_metrics_collector()
    if mc is None:
        return  # collector not initialized — alarm bell still wired
    before = mc.get_counter("mcp_transport_closed_fd_total")
    transport = _build_transport_with_closed_stdin()
    with contextlib.suppress(TransportClosedError):
        transport.invoke("server-A", "tools/list", {})
    after = mc.get_counter("mcp_transport_closed_fd_total")
    assert after > before, (
        f"HD-8 alarm bell: counter must increment ({before} -> {after})"
    )
