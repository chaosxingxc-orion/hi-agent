"""Security tests for capability governance — H-2 shell_exec env gate."""

from __future__ import annotations

import pytest
from hi_agent.capability.registry import CapabilityRegistry


def test_shell_exec_not_registered_without_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """shell_exec must not be registered in dev profile when env var is absent."""
    monkeypatch.delenv("HI_AGENT_ENABLE_SHELL_EXEC", raising=False)
    from hi_agent.capability.tools.builtin import register_builtin_tools

    registry = CapabilityRegistry()
    register_builtin_tools(registry, profile="dev")
    names = registry.list_names()
    assert "shell_exec" not in names


def test_shell_exec_registered_with_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """shell_exec must be registered in dev profile when HI_AGENT_ENABLE_SHELL_EXEC=true."""
    monkeypatch.setenv("HI_AGENT_ENABLE_SHELL_EXEC", "true")
    from hi_agent.capability.tools.builtin import register_builtin_tools

    registry = CapabilityRegistry()
    register_builtin_tools(registry, profile="dev")
    names = registry.list_names()
    assert "shell_exec" in names


def test_shell_exec_not_registered_in_prod_even_with_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """shell_exec must never be registered in non-dev profiles."""
    monkeypatch.setenv("HI_AGENT_ENABLE_SHELL_EXEC", "true")
    from hi_agent.capability.tools.builtin import register_builtin_tools

    registry = CapabilityRegistry()
    register_builtin_tools(registry, profile="prod-real")
    names = registry.list_names()
    assert "shell_exec" not in names
