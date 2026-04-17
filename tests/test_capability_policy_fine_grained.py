"""Tests for fine-grained action-level capability policy."""

import pytest
from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityPolicy,
    CapabilityRegistry,
    CapabilitySpec,
    CircuitBreaker,
)


def _build_invoker(policy: CapabilityPolicy) -> CapabilityInvoker:
    registry = CapabilityRegistry()
    registry.register(CapabilitySpec(name="echo", handler=lambda payload: {"echo": payload["x"]}))
    return CapabilityInvoker(registry, CircuitBreaker(), policy=policy)


def test_invoke_denied_when_capability_allowed_but_action_not_allowed() -> None:
    """Action policy should deny even when capability-level permission exists."""
    policy = CapabilityPolicy({"operator": {"echo"}})
    invoker = _build_invoker(policy)

    with pytest.raises(PermissionError):
        invoker.invoke(
            "echo",
            {"x": 1},
            role="operator",
            metadata={"stage_id": "draft", "action_kind": "approve"},
        )


def test_invoke_allowed_when_action_permission_granted() -> None:
    """Action-level permission should be sufficient when metadata is provided."""
    policy = CapabilityPolicy()
    policy.allow_action("operator", "draft", "approve")
    invoker = _build_invoker(policy)

    response = invoker.invoke(
        "echo",
        {"x": 2},
        role="operator",
        metadata={"stage_id": "draft", "action_kind": "approve"},
    )

    assert response.get("echo") == 2


def test_invoke_without_metadata_uses_legacy_capability_policy() -> None:
    """Legacy capability policy path should remain unchanged without metadata."""
    policy = CapabilityPolicy({"operator": {"echo"}})
    invoker = _build_invoker(policy)

    response = invoker.invoke("echo", {"x": 3}, role="operator")

    assert response.get("echo") == 3
