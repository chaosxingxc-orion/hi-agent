"""Contract tests for ToolCallAuditEvent shape and GovernedToolExecutor audit writes (P1-2d)."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

from hi_agent.capability.governance import GovernedToolExecutor
from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry, CapabilitySpec
from hi_agent.observability.audit import ToolCallAuditEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_with_capability(
    name: str,
    *,
    prod_enabled_default: bool = True,
    requires_approval: bool = False,
    risk_class: str = "read_only",
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    descriptor = CapabilityDescriptor(
        name=name,
        risk_class=risk_class,
        prod_enabled_default=prod_enabled_default,
        requires_approval=requires_approval,
    )
    spec = CapabilitySpec(
        name=name,
        handler=lambda args: {"result": "ok"},
        descriptor=descriptor,
    )
    registry.register(spec)
    return registry


def _make_invoker(return_value: dict | None = None) -> MagicMock:
    invoker = MagicMock()
    invoker.invoke.return_value = return_value or {"result": "ok"}
    return invoker


# ---------------------------------------------------------------------------
# ToolCallAuditEvent shape
# ---------------------------------------------------------------------------


def test_tool_call_audit_event_has_required_fields():
    """ToolCallAuditEvent can be constructed with all required fields."""
    event = ToolCallAuditEvent(
        event_id="abc123",
        session_id="sess-1",
        run_id="run-1",
        principal="user-1",
        tool_name="file_read",
        risk_class="filesystem_read",
        source="http_tools",
        argument_digest="a1b2c3d4",
        decision="allow",
        denial_reason=None,
        approval_id=None,
        result_status="ok",
        duration_ms=15.2,
        timestamp="2026-04-18T00:00:00Z",
    )
    assert event.event_id == "abc123"
    assert event.tool_name == "file_read"
    assert event.decision == "allow"
    assert event.risk_class == "filesystem_read"
    assert event.result_status == "ok"
    assert event.duration_ms == 15.2
    assert event.denial_reason is None


def test_tool_call_audit_event_deny_shape():
    """ToolCallAuditEvent represents a deny decision correctly."""
    event = ToolCallAuditEvent(
        event_id="xyz789",
        session_id="sess-2",
        run_id="",
        principal="anonymous",
        tool_name="shell_exec",
        risk_class="shell",
        source="runner",
        argument_digest="deadbeef",
        decision="deny",
        denial_reason="prod_disabled",
        approval_id=None,
        result_status=None,
        duration_ms=None,
        timestamp="2026-04-18T01:00:00Z",
    )
    assert event.decision == "deny"
    assert event.denial_reason == "prod_disabled"
    assert event.result_status is None


# ---------------------------------------------------------------------------
# GovernedToolExecutor audit on deny
# ---------------------------------------------------------------------------


def test_governed_executor_writes_audit_on_deny():
    """Audit store receives decision='deny' when capability is prod-disabled."""
    name = "shell_exec"
    registry = _make_registry_with_capability(name, prod_enabled_default=False)
    invoker = _make_invoker()
    audit_store = MagicMock()

    executor = GovernedToolExecutor(
        registry=registry,
        invoker=invoker,
        runtime_mode="prod-real",
        audit_store=audit_store,
    )

    with contextlib.suppress(Exception):
        executor.invoke(name, {}, principal="user-1", session_id="sess-x", source="runner")

    audit_store.record_tool_call.assert_called()
    call_kwargs = audit_store.record_tool_call.call_args.kwargs
    assert call_kwargs["decision"] == "deny"
    assert call_kwargs["capability_name"] == name


# ---------------------------------------------------------------------------
# GovernedToolExecutor audit on allow
# ---------------------------------------------------------------------------


def test_governed_executor_writes_audit_on_allow():
    """Audit store receives decision='allow' for an allowed capability."""
    name = "data_read"
    registry = _make_registry_with_capability(name)
    invoker = _make_invoker()
    audit_store = MagicMock()

    executor = GovernedToolExecutor(
        registry=registry,
        invoker=invoker,
        runtime_mode="dev-smoke",
        audit_store=audit_store,
    )

    executor.invoke(name, {}, principal="user-1", session_id="sess-y", source="http_tools")

    assert audit_store.record_tool_call.call_count >= 1
    # At least one call must be decision=allow
    allow_calls = [
        c
        for c in audit_store.record_tool_call.call_args_list
        if c.kwargs.get("decision") == "allow"
    ]
    assert allow_calls, "Expected at least one 'allow' audit call"


# ---------------------------------------------------------------------------
# GovernedToolExecutor includes risk_class
# ---------------------------------------------------------------------------


def test_governed_executor_includes_risk_class():
    """risk_class from descriptor is passed to audit store."""
    name = "file_reader"
    registry = _make_registry_with_capability(name, risk_class="filesystem_read")
    invoker = _make_invoker()
    audit_store = MagicMock()

    executor = GovernedToolExecutor(
        registry=registry,
        invoker=invoker,
        runtime_mode="dev-smoke",
        audit_store=audit_store,
    )

    executor.invoke(name, {}, principal="user-1", session_id="sess-z", source="runner")

    audit_store.record_tool_call.assert_called()
    call_kwargs = audit_store.record_tool_call.call_args.kwargs
    assert call_kwargs.get("risk_class") == "filesystem_read"


# ---------------------------------------------------------------------------
# GovernedToolExecutor result tracking
# ---------------------------------------------------------------------------


def test_governed_executor_writes_result_status_ok():
    """Post-execution audit call includes result_status='ok' on success."""
    name = "data_read"
    registry = _make_registry_with_capability(name)
    invoker = _make_invoker({"data": "value"})
    audit_store = MagicMock()

    executor = GovernedToolExecutor(
        registry=registry,
        invoker=invoker,
        runtime_mode="dev-smoke",
        audit_store=audit_store,
    )

    executor.invoke(name, {}, principal="user-1", session_id="sess-r", source="runner")

    ok_calls = [
        c
        for c in audit_store.record_tool_call.call_args_list
        if c.kwargs.get("result_status") == "ok"
    ]
    assert ok_calls, "Expected a post-execution audit call with result_status='ok'"
    assert ok_calls[0].kwargs.get("duration_ms") is not None


def test_governed_executor_writes_result_status_error():
    """Post-execution audit call includes result_status='error' on exception."""
    name = "data_read"
    registry = _make_registry_with_capability(name)
    invoker = MagicMock()
    invoker.invoke.side_effect = RuntimeError("boom")
    audit_store = MagicMock()

    executor = GovernedToolExecutor(
        registry=registry,
        invoker=invoker,
        runtime_mode="dev-smoke",
        audit_store=audit_store,
    )

    with contextlib.suppress(RuntimeError):
        executor.invoke(name, {}, principal="user-1", session_id="sess-e", source="runner")

    error_calls = [
        c
        for c in audit_store.record_tool_call.call_args_list
        if c.kwargs.get("result_status") == "error"
    ]
    assert error_calls, "Expected a post-execution audit call with result_status='error'"


# ---------------------------------------------------------------------------
# Argument redaction
# ---------------------------------------------------------------------------


def test_argument_digest_redacts_sensitive_fields():
    """Sensitive arg fields ('password', 'secret', 'token', 'key') are redacted before hashing."""
    import hashlib
    import json

    name = "data_read"
    registry = _make_registry_with_capability(name)
    invoker = _make_invoker()
    audit_store = MagicMock()

    executor = GovernedToolExecutor(
        registry=registry,
        invoker=invoker,
        runtime_mode="dev-smoke",
        audit_store=audit_store,
    )

    sensitive_args = {"query": "select *", "token": "super-secret", "password": "abc123"}
    executor.invoke(name, sensitive_args, principal="user-1", session_id="sess-s", source="runner")

    # Compute expected digest using redacted args
    redacted = {"query": "select *", "token": "[REDACTED]", "password": "[REDACTED]"}
    expected_digest = hashlib.sha256(
        json.dumps(redacted, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]

    allow_calls = [
        c
        for c in audit_store.record_tool_call.call_args_list
        if c.kwargs.get("decision") == "allow"
    ]
    assert allow_calls
    assert allow_calls[0].kwargs["argument_digest"] == expected_digest
