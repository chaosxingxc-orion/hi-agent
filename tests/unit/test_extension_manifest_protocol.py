"""Unit tests for ExtensionManifest Protocol conformance.

Layer 1 — Unit: tests each manifest type implements the protocol and emits
the required dict shape.  No network or external I/O.
"""

from __future__ import annotations

from hi_agent.contracts.extension_manifest import ExtensionManifest
from hi_agent.knowledge.manifest import KnowledgeManifest
from hi_agent.mcp.manifest import McpToolManifest
from hi_agent.plugins.manifest import PluginManifest

_REQUIRED_DICT_KEYS = {"name", "version", "kind"}


def test_plugin_manifest_implements_protocol() -> None:
    """PluginManifest satisfies the ExtensionManifest runtime-checkable Protocol."""
    m = PluginManifest(name="test-plugin", version="2.0")
    assert isinstance(m, ExtensionManifest), (
        "PluginManifest must satisfy ExtensionManifest Protocol"
    )


def test_mcp_manifest_implements_protocol() -> None:
    """McpToolManifest satisfies the ExtensionManifest runtime-checkable Protocol."""
    m = McpToolManifest(name="test-mcp")
    assert isinstance(m, ExtensionManifest), (
        "McpToolManifest must satisfy ExtensionManifest Protocol"
    )


def test_knowledge_manifest_implements_protocol() -> None:
    """KnowledgeManifest satisfies the ExtensionManifest runtime-checkable Protocol."""
    m = KnowledgeManifest(name="test-knowledge")
    assert isinstance(m, ExtensionManifest), (
        "KnowledgeManifest must satisfy ExtensionManifest Protocol"
    )


def test_to_manifest_dict_has_required_keys_plugin() -> None:
    """PluginManifest.to_manifest_dict() returns dict with name, version, kind."""
    m = PluginManifest(name="p1", version="1.2", capabilities=["cap_a"])
    d = m.to_manifest_dict()
    assert d.keys() >= _REQUIRED_DICT_KEYS, f"Missing keys in PluginManifest dict: {d}"
    assert d["name"] == "p1"
    assert d["version"] == "1.2"
    assert d["kind"] == "plugin"


def test_to_manifest_dict_has_required_keys_mcp() -> None:
    """McpToolManifest.to_manifest_dict() returns dict with name, version, kind."""
    m = McpToolManifest(name="mcp1", tools=["tool_a", "tool_b"])
    d = m.to_manifest_dict()
    assert d.keys() >= _REQUIRED_DICT_KEYS, f"Missing keys in McpToolManifest dict: {d}"
    assert d["name"] == "mcp1"
    assert d["kind"] == "mcp_tool"


def test_to_manifest_dict_has_required_keys_knowledge() -> None:
    """KnowledgeManifest.to_manifest_dict() returns dict with name, version, kind."""
    m = KnowledgeManifest(name="kg1", backends=["sqlite"])
    d = m.to_manifest_dict()
    assert d.keys() >= _REQUIRED_DICT_KEYS, f"Missing keys in KnowledgeManifest dict: {d}"
    assert d["name"] == "kg1"
    assert d["kind"] == "knowledge"
