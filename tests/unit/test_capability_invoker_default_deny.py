"""Unit tests for CapabilityInvoker default-deny when no policy is set (H-3)."""
from __future__ import annotations

import pytest

from hi_agent.capability.invoker import CapabilityInvoker
from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec


def _make_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(
            name="file_read",
            handler=lambda payload: {"content": "hello"},
            description="Read a file",
        )
    )
    return registry


def test_bare_invoker_without_policy_raises() -> None:
    """CapabilityInvoker with no policy must raise PermissionError on invoke()."""
    registry = _make_registry()
    invoker = CapabilityInvoker(registry=registry)
    with pytest.raises(PermissionError, match="no CapabilityPolicy"):
        invoker.invoke("file_read", {"path": "foo.txt"})


def test_bare_invoker_allow_unguarded_bypasses_policy_check() -> None:
    """allow_unguarded=True must allow invocation without a policy (test/internal use)."""
    registry = _make_registry()
    invoker = CapabilityInvoker(registry=registry, allow_unguarded=True)
    result = invoker.invoke("file_read", {"path": "foo.txt"})
    assert result.get("content") == "hello"
