"""Unit tests for GovernedToolExecutor — central governance gate (P0-1b).

All tests use real registry/descriptor objects and only mock CapabilityInvoker
to avoid actual side-effects (file writes, shell execution, etc.).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hi_agent.capability.governance import (
    ApprovalRequiredError,
    CapabilityDisabledError,
    CapabilityNotFoundError,
    CapabilityUnavailableError,
    GovernedToolExecutor,
    PermissionDeniedError,
)
from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry, CapabilitySpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(*specs: CapabilitySpec) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for spec in specs:
        registry.register(spec)
    return registry


def _make_invoker(return_value: dict | None = None) -> MagicMock:
    """Return a mock CapabilityInvoker whose .invoke() returns return_value."""
    invoker = MagicMock()
    invoker.invoke.return_value = return_value or {"ok": True}
    return invoker


def _make_spec(
    name: str,
    *,
    prod_enabled_default: bool = True,
    requires_auth: bool = True,
    requires_approval: bool = False,
    required_env: dict | None = None,
    risk_class: str = "read_only",
) -> CapabilitySpec:
    descriptor = CapabilityDescriptor(
        name=name,
        risk_class=risk_class,  # type: ignore[arg-type]
        prod_enabled_default=prod_enabled_default,
        requires_auth=requires_auth,
        requires_approval=requires_approval,
        required_env=required_env or {},
    )
    return CapabilitySpec(
        name=name,
        handler=lambda payload: {"ok": True},
        descriptor=descriptor,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unknown_capability_raises_not_found():
    """governed_executor.invoke("nonexistent", {}) → CapabilityNotFoundError."""
    registry = _make_registry()
    invoker = _make_invoker()
    executor = GovernedToolExecutor(registry=registry, invoker=invoker)

    with pytest.raises(CapabilityNotFoundError, match="nonexistent"):
        executor.invoke("nonexistent", {})

    invoker.invoke.assert_not_called()


def test_prod_disabled_capability_is_denied():
    """shell_exec with prod_enabled_default=False in prod-real → CapabilityDisabledError."""
    spec = _make_spec("shell_exec", prod_enabled_default=False, risk_class="shell")
    registry = _make_registry(spec)
    invoker = _make_invoker()
    executor = GovernedToolExecutor(
        registry=registry, invoker=invoker, runtime_mode="prod-real"
    )

    with pytest.raises(CapabilityDisabledError, match="shell_exec"):
        executor.invoke("shell_exec", {"cmd": "ls"})

    invoker.invoke.assert_not_called()


def test_approval_required_capability_raises():
    """file_write with requires_approval=True → ApprovalRequiredError."""
    spec = _make_spec("file_write", requires_approval=True, risk_class="filesystem_write")
    registry = _make_registry(spec)
    invoker = _make_invoker()
    executor = GovernedToolExecutor(registry=registry, invoker=invoker)

    with pytest.raises(ApprovalRequiredError) as exc_info:
        executor.invoke("file_write", {"path": "/tmp/x", "content": "hello"})

    assert exc_info.value.capability_name == "file_write"
    invoker.invoke.assert_not_called()


def test_dev_mode_allows_shell_exec():
    """shell_exec with prod_enabled_default=False in dev-smoke mode is allowed.

    Mocking invoker so no real shell command is executed.
    """
    spec = _make_spec("shell_exec", prod_enabled_default=False, risk_class="shell")
    registry = _make_registry(spec)
    invoker = _make_invoker({"output": "hello"})
    executor = GovernedToolExecutor(
        registry=registry, invoker=invoker, runtime_mode="dev-smoke"
    )

    result = executor.invoke("shell_exec", {"cmd": "echo hello"}, principal="dev_user")

    invoker.invoke.assert_called_once_with("shell_exec", {"cmd": "echo hello"})
    assert result == {"output": "hello"}


def test_unauthenticated_denied_in_prod():
    """requires_auth=True capability with anonymous principal in prod-real → PermissionDeniedError."""
    spec = _make_spec("sensitive_op", requires_auth=True)
    registry = _make_registry(spec)
    invoker = _make_invoker()
    executor = GovernedToolExecutor(
        registry=registry, invoker=invoker, runtime_mode="prod-real"
    )

    with pytest.raises(PermissionDeniedError, match="sensitive_op"):
        executor.invoke("sensitive_op", {}, principal="anonymous")

    invoker.invoke.assert_not_called()


def test_allow_decision_calls_invoker():
    """A read_only capability with no restrictions → invoker.invoke is called."""
    spec = _make_spec(
        "read_status",
        requires_auth=False,
        requires_approval=False,
        prod_enabled_default=True,
    )
    registry = _make_registry(spec)
    expected = {"status": "active"}
    invoker = _make_invoker(expected)
    executor = GovernedToolExecutor(
        registry=registry, invoker=invoker, runtime_mode="prod-real"
    )

    result = executor.invoke(
        "read_status", {"run_id": "abc"}, principal="service_account"
    )

    invoker.invoke.assert_called_once_with("read_status", {"run_id": "abc"})
    assert result == expected


def test_missing_env_raises_unavailable(monkeypatch):
    """Capability with required_env when env var is absent → CapabilityUnavailableError."""
    monkeypatch.delenv("MY_SECRET_KEY", raising=False)
    spec = _make_spec("external_api", required_env={"MY_SECRET_KEY": "API key for service"})
    registry = _make_registry(spec)
    invoker = _make_invoker()
    executor = GovernedToolExecutor(registry=registry, invoker=invoker)

    with pytest.raises(CapabilityUnavailableError, match="MY_SECRET_KEY"):
        executor.invoke("external_api", {})

    invoker.invoke.assert_not_called()


def test_audit_store_receives_allow_record():
    """When audit_store is set, an allow decision is recorded."""
    spec = _make_spec("read_status", requires_auth=False)
    registry = _make_registry(spec)
    invoker = _make_invoker({"ok": True})
    audit_store = MagicMock()
    executor = GovernedToolExecutor(
        registry=registry, invoker=invoker, audit_store=audit_store
    )

    executor.invoke("read_status", {})

    audit_store.record_tool_call.assert_called_once()
    call_kwargs = audit_store.record_tool_call.call_args.kwargs
    assert call_kwargs["decision"] == "allow"
    assert call_kwargs["capability_name"] == "read_status"


def test_audit_store_receives_deny_record():
    """When audit_store is set, a deny decision is recorded on prod_disabled."""
    spec = _make_spec("shell_exec", prod_enabled_default=False)
    registry = _make_registry(spec)
    invoker = _make_invoker()
    audit_store = MagicMock()
    executor = GovernedToolExecutor(
        registry=registry, invoker=invoker, runtime_mode="prod-real", audit_store=audit_store
    )

    with pytest.raises(CapabilityDisabledError):
        executor.invoke("shell_exec", {})

    audit_store.record_tool_call.assert_called_once()
    call_kwargs = audit_store.record_tool_call.call_args.kwargs
    assert call_kwargs["decision"] == "deny"
    assert call_kwargs["reason"] == "prod_disabled"


def test_audit_store_failure_does_not_block_execution():
    """Audit store errors must never propagate to callers."""
    spec = _make_spec("read_status", requires_auth=False)
    registry = _make_registry(spec)
    invoker = _make_invoker({"ok": True})
    audit_store = MagicMock()
    audit_store.record_tool_call.side_effect = RuntimeError("audit DB down")
    executor = GovernedToolExecutor(
        registry=registry, invoker=invoker, audit_store=audit_store
    )

    # Should not raise despite audit failure
    result = executor.invoke("read_status", {})
    assert result == {"ok": True}
