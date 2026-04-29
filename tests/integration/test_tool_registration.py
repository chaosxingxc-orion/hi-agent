"""Tests that SystemBuilder registers real builtin tools alongside LLM capabilities."""

from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig


def test_builder_invoker_includes_builtin_tools():
    config = TraceConfig()
    builder = SystemBuilder(config=config)
    invoker = builder.build_invoker()
    names = invoker.registry.list_names()
    assert "file_read" in names
    assert "file_write" in names
    assert "web_fetch" in names
    # shell_exec is gated behind HI_AGENT_ENABLE_SHELL_EXEC=true (H-2 security hardening)


def test_builder_invoker_includes_llm_capabilities():
    config = TraceConfig()
    builder = SystemBuilder(config=config)
    invoker = builder.build_invoker()
    names = invoker.registry.list_names()
    assert "analyze_goal" in names
    assert "synthesize" in names


def test_capability_spec_has_description():
    from hi_agent.capability.tools.builtin import _BUILTIN_TOOLS

    for spec in _BUILTIN_TOOLS:
        assert spec.description, f"{spec.name} must have a non-empty description"


def test_capability_spec_has_parameters():
    from hi_agent.capability.tools.builtin import _BUILTIN_TOOLS

    for spec in _BUILTIN_TOOLS:
        assert isinstance(spec.parameters, dict), f"{spec.name} parameters must be a dict"
        assert "properties" in spec.parameters, f"{spec.name} parameters must have 'properties'"


def test_file_read_invokable_via_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
    monkeypatch.chdir(
        tmp_path
    )  # file_read resolves paths relative to cwd (H-6: payload base_dir ignored)
    config = TraceConfig()
    builder = SystemBuilder(config=config)
    invoker = builder.build_invoker()
    f = tmp_path / "test.txt"
    f.write_text("hello")
    result = invoker.invoke("file_read", {"path": "test.txt"})
    assert result["success"] is True
    assert result["content"] == "hello"
