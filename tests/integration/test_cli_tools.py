"""Tests for tools CLI subcommand and /tools server endpoints."""


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
        tools.append(
            {
                "name": name,
                "description": getattr(spec, "description", ""),
                "parameters": getattr(spec, "parameters", {}),
            }
        )

    names = [t["name"] for t in tools]
    assert "file_read" in names
    assert "file_write" in names
    assert "web_fetch" in names
    # shell_exec requires HI_AGENT_ENABLE_SHELL_EXEC=true (H-2 security gate)


def test_tools_call_logic_file_read(tmp_path, monkeypatch):
    """Test the /tools/call logic directly."""
    from hi_agent.capability.circuit_breaker import CircuitBreaker
    from hi_agent.capability.invoker import CapabilityInvoker
    from hi_agent.capability.registry import CapabilityRegistry
    from hi_agent.capability.tools.builtin import register_builtin_tools

    monkeypatch.chdir(tmp_path)  # file_read uses cwd; payload base_dir is ignored (H-6)
    registry = CapabilityRegistry()
    register_builtin_tools(registry)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)

    f = tmp_path / "cli_test.txt"
    f.write_text("cli content")

    result = invoker.invoke("file_read", {"path": "cli_test.txt"})
    assert result["success"] is True
    assert result["content"] == "cli content"
