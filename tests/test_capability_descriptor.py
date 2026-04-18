"""Tests for CapabilityDescriptor risk metadata on builtin tools."""
from __future__ import annotations

import pytest

from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry
from hi_agent.capability.tools.builtin import register_builtin_tools


@pytest.fixture()
def registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    register_builtin_tools(reg)
    return reg


def test_builtin_file_read_descriptor(registry: CapabilityRegistry) -> None:
    desc = registry.get_descriptor("file_read")
    assert desc is not None
    assert desc.risk_class == "filesystem_read"
    assert desc.prod_enabled_default is True
    assert desc.requires_approval is False


def test_builtin_shell_exec_descriptor(registry: CapabilityRegistry) -> None:
    desc = registry.get_descriptor("shell_exec")
    assert desc is not None
    assert desc.risk_class == "shell"
    assert desc.prod_enabled_default is False
    assert desc.requires_approval is True


def test_descriptor_accessible_via_registry(registry: CapabilityRegistry) -> None:
    desc = registry.get_descriptor("file_read")
    assert isinstance(desc, CapabilityDescriptor)
    assert desc.name == "file_read"


def test_missing_descriptor_returns_none(registry: CapabilityRegistry) -> None:
    assert registry.get_descriptor("nonexistent") is None
