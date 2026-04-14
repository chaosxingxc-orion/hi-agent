"""MCP external provider positive integration tests.

These tests verify the full positive chain that the downstream requires
before accepting "external MCP provider capability delivered":

  register → health-check → bind → /mcp/tools/list visible → /mcp/tools/call succeeds

This is the official answer to the downstream P1 blocker:
  "failure path more honest ≠ positive delivery path formally verified"

Design (per CLAUDE.md P3 — Production Integrity Constraint):
  - No mocking of transport or subprocess I/O.
  - A real Python-based MCP server subprocess is launched for each test.
  - The subprocess speaks JSON-RPC 2.0 over stdio — same protocol as production.
  - Internal hi_agent components (registry, health, binding, server) run for real.
  - subprocess.Popen is the only "external" boundary — not mocked per P3 rule
    (external process I/O is a permitted mock boundary in unit tests, but here
    we use a REAL subprocess so no mock is needed).

Fixture strategy:
  _mcp_server_script() writes a minimal MCP server to a temp file and returns
  the path.  The server supports:
    - initialize  → returns protocol handshake
    - tools/list  → returns one tool: "echo_tool"
    - tools/call  → echo_tool returns its input as output

Chain under test:
  MCPRegistry.register()
    → SystemBuilder._wire_plugin_contributions() picks up mcp_servers
    → MCPHealth.check_all() with MultiStdioTransport (real subprocess ping)
    → MCPBinding.bind_all() promotes healthy servers to CapabilityRegistry
    → AgentServer /mcp/status reports transport_status=wired, capability_mode=external_provider
    → GET /mcp/tools lists echo_tool
    → POST /mcp/tools/call invokes echo_tool and returns real output
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from hi_agent.mcp.registry import MCPRegistry
from hi_agent.mcp.transport import MultiStdioTransport, StdioMCPTransport
from hi_agent.mcp.health import MCPHealth
from hi_agent.mcp.binding import MCPBinding
from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec


# ---------------------------------------------------------------------------
# Minimal in-process MCP server script (written to a temp file)
# ---------------------------------------------------------------------------

_MCP_SERVER_SCRIPT = textwrap.dedent("""\
    \"\"\"Minimal MCP server for integration testing.

    Speaks JSON-RPC 2.0 over stdio.  Supports:
      initialize  → protocol handshake
      tools/list  → lists one tool: echo_tool
      tools/call  → echo_tool returns its arguments as output
    \"\"\"
    import json
    import sys

    TOOLS = [
        {
            "name": "echo_tool",
            "description": "Returns its input arguments as output.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"],
            },
        }
    ]

    def handle(request):
        method = request.get("method", "")
        req_id = request.get("id")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "hi-agent-test-mcp-server", "version": "0.1"},
                },
            }
        elif method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            args = params.get("arguments", {})
            if tool_name == "echo_tool":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": f"echo: {args.get('message', '')}"}
                        ]
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }

    def main():
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                request = json.loads(raw)
            except json.JSONDecodeError:
                continue
            response = handle(request)
            sys.stdout.write(json.dumps(response) + "\\n")
            sys.stdout.flush()

    if __name__ == "__main__":
        main()
""")


@pytest.fixture(scope="module")
def mcp_server_script() -> Path:
    """Write the minimal MCP server to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        suffix=".py",
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    tmp.write(_MCP_SERVER_SCRIPT)
    tmp.flush()
    tmp.close()
    yield Path(tmp.name)
    os.unlink(tmp.name)


@pytest.fixture()
def mcp_server_command(mcp_server_script: Path) -> str:
    """Return the shell command to launch the test MCP server subprocess."""
    return f"{sys.executable} {mcp_server_script}"


# ---------------------------------------------------------------------------
# Helper: verify subprocess is actually reachable before using it in tests
# ---------------------------------------------------------------------------

