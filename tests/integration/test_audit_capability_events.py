"""Tests for audit event helpers (HI-W10-005)."""

import json
from pathlib import Path


def _read_events(audit_dir: Path) -> list[dict]:
    path = audit_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_emit_capability_invoke_writes_event(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit_capability_invoke

    emit_capability_invoke("my_cap", role="approver", duration_ms=42)
    events = _read_events(tmp_path / ".hi_agent" / "audit")
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "capability.invoke"
    assert e["capability_name"] == "my_cap"
    assert e["role"] == "approver"
    assert e["duration_ms"] == 42
    assert e["output_truncated"] is False


def test_emit_capability_deny_writes_event(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit_capability_deny

    emit_capability_deny("danger_op", role="submitter", reason="missing_role")
    events = _read_events(tmp_path / ".hi_agent" / "audit")
    e = events[0]
    assert e["event"] == "capability.deny"
    assert e["reason"] == "missing_role"


def test_emit_mcp_tools_call_writes_event(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit_mcp_tools_call

    emit_mcp_tools_call("srv1", "read_file", duration_ms=15)
    events = _read_events(tmp_path / ".hi_agent" / "audit")
    e = events[0]
    assert e["event"] == "mcp.tools_call"
    assert e["server_id"] == "srv1"
    assert e["tool_name"] == "read_file"
    assert e["error"] is None


def test_emit_mcp_server_restart_writes_event(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit_mcp_server_restart

    emit_mcp_server_restart("srv1", attempt=2, success=False, error="OSError: ENOENT")
    events = _read_events(tmp_path / ".hi_agent" / "audit")
    e = events[0]
    assert e["event"] == "mcp.server_restart"
    assert e["attempt"] == 2
    assert e["success"] is False
    assert "ENOENT" in e["error"]
