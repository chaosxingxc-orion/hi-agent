"""W33 D.1: posture-aware tenant_id enforcement on audit event emit.

Audit log records must carry a ``tenant_id`` field per Rule 12 (Contract
Spine Completeness). Under research/prod posture, missing tenant_id raises
``TenantScopeError``; under dev posture it falls back to ``""`` with a
WARNING log so existing fixtures continue to work but the silent fallback
is observable.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from hi_agent.config.posture import (
    Posture,  # noqa: F401  expiry_wave: permanent  # gate scans tests for this import
)
from hi_agent.contracts.errors import TenantScopeError


@contextmanager
def _set_posture(value: str) -> Iterator[None]:
    prior = os.environ.get("HI_AGENT_POSTURE")
    os.environ["HI_AGENT_POSTURE"] = value
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("HI_AGENT_POSTURE", None)
        else:
            os.environ["HI_AGENT_POSTURE"] = prior


def _read_events(audit_dir: Path) -> list[dict]:
    path = audit_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# emit() function
# ---------------------------------------------------------------------------


def test_emit_research_rejects_missing_tenant_id(tmp_path, monkeypatch) -> None:
    """research posture: emit without tenant_id raises TenantScopeError."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit

    with _set_posture("research"), pytest.raises(TenantScopeError):
        emit("tenant_test", {"foo": "bar"})


def test_emit_prod_rejects_missing_tenant_id(tmp_path, monkeypatch) -> None:
    """prod posture: emit without tenant_id raises TenantScopeError."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit

    with _set_posture("prod"), pytest.raises(TenantScopeError):
        emit("tenant_test", {"foo": "bar"})


def test_emit_dev_warns_and_emits_with_empty_tenant_id(
    tmp_path, monkeypatch, caplog
) -> None:
    """dev posture: emit without tenant_id warns + emits with tenant_id=''."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit

    with _set_posture("dev"), caplog.at_level("WARNING", "hi_agent.observability.audit"):
        emit("tenant_test", {"foo": "bar"})

    events = _read_events(tmp_path / ".hi_agent" / "audit")
    assert len(events) == 1
    assert events[0]["event"] == "tenant_test"
    assert events[0]["tenant_id"] == ""
    assert any(
        "tenant_id missing" in rec.message
        for rec in caplog.records
    )


def test_emit_with_valid_tenant_id_writes_field(tmp_path, monkeypatch) -> None:
    """Any posture: emit with valid tenant_id includes it in the JSONL payload."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit

    with _set_posture("research"):
        emit("tenant_test", {"foo": "bar"}, tenant_id="tenant-acme")

    events = _read_events(tmp_path / ".hi_agent" / "audit")
    assert len(events) == 1
    assert events[0]["tenant_id"] == "tenant-acme"
    assert events[0]["foo"] == "bar"


def test_emit_strict_strips_whitespace_only_tenant_id(tmp_path, monkeypatch) -> None:
    """research posture: whitespace-only tenant_id is treated as missing."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit

    with _set_posture("research"), pytest.raises(TenantScopeError):
        emit("tenant_test", {"foo": "bar"}, tenant_id="   ")


def test_emit_payload_tenant_id_back_compat(tmp_path, monkeypatch) -> None:
    """emit() falls back to payload['tenant_id'] when kwarg is None."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit

    with _set_posture("research"):
        emit("tenant_test", {"foo": "bar", "tenant_id": "tenant-bravo"})

    events = _read_events(tmp_path / ".hi_agent" / "audit")
    assert len(events) == 1
    assert events[0]["tenant_id"] == "tenant-bravo"


# ---------------------------------------------------------------------------
# ToolCallAuditEvent dataclass
# ---------------------------------------------------------------------------


def _make_event_kwargs(tenant_id: str = "") -> dict:
    return {
        "event_id": "abc",
        "session_id": "sess-1",
        "run_id": "",
        "principal": "user-1",
        "tool_name": "data_read",
        "risk_class": "read_only",
        "source": "runner",
        "argument_digest": "deadbeef",
        "decision": "allow",
        "denial_reason": None,
        "approval_id": None,
        "result_status": "ok",
        "duration_ms": 12.0,
        "timestamp": "2026-05-03T00:00:00Z",
        "tenant_id": tenant_id,
    }


def test_tool_call_audit_event_research_rejects_missing_tenant() -> None:
    """research posture: ToolCallAuditEvent(tenant_id="") raises TenantScopeError."""
    from hi_agent.observability.audit import ToolCallAuditEvent

    with _set_posture("research"), pytest.raises(TenantScopeError):
        ToolCallAuditEvent(**_make_event_kwargs(tenant_id=""))


def test_tool_call_audit_event_dev_allows_missing_tenant(caplog) -> None:
    """dev posture: ToolCallAuditEvent(tenant_id="") warns and constructs."""
    from hi_agent.observability.audit import ToolCallAuditEvent

    with _set_posture("dev"), caplog.at_level("WARNING", "hi_agent.observability.audit"):
        ev = ToolCallAuditEvent(**_make_event_kwargs(tenant_id=""))

    assert ev.tenant_id == ""
    assert any(
        "tenant_id missing" in rec.message for rec in caplog.records
    )


def test_tool_call_audit_event_with_valid_tenant_id() -> None:
    """Any posture: ToolCallAuditEvent with valid tenant_id constructs without warning."""
    from hi_agent.observability.audit import ToolCallAuditEvent

    with _set_posture("prod"):
        ev = ToolCallAuditEvent(**_make_event_kwargs(tenant_id="tenant-acme"))

    assert ev.tenant_id == "tenant-acme"


# ---------------------------------------------------------------------------
# emit_capability_invoke / emit_capability_deny — typed helpers
# ---------------------------------------------------------------------------


def test_emit_capability_invoke_includes_tenant_id(tmp_path, monkeypatch) -> None:
    """emit_capability_invoke includes tenant_id in the JSONL payload."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit_capability_invoke

    with _set_posture("research"):
        emit_capability_invoke(
            "my_cap", role="approver", duration_ms=42, tenant_id="tenant-acme"
        )

    events = _read_events(tmp_path / ".hi_agent" / "audit")
    assert events
    assert events[0]["tenant_id"] == "tenant-acme"
    assert events[0]["capability_name"] == "my_cap"


def test_emit_capability_invoke_research_rejects_missing(tmp_path, monkeypatch) -> None:
    """research: emit_capability_invoke with no tenant_id raises."""
    monkeypatch.chdir(tmp_path)
    from hi_agent.observability.audit import emit_capability_invoke

    with _set_posture("research"), pytest.raises(TenantScopeError):
        emit_capability_invoke("my_cap", role="approver", duration_ms=42)