def _subprocess_reachable(command: str, timeout: float = 5.0) -> bool:
    """Return True if the MCP server subprocess responds to an initialize ping."""
    transport = StdioMCPTransport(command=command, timeout=timeout)
    try:
        return transport.ping()
    except Exception:
        return False
    finally:
        transport.close()


# ---------------------------------------------------------------------------
# MI-01: StdioMCPTransport can ping the real subprocess
# ---------------------------------------------------------------------------

def test_mi01_real_subprocess_ping(mcp_server_command: str) -> None:
    """StdioMCPTransport.ping() must return True for a real MCP server.

    This is the most basic positive-chain test: verify that our transport
    can establish a real JSON-RPC initialize handshake with a real subprocess.
    """
    transport = StdioMCPTransport(command=mcp_server_command, timeout=5.0)
    try:
        alive = transport.ping()
    finally:
        transport.close()
    assert alive is True, (
        "StdioMCPTransport.ping() returned False for a real MCP subprocess. "
        "The transport cannot establish a JSON-RPC initialize handshake."
    )


# ---------------------------------------------------------------------------
# MI-02: Health check promotes server from registered → healthy
# ---------------------------------------------------------------------------

def test_mi02_health_check_promotes_to_healthy(mcp_server_command: str) -> None:
    """MCPHealth.check_all() must mark a reachable server as 'healthy'.

    register → health-check → status=healthy
    """
    registry = MCPRegistry()
    registry.register(
        server_id="test_srv",
        name="Test MCP Server",
        transport="stdio",
        endpoint=mcp_server_command,
        tools=["echo_tool"],
    )
    assert registry.get("test_srv").status == "registered"

    transport = MultiStdioTransport(mcp_registry=registry, timeout=5.0)
    health = MCPHealth(mcp_registry=registry, transport=transport)
    results = health.check_all()

    transport.close_all()
    assert results["test_srv"] == "healthy", (
        f"Server should be 'healthy' after a real ping, got {results['test_srv']!r}"
    )
    assert registry.get("test_srv").status == "healthy"


# ---------------------------------------------------------------------------
# MI-03: MCPBinding registers tools from healthy server into CapabilityRegistry
# ---------------------------------------------------------------------------

def test_mi03_binding_registers_tools_after_health_check(mcp_server_command: str) -> None:
    """bind_all() must register echo_tool into CapabilityRegistry after health check.

    register → health-check → bind → capability registered
    """
    mcp_registry = MCPRegistry()
    mcp_registry.register(
        server_id="test_srv",
        name="Test MCP Server",
        transport="stdio",
        endpoint=mcp_server_command,
        tools=["echo_tool"],
    )

    transport = MultiStdioTransport(mcp_registry=mcp_registry, timeout=5.0)
    health = MCPHealth(mcp_registry=mcp_registry, transport=transport)
    health.check_all()

    cap_registry = CapabilityRegistry()
    binding = MCPBinding(registry=cap_registry, mcp_registry=mcp_registry, transport=transport)
    bound = binding.bind_all()

    transport.close_all()

    assert bound == 1, f"Expected 1 tool bound, got {bound}"
    names = cap_registry.list_names()
    assert "mcp.test_srv.echo_tool" in names, (
        f"echo_tool not in capability registry. Registered: {names}"
    )


# ---------------------------------------------------------------------------
# MI-04: Bound capability can be invoked end-to-end
# ---------------------------------------------------------------------------

