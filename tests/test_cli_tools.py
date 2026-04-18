"""Tests for tools CLI subcommand and /tools server endpoints."""
import os
import json
import pytest

os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")


def test_cli_tools_parser_exists():
    """Parser must have 'tools' subcommand."""
    from hi_agent.cli import build_parser
    parser = build_parser()
    # Parse 'tools list' — should not raise
    args = parser.parse_args(["tools", "list"])
    assert args.command == "tools"
    assert args.tools_action == "list"


def test_cli_tools_call_parser():
    from hi_agent.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["tools", "call", "--name", "file_read", "--args", '{"path": "x"}'])
    assert args.tools_action == "call"
    assert args.name == "file_read"


def test_tools_endpoint_list_logic():
    """Test the /tools endpoint response format directly (no HTTP server needed)."""
    from hi_agent.capability.registry import CapabilityRegistry
    from hi_agent.capability.tools.builtin import register_builtin_tools

    registry = CapabilityRegistry()
    register_builtin_tools(registry)

    # Simulate the /tools endpoint logic
    tools = []
    for name in registry.list_names():
        spec = registry.get(name)
        tools.append({
            "name": name,
            "description": getattr(spec, "description", ""),
            "parameters": getattr(spec, "parameters", {}),
        })

    names = [t["name"] for t in tools]
    assert "file_read" in names
    assert "file_write" in names
    assert "web_fetch" in names
    assert "shell_exec" in names


def test_tools_call_logic_file_read(tmp_path):
    """Test the /tools/call logic directly."""
    from hi_agent.capability.registry import CapabilityRegistry
    from hi_agent.capability.tools.builtin import register_builtin_tools
    from hi_agent.capability.invoker import CapabilityInvoker
    from hi_agent.capability.circuit_breaker import CircuitBreaker

    registry = CapabilityRegistry()
    register_builtin_tools(registry)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker())

    f = tmp_path / "cli_test.txt"
    f.write_text("cli content")

    result = invoker.invoke("file_read", {"path": "cli_test.txt", "base_dir": str(tmp_path)})
    assert result["success"] is True
    assert result["content"] == "cli content"
