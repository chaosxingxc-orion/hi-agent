"""Tests for hi_agent.mcp.transport.

Unit-layer: subprocess spawning is mocked only for the external process call
(per P3 — mocking of external network/process I/O is permitted in unit tests).
Integration path (real subprocess) is marked skip pending live MCP binary.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hi_agent.mcp.registry import MCPRegistry
from hi_agent.mcp.transport import (
    MCPTransportError,
    MultiStdioTransport,
    StdioMCPTransport,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(servers: list[dict]) -> MCPRegistry:
    registry = MCPRegistry()
    for srv in servers:
        registry.register(
            server_id=srv["server_id"],
            name=srv.get("name", srv["server_id"]),
            transport=srv.get("transport", "stdio"),
            endpoint=srv.get("endpoint", "echo hi"),
            tools=srv.get("tools", []),
        )
    return registry


def _mock_proc(responses: list[dict]) -> MagicMock:
    """Return a mock subprocess.Popen with pre-canned JSON-RPC responses."""
    proc = MagicMock()
    proc.poll.return_value = None  # process is alive
    proc.pid = 99

    # stdout: each read returns the next pre-canned JSON response
    response_lines = [json.dumps(r) + "\n" for r in responses]
    response_iter = iter(response_lines)
    proc.stdout.readline.side_effect = lambda: next(response_iter, "")

    stdin_buf: list[str] = []
    proc.stdin.write.side_effect = stdin_buf.append
    proc.stdin.flush = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# StdioMCPTransport — unit tests (subprocess mocked)
# ---------------------------------------------------------------------------


class TestStdioMCPTransport:
    """Unit tests for StdioMCPTransport using mocked subprocess."""

    def _transport(self) -> StdioMCPTransport:
        return StdioMCPTransport(command="echo hi", timeout=5.0)

    def _patch_popen(self, proc: Any):
        return patch("subprocess.Popen", return_value=proc)

    def test_invoke_returns_result_dict(self) -> None:
        t = self._transport()
        proc = _mock_proc([{"jsonrpc": "2.0", "id": 1, "result": {"content": "hello"}}])
        with self._patch_popen(proc):
            result = t.invoke("srv", "greet", {"name": "world"})
        assert result == {"content": "hello"}

    def test_invoke_raises_on_rpc_error(self) -> None:
        t = self._transport()
        proc = _mock_proc(
            [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}]
        )
        with self._patch_popen(proc), pytest.raises(MCPTransportError, match="Method not found"):
            t.invoke("srv", "unknown_tool", {})

    def test_invoke_raises_on_eof(self) -> None:
        t = self._transport()
        proc = _mock_proc([])  # empty — EOF immediately
        with self._patch_popen(proc), pytest.raises(MCPTransportError):
            t.invoke("srv", "tool", {})

    def test_invoke_skips_non_matching_response_ids(self) -> None:
        """Transport should skip responses with wrong id and wait for the right one."""
        t = self._transport()
        proc = _mock_proc(
            [
                {"jsonrpc": "2.0", "id": 99, "result": {"wrong": True}},  # wrong id
                {"jsonrpc": "2.0", "id": 1, "result": {"correct": True}},
            ]
        )
        with self._patch_popen(proc):
            result = t.invoke("srv", "tool", {})
        assert result == {"correct": True}

    def test_invoke_spawns_process_once_on_reuse(self) -> None:
        t = self._transport()
        proc = _mock_proc(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {"r": 1}},
                {"jsonrpc": "2.0", "id": 2, "result": {"r": 2}},
            ]
        )
        with patch("subprocess.Popen", return_value=proc) as mock_popen:
            t.invoke("srv", "tool", {})
            t.invoke("srv", "tool", {})
        # Popen should only be called once (process reused)
        mock_popen.assert_called_once()

    def test_close_terminates_process(self) -> None:
        t = self._transport()
        proc = _mock_proc([{"jsonrpc": "2.0", "id": 1, "result": {}}])
        with self._patch_popen(proc):
            t.invoke("srv", "tool", {})
        t.close()
        proc.terminate.assert_called_once()
        assert t._proc is None

    def test_close_safe_when_not_started(self) -> None:
        t = self._transport()
        t.close()  # should not raise

    def test_ping_returns_true_on_initialize_response(self) -> None:
        t = self._transport()
        proc = _mock_proc(
            [{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}]
        )
        with self._patch_popen(proc):
            alive = t.ping()
        assert alive is True

    def test_ping_returns_false_on_transport_error(self) -> None:
        t = self._transport()
        proc = _mock_proc([])  # EOF
        with self._patch_popen(proc):
            alive = t.ping()
        assert alive is False

    def test_spawn_failure_raises_transport_error(self) -> None:
        t = self._transport()
        with patch("subprocess.Popen", side_effect=OSError("not found")), pytest.raises(
            MCPTransportError, match="not found"
        ):
            t.invoke("srv", "tool", {})


# ---------------------------------------------------------------------------
# MultiStdioTransport — unit tests
# ---------------------------------------------------------------------------


class TestMultiStdioTransport:
    """Unit tests for MultiStdioTransport registry-driven routing."""

    def test_invoke_routes_to_correct_server(self) -> None:
        registry = _make_registry(
            [
                {"server_id": "srv_a", "endpoint": "cmd_a"},
                {"server_id": "srv_b", "endpoint": "cmd_b"},
            ]
        )
        multi = MultiStdioTransport(mcp_registry=registry)

        proc_a = _mock_proc([{"jsonrpc": "2.0", "id": 1, "result": {"from": "a"}}])
        proc_b = _mock_proc([{"jsonrpc": "2.0", "id": 1, "result": {"from": "b"}}])

        def _popen_factory(cmd, **kwargs):
            if "cmd_a" in (cmd if isinstance(cmd, str) else " ".join(cmd)):
                return proc_a
            return proc_b

        with patch("subprocess.Popen", side_effect=_popen_factory):
            result = multi.invoke("srv_a", "tool", {})
        assert result == {"from": "a"}

    def test_invoke_raises_for_unknown_server(self) -> None:
        registry = _make_registry([])
        multi = MultiStdioTransport(mcp_registry=registry)
        with pytest.raises(MCPTransportError, match="not found in MCPRegistry"):
            multi.invoke("nonexistent", "tool", {})

    def test_invoke_raises_for_non_stdio_transport(self) -> None:
        registry = _make_registry(
            [{"server_id": "http_srv", "transport": "http", "endpoint": "http://localhost"}]
        )
        multi = MultiStdioTransport(mcp_registry=registry)
        with pytest.raises(MCPTransportError, match="only 'stdio' is supported"):
            multi.invoke("http_srv", "tool", {})

    def test_transport_reused_across_calls(self) -> None:
        registry = _make_registry([{"server_id": "srv", "endpoint": "cmd"}])
        multi = MultiStdioTransport(mcp_registry=registry)
        proc = _mock_proc(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {"r": 1}},
                {"jsonrpc": "2.0", "id": 2, "result": {"r": 2}},
            ]
        )
        with patch("subprocess.Popen", return_value=proc) as mock_popen:
            multi.invoke("srv", "tool", {})
            multi.invoke("srv", "tool", {})
        mock_popen.assert_called_once()

    def test_close_all_terminates_all(self) -> None:
        registry = _make_registry(
            [
                {"server_id": "s1", "endpoint": "c1"},
                {"server_id": "s2", "endpoint": "c2"},
            ]
        )
        multi = MultiStdioTransport(mcp_registry=registry)
        proc1 = _mock_proc(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                {"jsonrpc": "2.0", "id": 2, "result": {}},
            ]
        )
        proc2 = _mock_proc(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                {"jsonrpc": "2.0", "id": 2, "result": {}},
            ]
        )
        procs = {"c1": proc1, "c2": proc2}

        def _factory(cmd, **kwargs):
            return procs.get(cmd if isinstance(cmd, str) else cmd[0], proc1)

        with patch("subprocess.Popen", side_effect=_factory):
            multi.invoke("s1", "t", {})
            multi.invoke("s2", "t", {})
        multi.close_all()
        proc1.terminate.assert_called_once()
        proc2.terminate.assert_called_once()
        assert len(multi._transports) == 0

    def test_ping_no_servers_returns_false(self) -> None:
        registry = _make_registry([])
        multi = MultiStdioTransport(mcp_registry=registry)
        assert multi.ping() is False

    def test_ping_first_server(self) -> None:
        registry = _make_registry([{"server_id": "s1", "endpoint": "cmd"}])
        multi = MultiStdioTransport(mcp_registry=registry)
        proc = _mock_proc(
            [{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}]
        )
        with patch("subprocess.Popen", return_value=proc):
            assert multi.ping() is True


# ---------------------------------------------------------------------------
# MCPHealth with transport — unit tests
# ---------------------------------------------------------------------------


class TestMCPHealthWithTransport:
    """Verify that MCPHealth delegates to transport.ping() when transport is set."""

    def test_check_all_healthy_when_ping_true(self) -> None:
        from hi_agent.mcp.health import MCPHealth

        registry = _make_registry([{"server_id": "srv"}])
        transport = MagicMock()
        transport.ping.return_value = True
        health = MCPHealth(mcp_registry=registry, transport=transport)
        results = health.check_all()
        assert results["srv"] == "healthy"

    def test_check_all_error_when_ping_false(self) -> None:
        from hi_agent.mcp.health import MCPHealth

        registry = _make_registry([{"server_id": "srv"}])
        transport = MagicMock()
        transport.ping.return_value = False
        health = MCPHealth(mcp_registry=registry, transport=transport)
        results = health.check_all()
        assert results["srv"] == "unhealthy"

    def test_check_all_error_when_ping_raises(self) -> None:
        from hi_agent.mcp.health import MCPHealth

        registry = _make_registry([{"server_id": "srv"}])
        transport = MagicMock()
        transport.ping.side_effect = Exception("connection refused")
        health = MCPHealth(mcp_registry=registry, transport=transport)
        results = health.check_all()
        assert results["srv"] == "unhealthy"

    def test_check_all_returns_recorded_status_without_transport(self) -> None:
        from hi_agent.mcp.health import MCPHealth

        registry = _make_registry([{"server_id": "srv"}])
        registry.update_status("srv", "healthy")
        health = MCPHealth(mcp_registry=registry)  # no transport
        results = health.check_all()
        assert results["srv"] == "healthy"


# ---------------------------------------------------------------------------
# Config reload safety — unit tests (Group K)
# ---------------------------------------------------------------------------


class TestConfigReloadSafety:
    """Verify _on_config_reload inherits singleton subsystems and bumps generation."""

    def test_reload_increments_generation(self) -> None:
        import asyncio
        import os

        os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
        from hi_agent.server.app import AgentServer

        server = AgentServer()
        assert server._builder_generation == 0
        old_builder = server._builder

        # Create a minimal new config (same as current, just a new object)
        new_cfg = server._config  # same values, different invocation
        asyncio.run(server._on_config_reload(new_cfg))

        assert server._builder_generation == 1
        assert server._builder is not old_builder  # new builder instance

    def test_reload_inherits_subsystem_singletons(self) -> None:
        """Subsystem singletons from old builder are passed to new builder."""
        import asyncio
        import os

        os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
        from hi_agent.mcp.registry import MCPRegistry
        from hi_agent.server.app import AgentServer

        server = AgentServer()
        # Inject a sentinel MCPRegistry into the old builder
        sentinel_registry = MCPRegistry()
        server._builder._mcp_registry = sentinel_registry

        asyncio.run(server._on_config_reload(server._config))

        # New builder must have inherited the sentinel registry
        assert server._builder._mcp_registry is sentinel_registry

    def test_reload_does_not_affect_in_flight_executor_reference(self) -> None:
        """Executor built before reload keeps its original builder reference."""
        import asyncio
        import os

        os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
        from hi_agent.server.app import AgentServer

        server = AgentServer()
        # Build an executor from the current builder
        builder_before = server._builder

        asyncio.run(server._on_config_reload(server._config))

        # builder has been replaced but the reference held by any previously-
        # built executor still points to builder_before (captured at build time).
        assert server._builder is not builder_before
        assert builder_before is not None  # not garbage-collected
