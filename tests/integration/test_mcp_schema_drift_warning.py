"""Tests for MCP schema version registry (HI-W10-005)."""
import logging

import pytest
from hi_agent.mcp.schema_registry import MCPSchemaRegistry


@pytest.fixture
def registry():
    return MCPSchemaRegistry()


def test_first_record_returns_no_drift(registry):
    tools = [{"name": "read_file", "description": "reads a file"}]
    assert registry.record("srv1", tools) is False


def test_same_tools_returns_no_drift(registry):
    tools = [{"name": "read_file"}]
    registry.record("srv1", tools)
    assert registry.record("srv1", tools) is False


def test_added_tool_triggers_drift(registry):
    registry.record("srv1", [{"name": "read_file"}])
    drifted = registry.record("srv1", [{"name": "read_file"}, {"name": "write_file"}])
    assert drifted is True


def test_removed_tool_triggers_drift(registry):
    registry.record("srv1", [{"name": "a"}, {"name": "b"}])
    drifted = registry.record("srv1", [{"name": "a"}])
    assert drifted is True


def test_drift_emits_warning_log(registry, caplog):
    registry.record("srv1", [{"name": "a"}])
    with caplog.at_level(logging.WARNING, logger="hi_agent.mcp.schema_registry"):
        registry.record("srv1", [{"name": "b"}])
    assert any("schema drift" in r.message for r in caplog.records)


def test_get_fingerprint_none_before_record(registry):
    assert registry.get_fingerprint("unknown") is None


def test_get_tools_returns_snapshot(registry):
    tools = [{"name": "t1"}, {"name": "t2"}]
    registry.record("srv1", tools)
    result = registry.get_tools("srv1")
    assert sorted(t["name"] for t in result) == ["t1", "t2"]


def test_order_independent_fingerprint(registry):
    """Tool list ordering must not affect fingerprint."""
    tools_a = [{"name": "a"}, {"name": "b"}]
    tools_b = [{"name": "b"}, {"name": "a"}]
    registry.record("srv1", tools_a)
    # Reversed order → same fingerprint → no drift
    assert registry.record("srv1", tools_b) is False