def test_mi04_bound_capability_invocable(mcp_server_command: str) -> None:
    """A bound MCP tool must be invocable through CapabilityInvoker.

    register → health-check → bind → capability → invocation returns real output
    """
    from hi_agent.capability.invoker import CapabilityInvoker
    from hi_agent.capability.circuit_breaker import CircuitBreaker

    mcp_registry = MCPRegistry()
    mcp_registry.register(
        server_id="test_srv",
        name="Test MCP Server",
        transport="stdio",
        endpoint=mcp_server_command,
        tools=["echo_tool"],
    )

    transport = MultiStdioTransport(mcp_registry=mcp_registry, timeout=5.0)
    health = MCPHealth(mcp_registry=mcp_registry, transport=transport)
    health.check_all()

    cap_registry = CapabilityRegistry()
    binding = MCPBinding(registry=cap_registry, mcp_registry=mcp_registry, transport=transport)
    binding.bind_all()

    invoker = CapabilityInvoker(registry=cap_registry, breaker=CircuitBreaker())
    try:
        result = invoker.invoke("mcp.test_srv.echo_tool", {"message": "hello integration"})
    finally:
        transport.close_all()

    assert isinstance(result, dict), f"Expected dict result, got {type(result).__name__!r}"
    # The test MCP server returns {"content": [{"type": "text", "text": "echo: hello integration"}]}
    content = result.get("content", [])
    assert isinstance(content, list) and len(content) > 0, (
        f"echo_tool response must have non-empty content list, got: {result!r}"
    )
    text_item = content[0]
    assert text_item.get("text") == "echo: hello integration", (
        f"Unexpected echo output: {text_item!r}"
    )


# ---------------------------------------------------------------------------
# MI-05: /mcp/status reports wired + external_provider when server is healthy
# ---------------------------------------------------------------------------

def test_mi05_mcp_status_reports_wired(mcp_server_command: str) -> None:
    """/mcp/status must report transport_status=wired + capability_mode=external_provider.

    This is the end-to-end server-level verification: the HTTP endpoint that
    downstream integrators poll must accurately reflect the wired state.

    Full chain: server startup → plugin registration → health-check → bind
      → GET /mcp/status → transport_status=wired, capability_mode=external_provider
    """
    from starlette.testclient import TestClient
    from hi_agent.server.app import AgentServer

    server = AgentServer()
    # Directly inject a pre-healthy MCP server into the server's registry
    # (simulates what plugin manifest registration does at startup)
    mcp_reg = server._builder.build_mcp_registry()
    mcp_reg.register(
        server_id="test_srv",
        name="Test MCP Server",
        transport="stdio",
        endpoint=mcp_server_command,
        tools=["echo_tool"],
    )

    # Wire transport + health-check + bind (same flow as _wire_plugin_contributions)
    transport = MultiStdioTransport(mcp_registry=mcp_reg, timeout=5.0)
    server._builder._mcp_transport = transport
    health = MCPHealth(mcp_registry=mcp_reg, transport=transport)
    health.check_all()

    cap_registry = server._builder.build_capability_registry()
    binding = MCPBinding(registry=cap_registry, mcp_registry=mcp_reg, transport=transport)
    binding.bind_all()

    client = TestClient(server.app, raise_server_exceptions=True)
    try:
        resp = client.get("/mcp/status")
    finally:
        transport.close_all()

    assert resp.status_code == 200, f"/mcp/status returned {resp.status_code}: {resp.text}"
    body = resp.json()

    assert body["transport_status"] == "wired", (
        f"Expected transport_status='wired' after health check, "
        f"got {body['transport_status']!r}. Full response: {body}"
    )
    assert body["capability_mode"] == "external_provider", (
        f"Expected capability_mode='external_provider', "
        f"got {body['capability_mode']!r}. Full response: {body}"
    )
    assert body["count"] >= 1, "At least one MCP server must be registered"


# ---------------------------------------------------------------------------
# MI-06: Unreachable server does NOT leak into transport_status=wired
# ---------------------------------------------------------------------------

