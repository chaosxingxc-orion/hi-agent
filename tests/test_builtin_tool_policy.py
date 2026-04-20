"""Unit tests for builtin tool registration policy (TASK-P0-1f).

Verifies that shell_exec is absent in prod-real profile and present in dev
profiles.  All other builtin tools remain registered in all profiles.
"""

from __future__ import annotations

from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.capability.tools.builtin import register_builtin_tools

_OTHER_TOOLS = {"file_read", "file_write", "web_fetch"}


def _build_registry(profile: str) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    register_builtin_tools(registry, profile=profile)
    return registry


class TestShellExecPolicy:
    def test_shell_exec_absent_in_prod_profile(self):
        """shell_exec must not be registered when profile is 'prod-real'."""
        registry = _build_registry("prod-real")
        assert "shell_exec" not in registry.list_names()

    def test_shell_exec_absent_in_local_real_profile(self):
        """shell_exec must not be registered in 'local-real' (non-dev) profile."""
        registry = _build_registry("local-real")
        assert "shell_exec" not in registry.list_names()

    def test_shell_exec_present_in_dev_smoke_profile(self):
        """shell_exec must be registered in 'dev-smoke' profile."""
        registry = _build_registry("dev-smoke")
        assert "shell_exec" in registry.list_names()

    def test_shell_exec_present_in_dev_profile(self):
        """shell_exec must be registered in 'dev' profile."""
        registry = _build_registry("dev")
        assert "shell_exec" in registry.list_names()

    def test_shell_exec_present_with_default_profile(self):
        """Default profile (no arg) is dev-smoke — shell_exec should be present."""
        registry = CapabilityRegistry()
        register_builtin_tools(registry)
        assert "shell_exec" in registry.list_names()


class TestOtherToolsPolicy:
    def test_other_tools_present_in_prod_profile(self):
        """file_read, file_write, web_fetch must all be registered in 'prod-real'."""
        registry = _build_registry("prod-real")
        names = set(registry.list_names())
        for tool in _OTHER_TOOLS:
            assert tool in names, f"{tool!r} missing from prod-real registry"

    def test_other_tools_present_in_dev_profile(self):
        """file_read, file_write, web_fetch must all be registered in 'dev-smoke'."""
        registry = _build_registry("dev-smoke")
        names = set(registry.list_names())
        for tool in _OTHER_TOOLS:
            assert tool in names, f"{tool!r} missing from dev-smoke registry"
