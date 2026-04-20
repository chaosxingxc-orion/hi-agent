"""Tests for MCP server — real tool execution, no mocks.

P3: tests must reflect real path, not mock shortcuts.
"""
import json
import os
import sys

import pytest

os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

from hi_agent.capability.circuit_breaker import CircuitBreaker
from hi_agent.capability.invoker import CapabilityInvoker
from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.capability.tools.builtin import register_builtin_tools
from hi_agent.server.mcp import MCPServer


@pytest.fixture
def mcp():
    registry = CapabilityRegistry()
    register_builtin_tools(registry)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)
    return MCPServer(registry=registry, invoker=invoker)


def test_list_tools_returns_four_builtins(mcp):
    result = mcp.list_tools()
    assert "tools" in result
    names = [t["name"] for t in result["tools"]]
    assert "file_read" in names
    assert "file_write" in names
    assert "web_fetch" in names
    # shell_exec requires HI_AGENT_ENABLE_SHELL_EXEC=true (H-2 security gate)


def test_list_tools_have_input_schema(mcp):
    result = mcp.list_tools()
    for tool in result["tools"]:
        assert "inputSchema" in tool
        assert isinstance(tool["inputSchema"], dict)


def test_call_tool_file_read_real_io(mcp, tmp_path, monkeypatch):
    """Real file I/O — no mock."""
    monkeypatch.chdir(tmp_path)  # file_read uses cwd; payload base_dir is ignored (H-6)
    f = tmp_path / "mcp_test.txt"
    f.write_text("mcp content")
    result = mcp.call_tool("file_read", {"path": "mcp_test.txt"})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["content"] == "mcp content"


def test_call_tool_unknown_returns_error(mcp):
    result = mcp.call_tool("nonexistent_tool", {})
    assert result["isError"] is True


def test_call_tool_shell_exec_real(tmp_path, monkeypatch):
    """shell_exec is available when HI_AGENT_ENABLE_SHELL_EXEC=true (H-2 security gate)."""
    monkeypatch.setenv("HI_AGENT_ENABLE_SHELL_EXEC", "true")
    registry = CapabilityRegistry()
    register_builtin_tools(registry)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)
    mcp_with_shell = MCPServer(registry=registry, invoker=invoker)
    result = mcp_with_shell.call_tool(
        "shell_exec",
        {"command": [sys.executable, "-c", "print('mcp_test')"]},
    )
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert "mcp_test" in data["stdout"]