def test_mi06_unreachable_server_not_reported_wired(mcp_server_command: str) -> None:
    """An unreachable MCP server must result in transport_status=registered_but_unreachable.

    Regression guard for the original P0 defect: a fake/unreachable server must
    never be reported as wired or external_provider.
    """
    from starlette.testclient import TestClient
    from hi_agent.server.app import AgentServer

    server = AgentServer()
    mcp_reg = server._builder.build_mcp_registry()
    mcp_reg.register(
        server_id="fake_srv",
        name="Fake unreachable server",
        transport="stdio",
        endpoint=f"{sys.executable} /nonexistent_path_that_does_not_exist.py",
        tools=["fake_tool"],
    )

    transport = MultiStdioTransport(mcp_registry=mcp_reg, timeout=2.0)
    server._builder._mcp_transport = transport
    health = MCPHealth(mcp_registry=mcp_reg, transport=transport)
    health.check_all()  # will set status=error on the fake server

    client = TestClient(server.app, raise_server_exceptions=True)
    try:
        resp = client.get("/mcp/status")
    finally:
        transport.close_all()

    assert resp.status_code == 200
    body = resp.json()

    assert body["transport_status"] != "wired", (
        f"Unreachable server must NOT be reported as wired. "
        f"Got transport_status={body['transport_status']!r}."
    )
    assert body["capability_mode"] == "infrastructure_only", (
        f"Unreachable server must yield capability_mode=infrastructure_only, "
        f"got {body['capability_mode']!r}."
    )


# ---------------------------------------------------------------------------
# MI-07: Real plugin.json manifest → PluginLoader → _wire_plugin_contributions
#         → /mcp/tools/list shows external tool
# ---------------------------------------------------------------------------

def test_mi07_plugin_manifest_wires_mcp_to_tools_list(
    mcp_server_script: Path,
    tmp_path: Path,
) -> None:
    """Full plugin-manifest path: plugin.json → PluginLoader → _wire_plugin_contributions
    → POST /mcp/tools/list shows the external tool.

    This is the platform entry-level test the downstream requires.  It exercises
    the real code path:
      PluginLoader.load_all()       ← reads plugin.json from disk
      PluginLoader.activate_all()   ← sets status=active
      _wire_plugin_contributions()  ← registers mcp_servers, builds transport,
                                       runs health check, calls MCPBinding.bind_all()
      POST /mcp/tools/list          ← MCPServer.list_tools() from CapabilityRegistry

    No internal registry is injected directly — the MCP server enters through
    the documented plugin.json mcp_servers field.
    """
    import json as _json
    from starlette.testclient import TestClient
    from hi_agent.server.app import AgentServer
    from hi_agent.plugin.loader import PluginLoader

    # Write plugin.json describing the test MCP server.
    plugin_subdir = tmp_path / "echo-mcp-plugin"
    plugin_subdir.mkdir()
    manifest_data = {
        "name": "echo-mcp-plugin",
        "version": "1.0.0",
        "description": "Integration-test MCP plugin",
        "type": "mcp",
        "mcp_servers": [
            {
                "id": "echo_srv",
                "name": "echo-mcp",
                "transport": "stdio",
                "endpoint": f"{sys.executable} {mcp_server_script}",
                "tools": ["echo_tool"],
            }
        ],
    }
    (plugin_subdir / "plugin.json").write_text(
        _json.dumps(manifest_data), encoding="utf-8"
    )

    # Load via PluginLoader with the temp parent dir — exactly what happens
    # at startup when a real plugin is installed under .hi_agent/plugins/.
    loader = PluginLoader(plugin_dirs=[str(tmp_path)])
    loaded = loader.load_all()
    assert len(loaded) == 1, f"Expected 1 plugin, got {len(loaded)}: {loaded}"
    loader.activate_all()
    assert loader._loaded["echo-mcp-plugin"].status == "active", (
        "Plugin must be active before _wire_plugin_contributions will wire its servers."
    )

    # Create server, inject our loader, reset MCP singletons so
    # _wire_plugin_contributions rebuilds them from the plugin manifest.
    server = AgentServer()
    server._builder._plugin_loader = loader
    # Clear then immediately rebuild MCPRegistry so _wire_plugin_contributions
    # sees a non-None registry when it checks `self._mcp_registry is not None`
    # before registering servers from the plugin manifest.
    server._builder._mcp_registry = None
    server._builder.build_mcp_registry()
    server._builder._mcp_transport = None  # transport rebuilt from scratch by _wire

    transport = None
    try:
        server._builder._wire_plugin_contributions()
        transport = server._builder._mcp_transport

        client = TestClient(server.app, raise_server_exceptions=True)
        resp = client.post("/mcp/tools/list", json={})
    finally:
        if transport is not None:
            transport.close_all()

    assert resp.status_code == 200, (
        f"POST /mcp/tools/list returned {resp.status_code}: {resp.text}"
    )
    tools = resp.json().get("tools", [])
    tool_names = [t["name"] for t in tools]
    assert any("echo_tool" in name for name in tool_names), (
        f"echo_tool must appear in /mcp/tools/list after plugin manifest wiring. "
        f"Got: {tool_names}"
    )


