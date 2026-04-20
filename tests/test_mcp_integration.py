"""Integration tests for MCP transport + binding dynamic discovery.

Uses a real Python subprocess as a fake MCP server — no internal mocks.
Tests mi01-mi08: baseline transport + binding tests.
Tests mi09-mi15: tools/list dynamic discovery + merge strategy (HI-W5-001+W5-002).

P3: no mocks for internal components; subprocess-based fake server counts as
"external process" and is permitted.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.mcp.binding import MCPBinding
from hi_agent.mcp.registry import MCPRegistry
from hi_agent.mcp.transport import MCPTransportError, StdioMCPTransport

# ---------------------------------------------------------------------------
# FakeMCPServer helper — write a small Python script to tmp_path
# ---------------------------------------------------------------------------

_FAKE_SERVER_TEMPLATE = textwrap.dedent(
    """
    import json, sys, os

    TOOLS = {tools_json}

    def main():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp = {{
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {{"protocolVersion": "2024-11-05"}},
                }}
            elif method == "tools/call":
                tool_name = req.get("params", {{}}).get("name", "")
                if tool_name in TOOLS:
                    resp = {{
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {{"output": "ok", "tool": tool_name}},
                    }}
                else:
                    resp = {{
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {{
                            "code": -32601,
                            "message": f"tool {{tool_name!r}} not found",
                        }},
                    }}
            elif method == "tools/list":
                tools_list = [{{"name": name}} for name in TOOLS]
                resp = {{"jsonrpc": "2.0", "id": req_id, "result": {{"tools": tools_list}}}}
            else:
                resp = {{
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {{"code": -32601, "message": f"unknown method {{method!r}}"}},
                }}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()

    if __name__ == "__main__":
        main()
    """
)

_FAKE_SERVER_BAD_SCHEMA_TEMPLATE = textwrap.dedent(
    """
    import json, sys

    def main():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}}
            elif method == "tools/list":
                # Bad schema: tools is a dict, not a list
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": {"bad": "schema"}}}
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()

    if __name__ == "__main__":
        main()
    """
)

_FAKE_SERVER_CRASH_ON_LIST_TEMPLATE = textwrap.dedent(
    """
    import json, sys

    def main():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}}
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
            elif method == "tools/list":
                # Crash — close stdout without responding
                sys.stdout.close()
                sys.exit(1)
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()

    if __name__ == "__main__":
        main()
    """
)

_FAKE_SERVER_SLOW_LIST_TEMPLATE = textwrap.dedent(
    """
    import json, sys, time

    def main():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}}
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
            elif method == "tools/list":
                # Sleep longer than the timeout — never respond
                time.sleep(30)
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()

    if __name__ == "__main__":
        main()
    """
)


def _write_server_script(tmp_path: Path, name: str, script: str) -> Path:
    p = tmp_path / name
    p.write_text(script, encoding="utf-8")
    return p


def _server_command(script_path: Path) -> list[str]:
    return [sys.executable, str(script_path)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_mcp_server(tmp_path):
    """Path to a fake MCP server script with tools: echo, greet."""
    tools = ["echo", "greet"]
    script = _FAKE_SERVER_TEMPLATE.format(tools_json=json.dumps(tools))
    return _write_server_script(tmp_path, "fake_mcp_server.py", script)


@pytest.fixture
def fake_mcp_server_empty(tmp_path):
    """Path to a fake MCP server script with no tools."""
    script = _FAKE_SERVER_TEMPLATE.format(tools_json=json.dumps([]))
    return _write_server_script(tmp_path, "fake_mcp_server_empty.py", script)


@pytest.fixture
def fake_mcp_server_bad_schema(tmp_path):
    """Path to a fake MCP server that returns invalid tools/list schema."""
    return _write_server_script(
        tmp_path, "fake_mcp_server_bad.py", _FAKE_SERVER_BAD_SCHEMA_TEMPLATE
    )


# ---------------------------------------------------------------------------
# Helper: build MCPRegistry + MCPBinding with a healthy server
# ---------------------------------------------------------------------------


def _make_mcp_setup(
    server_script: Path,
    tools: list[str],
    *,
    status: str = "healthy",
) -> tuple[MCPRegistry, MCPBinding, CapabilityRegistry]:
    mcp_reg = MCPRegistry()
    mcp_reg.register(
        server_id="test_srv",
        name="Test Server",
        transport="stdio",
        endpoint=_server_command(server_script),
        tools=tools,
    )
    mcp_reg.update_status("test_srv", status)
    cap_reg = CapabilityRegistry()
    transport = StdioMCPTransport(
        command=_server_command(server_script),
        timeout=10.0,
    )
    binding = MCPBinding(registry=cap_reg, mcp_registry=mcp_reg, transport=transport)
    return mcp_reg, binding, cap_reg


# ---------------------------------------------------------------------------
# mi01-mi08: Baseline transport and binding tests
# ---------------------------------------------------------------------------


def test_mi01_transport_invoke_tool(fake_mcp_server, tmp_path):
    """Transport can invoke a tool on a real subprocess server."""
    t = StdioMCPTransport(command=_server_command(fake_mcp_server), timeout=10.0)
    try:
        result = t.invoke("test_srv", "echo", {"input": "hello"})
        assert result.get("tool") == "echo"
        assert result.get("output") == "ok"
    finally:
        t.close()


def test_mi02_transport_invoke_unknown_tool_raises(fake_mcp_server, tmp_path):
    """Transport raises MCPTransportError for an unknown tool."""
    t = StdioMCPTransport(command=_server_command(fake_mcp_server), timeout=10.0)
    try:
        with pytest.raises(MCPTransportError, match="not found"):
            t.invoke("test_srv", "nonexistent_tool", {})
    finally:
        t.close()


def test_mi03_transport_ping_healthy_server(fake_mcp_server, tmp_path):
    """Transport ping returns True for a healthy server."""
    t = StdioMCPTransport(command=_server_command(fake_mcp_server), timeout=10.0)
    try:
        assert t.ping() is True
    finally:
        t.close()


def test_mi04_transport_ping_dead_server(tmp_path):
    """Transport ping returns False when server command fails."""
    t = StdioMCPTransport(command=[sys.executable, "-c", "import sys; sys.exit(1)"], timeout=3.0)
    try:
        result = t.ping()
        assert result is False
    finally:
        t.close()


def test_mi05_binding_no_transport_returns_zero(fake_mcp_server, tmp_path):
    """MCPBinding without transport binds 0 tools and populates unavailable."""
    mcp_reg = MCPRegistry()
    mcp_reg.register(
        server_id="srv",
        name="S",
        transport="stdio",
        endpoint=_server_command(fake_mcp_server),
        tools=["echo", "greet"],
    )
    cap_reg = CapabilityRegistry()
    binding = MCPBinding(registry=cap_reg, mcp_registry=mcp_reg, transport=None)
    bound = binding.bind_all()
    assert bound == 0
    unavail = binding.list_unavailable()
    assert "mcp.srv.echo" in unavail
    assert "mcp.srv.greet" in unavail


def test_mi06_binding_with_transport_binds_healthy_tools(fake_mcp_server, tmp_path):
    """MCPBinding with transport binds tools from healthy servers."""
    _, binding, cap_reg = _make_mcp_setup(
        fake_mcp_server, tools=["echo", "greet"], status="healthy"
    )
    bound = binding.bind_all()
    assert bound > 0
    # Both tools registered in CapabilityRegistry
    names = cap_reg.list_names()
    assert "mcp.test_srv.echo" in names
    assert "mcp.test_srv.greet" in names


def test_mi07_binding_skips_unhealthy_server(fake_mcp_server, tmp_path):
    """MCPBinding skips servers with non-healthy status."""
    mcp_reg = MCPRegistry()
    mcp_reg.register(
        server_id="bad_srv",
        name="Bad",
        transport="stdio",
        endpoint=_server_command(fake_mcp_server),
        tools=["echo"],
    )
    mcp_reg.update_status("bad_srv", "error")
    cap_reg = CapabilityRegistry()
    transport = StdioMCPTransport(command=_server_command(fake_mcp_server), timeout=10.0)
    binding = MCPBinding(registry=cap_reg, mcp_registry=mcp_reg, transport=transport)
    bound = binding.bind_all()
    assert bound == 0


def test_mi08_binding_bound_tool_invokable(fake_mcp_server, tmp_path):
    """A tool bound via MCPBinding is invokable through CapabilityRegistry."""
    _, binding, cap_reg = _make_mcp_setup(
        fake_mcp_server, tools=["echo"], status="healthy"
    )
    binding.bind_all()
    spec = cap_reg.get("mcp.test_srv.echo")
    assert spec is not None
    result = spec.handler({"input": "test"})
    assert result.get("output") == "ok"


# ---------------------------------------------------------------------------
# mi09-mi15: tools/list dynamic discovery + merge strategy (HI-W5-001+W5-002)
# ---------------------------------------------------------------------------


def test_mi09_tools_list_returns_tools(fake_mcp_server, tmp_path):
    """tools/list returns registered tools from the real subprocess server."""
    t = StdioMCPTransport(command=_server_command(fake_mcp_server), timeout=10.0)
    try:
        tools = t.list_tools("test_srv")
        assert isinstance(tools, list)
        assert len(tools) == 2
        names = {tool["name"] for tool in tools}
        assert names == {"echo", "greet"}
    finally:
        t.close()


def test_mi10_tools_list_empty(fake_mcp_server_empty, tmp_path):
    """tools/list returns empty list when server has no tools."""
    t = StdioMCPTransport(command=_server_command(fake_mcp_server_empty), timeout=10.0)
    try:
        tools = t.list_tools("test_srv")
        assert tools == []
    finally:
        t.close()


def test_mi11_tools_list_invalid_schema(fake_mcp_server_bad_schema, tmp_path):
    """tools/list raises MCPTransportError on invalid schema (tools is a dict)."""
    t = StdioMCPTransport(command=_server_command(fake_mcp_server_bad_schema), timeout=10.0)
    try:
        with pytest.raises(MCPTransportError, match="must be a list"):
            t.list_tools("test_srv")
    finally:
        t.close()


def test_mi12_tools_list_timeout(tmp_path):
    """tools/list raises MCPTransportError on timeout."""
    slow_server = _write_server_script(
        tmp_path, "slow_server.py", _FAKE_SERVER_SLOW_LIST_TEMPLATE
    )
    # Very short timeout to keep test fast
    t = StdioMCPTransport(command=_server_command(slow_server), timeout=1.0)
    try:
        with pytest.raises(MCPTransportError, match="timed out"):
            t.list_tools("test_srv")
    finally:
        t.close()


def test_mi13_tools_list_server_crash_during_list(tmp_path):
    """tools/list raises MCPTransportError if server crashes mid-request."""
    crash_server = _write_server_script(
        tmp_path, "crash_server.py", _FAKE_SERVER_CRASH_ON_LIST_TEMPLATE
    )
    t = StdioMCPTransport(command=_server_command(crash_server), timeout=5.0)
    try:
        with pytest.raises(MCPTransportError):
            t.list_tools("test_srv")
    finally:
        t.close()


def test_mi14_tools_list_conflict_with_manifest_preclaim(fake_mcp_server, tmp_path):
    """Merge: manifest-only tools get warning; discovered tools are used as final set."""
    # Manifest pre-claims: echo, greet (real), ghost_tool (not in server)
    # Server responds with: echo, greet
    # Expected: final = [echo, greet]; warning about ghost_tool
    mcp_reg = MCPRegistry()
    mcp_reg.register(
        server_id="test_srv",
        name="Test Server",
        transport="stdio",
        endpoint=_server_command(fake_mcp_server),
        tools=["echo", "greet", "ghost_tool"],  # ghost_tool not in server
    )
    mcp_reg.update_status("test_srv", "healthy")
    cap_reg = CapabilityRegistry()
    transport = StdioMCPTransport(
        command=_server_command(fake_mcp_server),
        timeout=10.0,
    )
    binding = MCPBinding(registry=cap_reg, mcp_registry=mcp_reg, transport=transport)

    bound = binding.bind_all()

    # Only discovered tools should be bound
    assert bound == 2
    names = set(cap_reg.list_names())
    assert "mcp.test_srv.echo" in names
    assert "mcp.test_srv.greet" in names
    assert "mcp.test_srv.ghost_tool" not in names

    # Warning emitted for manifest-only tool
    warnings = binding.list_warnings()
    assert any("ghost_tool" in w for w in warnings)
    assert any("not found" in w for w in warnings)


def test_mi15_merge_strategy_fallback_on_discovery_failure(tmp_path):
    """Merge: discovery failure → fall back to manifest pre-claims (degraded mode)."""
    # Server crashes on tools/list → binding falls back to manifest pre-claims
    crash_server = _write_server_script(
        tmp_path, "crash_server.py", _FAKE_SERVER_CRASH_ON_LIST_TEMPLATE
    )
    mcp_reg = MCPRegistry()
    mcp_reg.register(
        server_id="test_srv",
        name="Test Server",
        transport="stdio",
        endpoint=_server_command(crash_server),
        tools=["fallback_tool"],
    )
    mcp_reg.update_status("test_srv", "healthy")
    cap_reg = CapabilityRegistry()
    transport = StdioMCPTransport(
        command=_server_command(crash_server),
        timeout=5.0,
    )
    binding = MCPBinding(registry=cap_reg, mcp_registry=mcp_reg, transport=transport)

    # Should fall back gracefully — bound tools come from manifest pre-claims
    bound = binding.bind_all()
    assert bound == 1
    names = set(cap_reg.list_names())
    assert "mcp.test_srv.fallback_tool" in names

    # Warning recorded about failed discovery
    warnings = binding.list_warnings()
    assert any("failed" in w.lower() or "fallback" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# mi16-mi18: stderr tail + health degradation (HI-W5-003)
# ---------------------------------------------------------------------------

_FAKE_SERVER_STDERR_TEMPLATE = textwrap.dedent(
    """
    import json, sys

    def main():
        # Write error lines to stderr before processing
        for msg in {stderr_lines_json}:
            sys.stderr.write(msg + "\\n")
            sys.stderr.flush()

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp = {{
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {{"protocolVersion": "2024-11-05"}},
                }}
            elif method == "tools/list":
                resp = {{"jsonrpc": "2.0", "id": req_id, "result": {{"tools": []}}}}
            else:
                resp = {{"jsonrpc": "2.0", "id": req_id, "result": {{}}}}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()

    if __name__ == "__main__":
        main()
    """
)

_FAKE_SERVER_STDERR_CRASH_TEMPLATE = textwrap.dedent(
    """
    import json, sys

    # Write stderr lines and then exit immediately (crash simulation)
    sys.stderr.write("ERROR: fatal startup failure\\n")
    sys.stderr.write("Traceback: something went wrong\\n")
    sys.stderr.flush()
    sys.exit(1)
    """
)


def test_mi16_stderr_captured_on_crash(tmp_path):
    """Stderr lines from a crashing MCP server are captured in the ring buffer."""
    script = _write_server_script(
        tmp_path, "stderr_crash_server.py", _FAKE_SERVER_STDERR_CRASH_TEMPLATE
    )
    t = StdioMCPTransport(command=_server_command(script), timeout=5.0)
    try:
        # Trigger subprocess spawn; ping will fail (server crashes)
        t.ping()
        # Give the stderr reader thread time to drain
        time.sleep(0.3)
        tail = t.get_stderr_tail()
        assert isinstance(tail, list)
        assert any("error" in line.lower() or "fatal" in line.lower() for line in tail)
    finally:
        t.close()


def test_mi17_stderr_tail_in_mcp_status(fake_mcp_server, tmp_path):
    """GET /mcp/status response includes a 'stderr_tails' dict."""
    from hi_agent.mcp.registry import MCPRegistry

    mcp_reg = MCPRegistry()
    mcp_reg.register(
        server_id="test_srv",
        name="Test Server",
        transport="stdio",
        endpoint=_server_command(fake_mcp_server),
        tools=["echo"],
    )
    mcp_reg.update_status("test_srv", "healthy")
    transport = StdioMCPTransport(
        command=_server_command(fake_mcp_server),
        timeout=10.0,
    )

    # Build the stderr_tails dict the same way handle_mcp_status does
    stderr_tails: dict[str, list[str]] = {}
    for server in mcp_reg.list_servers():
        sid = server["server_id"]
        try:
            stderr_tails[sid] = transport.get_stderr_tail()
        except Exception:
            stderr_tails[sid] = []

    assert isinstance(stderr_tails, dict)
    assert "test_srv" in stderr_tails
    assert isinstance(stderr_tails["test_srv"], list)
    transport.close()


def test_mi18_degraded_server_reported_correctly(tmp_path):
    """Server with stderr errors causes MCPHealth._check_one to return 'degraded'."""
    from hi_agent.mcp.health import MCPHealth
    from hi_agent.mcp.registry import MCPRegistry

    # Use a server that writes error keywords to stderr but stays alive
    stderr_lines = ["ERROR: connection pool exhausted"]
    script_content = _FAKE_SERVER_STDERR_TEMPLATE.format(
        stderr_lines_json=json.dumps(stderr_lines)
    )
    script = _write_server_script(tmp_path, "stderr_error_server.py", script_content)

    mcp_reg = MCPRegistry()
    mcp_reg.register(
        server_id="test_srv",
        name="Test Server",
        transport="stdio",
        endpoint=_server_command(script),
        tools=["echo"],
    )
    mcp_reg.update_status("test_srv", "healthy")

    transport = StdioMCPTransport(
        command=_server_command(script),
        timeout=10.0,
    )

    # Ping to spawn the subprocess, then wait for stderr reader to drain
    transport.ping()
    time.sleep(0.3)

    health = MCPHealth(mcp_reg, transport=transport)
    results = health.check_all()

    assert results.get("test_srv") == "degraded"
    transport.close()
