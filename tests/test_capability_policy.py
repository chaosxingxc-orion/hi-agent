"""Tests for capability RBAC policy integration."""

import pytest
from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityPolicy,
    CapabilityRegistry,
    CapabilitySpec,
    CircuitBreaker,
)


def test_capability_policy_admin_allowed() -> None:
    """Admin role should be able to invoke an allowed capability."""
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(name="echo", handler=lambda payload: {"echo": payload["x"]})
    )
    breaker = CircuitBreaker()
    policy = CapabilityPolicy({"admin": {"echo"}})
    invoker = CapabilityInvoker(registry, breaker, policy=policy)

    response = invoker.invoke("echo", {"x": 42}, role="admin")

    assert response.get("echo") == 42


def test_capability_policy_viewer_denied() -> None:
    """Viewer role should be denied if capability is not allowed."""
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(name="echo", handler=lambda payload: {"echo": payload["x"]})
    )
    breaker = CircuitBreaker()
    policy = CapabilityPolicy({"admin": {"echo"}})
    invoker = CapabilityInvoker(registry, breaker, policy=policy)

    with pytest.raises(PermissionError):
        invoker.invoke("echo", {"x": 1}, role="viewer")


def test_capability_policy_anonymous_compatible() -> None:
    """Anonymous/None role should keep backward-compatible behavior."""
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(name="echo", handler=lambda payload: {"echo": payload["x"]})
    )
    breaker = CircuitBreaker()
    policy = CapabilityPolicy({"admin": {"echo"}})
    invoker = CapabilityInvoker(registry, breaker, policy=policy)

    response = invoker.invoke("echo", {"x": 7})

    assert response.get("echo") == 7
