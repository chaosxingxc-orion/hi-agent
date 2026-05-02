"""Integration tests for dangerous capability governance."""

import pytest
from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityRegistry,
    CapabilitySpec,
    CircuitBreaker,
)
from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor
from hi_agent.runtime.harness.contracts import EffectClass
from hi_agent.runtime.harness.governance import GovernanceEngine


def _invoker_with_capability(
    capability_name: str,
    effect_class: str | EffectClass,
) -> CapabilityInvoker:
    registry = CapabilityRegistry()
    spec = CapabilitySpec(
        name=capability_name,
        handler=lambda payload: {"ok": True, "payload": payload},
    )
    descriptor = CapabilityDescriptor(
        name=capability_name,
        effect_class=effect_class,
    )
    object.__setattr__(spec, "descriptor", descriptor)
    registry.register(spec)
    return CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)


def test_dangerous_capability_blocked_for_submitter() -> None:
    invoker = _invoker_with_capability("wipe_workspace", EffectClass.DANGEROUS)

    with pytest.raises(PermissionError, match="dangerous"):
        invoker.invoke("wipe_workspace", {}, role="submitter")


def test_dangerous_capability_allowed_for_approver() -> None:
    invoker = _invoker_with_capability("wipe_workspace", EffectClass.DANGEROUS)

    result = invoker.invoke("wipe_workspace", {"target": "tmp"}, role="approver")

    assert result["ok"] is True


def test_dangerous_capability_allowed_for_admin() -> None:
    invoker = _invoker_with_capability("wipe_workspace", EffectClass.DANGEROUS)

    result = invoker.invoke("wipe_workspace", {"target": "tmp"}, role="admin")

    assert result["ok"] is True


def test_normal_capability_not_affected() -> None:
    invoker = _invoker_with_capability("read_status", EffectClass.READ_ONLY)

    result = invoker.invoke("read_status", {}, role="submitter")

    assert result["ok"] is True


def test_governance_dangerous_pattern_detection() -> None:
    engine = GovernanceEngine()

    assert engine.check_dangerous_command("rm -rf /tmp/data")
    assert engine.check_dangerous_command("echo hello world") == []