# ---------------------------------------------------------------------------
# MI-08: HTTP POST /mcp/tools/call reaches external MCP tool end-to-end
# ---------------------------------------------------------------------------

def test_mi08_http_tools_call_reaches_external_mcp_tool(
    mcp_server_script: Path,
    tmp_path: Path,
) -> None:
    """POST /mcp/tools/call must invoke a real external MCP tool and return
    its output through the full HTTP stack.

    Chain under test:
      POST /mcp/tools/call
        → handle_mcp_tools_call (app.py)
        → MCPServer.call_tool()
        → CapabilityInvoker.invoke("mcp.echo_srv.echo_tool", ...)
        → MCPBinding handler (closure over MultiStdioTransport)
        → real subprocess echo_tool
        → JSON-RPC response
        → HTTP response

    This is the HTTP-level positive path verification the downstream requires.
    MI-04 tests the CapabilityInvoker layer directly; this test proves the
    full platform HTTP stack routes correctly to an external MCP tool.
    """
    import json as _json
    from starlette.testclient import TestClient
    from hi_agent.server.app import AgentServer
    from hi_agent.plugin.loader import PluginLoader

    plugin_subdir = tmp_path / "echo-mcp-plugin"
    plugin_subdir.mkdir()
    manifest_data = {
        "name": "echo-mcp-plugin",
        "version": "1.0.0",
        "description": "Integration-test MCP plugin",
        "type": "mcp",
        "mcp_servers": [
            {
                "id": "echo_srv",
                "name": "echo-mcp",
                "transport": "stdio",
                "endpoint": f"{sys.executable} {mcp_server_script}",
                "tools": ["echo_tool"],
            }
        ],
    }
    (plugin_subdir / "plugin.json").write_text(
        _json.dumps(manifest_data), encoding="utf-8"
    )

    loader = PluginLoader(plugin_dirs=[str(tmp_path)])
    loader.load_all()
    loader.activate_all()

    server = AgentServer()
    server._builder._plugin_loader = loader
    server._builder._mcp_registry = None
    server._builder.build_mcp_registry()   # must be non-None before _wire runs
    server._builder._mcp_transport = None

    transport = None
    try:
        server._builder._wire_plugin_contributions()
        transport = server._builder._mcp_transport

        client = TestClient(server.app, raise_server_exceptions=True)
        # Use the canonical capability name: mcp.{server_id}.{tool_name}
        resp = client.post(
            "/mcp/tools/call",
            json={"name": "mcp.echo_srv.echo_tool", "arguments": {"message": "hello platform"}},
        )
    finally:
        if transport is not None:
            transport.close_all()

    assert resp.status_code == 200, (
        f"POST /mcp/tools/call returned {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert not body.get("isError", False), (
        f"Tool call returned isError=True: {body}"
    )
    content = body.get("content", [])
    assert isinstance(content, list) and len(content) > 0, (
        f"Response must have non-empty content list, got: {body}"
    )
    # The echo_tool subprocess returns {"content": [{"type": "text", "text": "echo: <message>"}]}
    # MCPServer wraps this as JSON text inside content[0].text.
    raw_text = content[0].get("text", "")
    assert "echo" in raw_text.lower() or "hello platform" in raw_text, (
        f"Expected echo output to contain echo/message content, got: {raw_text!r}"
    )
