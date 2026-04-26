"""Unit tests for ExtensionRegistry operations.

Layer 1 — Unit: tests register/lookup/filter with real manifest instances.
No network or external I/O.
"""

from __future__ import annotations

from hi_agent.contracts.extension_manifest import ExtensionRegistry
from hi_agent.mcp.manifest import McpToolManifest
from hi_agent.plugins.manifest import PluginManifest


def _make_registry() -> ExtensionRegistry:
    """Return a fresh ExtensionRegistry (not the global singleton)."""
    return ExtensionRegistry()


def test_register_and_lookup() -> None:
    """Registering a manifest by name then looking it up returns the same object."""
    reg = _make_registry()
    m = PluginManifest(name="my-plugin", version="1.0")
    reg.register(m)
    result = reg.lookup("my-plugin")
    assert result is m


def test_lookup_missing_returns_none() -> None:
    """Looking up an unregistered name returns None (no KeyError)."""
    reg = _make_registry()
    assert reg.lookup("nonexistent") is None


def test_list_by_kind() -> None:
    """list_by_kind filters to only manifests with the requested manifest_kind."""
    reg = _make_registry()
    plugin = PluginManifest(name="p1", version="1.0")
    mcp = McpToolManifest(name="m1", tools=["tool_x"])
    reg.register(plugin)
    reg.register(mcp)

    plugins = reg.list_by_kind("plugin")
    assert len(plugins) == 1
    assert plugins[0].name == "p1"

    mcps = reg.list_by_kind("mcp_tool")
    assert len(mcps) == 1
    assert mcps[0].name == "m1"


def test_list_by_kind_empty() -> None:
    """list_by_kind returns empty list when no matching kind is registered."""
    reg = _make_registry()
    reg.register(PluginManifest(name="p1", version="1.0"))
    assert reg.list_by_kind("knowledge") == []


def test_posture_filtering_excludes_unsupported() -> None:
    """Manifest with posture_support['research']=False is excluded from research list."""
    reg = _make_registry()
    dev_only = PluginManifest(
        name="dev-only",
        version="1.0",
        posture_support={"dev": True, "research": False, "prod": False},
    )
    all_postures = PluginManifest(
        name="all-postures",
        version="1.0",
        posture_support={"dev": True, "research": True, "prod": True},
    )
    reg.register(dev_only)
    reg.register(all_postures)

    research_items = reg.list_for_posture("research")
    names = [m.name for m in research_items]
    assert "dev-only" not in names
    assert "all-postures" in names


def test_posture_filtering_dev() -> None:
    """list_for_posture('dev') includes manifests that support dev."""
    reg = _make_registry()
    m = PluginManifest(
        name="p1",
        version="1.0",
        posture_support={"dev": True, "research": False},
    )
    reg.register(m)
    assert len(reg.list_for_posture("dev")) == 1
    assert len(reg.list_for_posture("research")) == 0


def test_list_all_returns_all_registered() -> None:
    """list_all returns every registered manifest regardless of kind or posture."""
    reg = _make_registry()
    reg.register(PluginManifest(name="a", version="1.0"))
    reg.register(McpToolManifest(name="b"))
    all_items = reg.list_all()
    assert len(all_items) == 2
