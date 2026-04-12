"""Tests for MCP server — real tool execution, no mocks.

P3: tests must reflect real path, not mock shortcuts.
"""
import json
import os
import pytest

os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

from hi_agent.server.mcp import MCPServer
from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.capability.tools.builtin import register_builtin_tools
from hi_agent.capability.invoker import CapabilityInvoker
from hi_agent.capability.circuit_breaker import CircuitBreaker


@pytest.fixture
def mcp():
    registry = CapabilityRegistry()
    register_builtin_tools(registry)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker())
    return MCPServer(registry=registry, invoker=invoker)


def test_list_tools_returns_four_builtins(mcp):
    result = mcp.list_tools()
    assert "tools" in result
    names = [t["name"] for t in result["tools"]]
    assert "file_read" in names
    assert "file_write" in names
    assert "web_fetch" in names
    assert "shell_exec" in names


def test_list_tools_have_input_schema(mcp):
    result = mcp.list_tools()
    for tool in result["tools"]:
        assert "inputSchema" in tool
        assert isinstance(tool["inputSchema"], dict)


def test_call_tool_file_read_real_io(mcp, tmp_path):
    """Real file I/O — no mock."""
    f = tmp_path / "mcp_test.txt"
    f.write_text("mcp content")
    result = mcp.call_tool("file_read", {"path": str(f)})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["content"] == "mcp content"


def test_call_tool_unknown_returns_error(mcp):
    result = mcp.call_tool("nonexistent_tool", {})
    assert result["isError"] is True


def test_call_tool_shell_exec_real(mcp):
    result = mcp.call_tool("shell_exec", {"command": "echo mcp_test"})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert "mcp_test" in data["stdout"]
