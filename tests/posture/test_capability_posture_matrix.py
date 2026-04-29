"""Tests for per-capability posture matrix on CapabilityDescriptor."""
from __future__ import annotations

import pytest
from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry, CapabilitySpec


def _make_registry() -> CapabilityRegistry:
    return CapabilityRegistry()


def test_descriptor_has_posture_fields():
    desc = CapabilityDescriptor(name="test_cap")
    assert hasattr(desc, "available_in_dev")
    assert hasattr(desc, "available_in_research")
    assert hasattr(desc, "available_in_prod")


def test_default_posture_all_true():
    desc = CapabilityDescriptor(name="test_cap")
    assert desc.available_in_dev is True
    assert desc.available_in_research is True
    assert desc.available_in_prod is True


def test_shell_exec_blocked_in_prod():
    """shell_exec must default available_in_prod=False."""
    from hi_agent.capability.tools.builtin import get_builtin_capabilities
    caps = {spec.name: spec for spec in get_builtin_capabilities()}
    if "shell_exec" not in caps:
        pytest.skip("shell_exec not registered as builtin")
    desc = caps["shell_exec"].descriptor
    assert desc is not None
    assert desc.available_in_prod is False, "shell_exec must have available_in_prod=False"


def test_l0_cap_blocked_in_research():
    """L0 capabilities must not be available in research posture when strict."""
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="l0_cap",
        maturity_level="L0",
        available_in_research=False,
    )
    spec = CapabilitySpec(name="l0_cap", handler=lambda _: {}, descriptor=desc)
    registry.register(spec)
    # Under research posture, l0_cap should be reported as unavailable
    ok, reason = registry.probe_availability_with_posture("l0_cap", posture="research")
    assert not ok
    lower = reason.lower()
    assert "research" in lower or "posture" in lower or "available" in lower


def test_manifest_dict_reflects_per_capability_matrix():
    """to_extension_manifest_dict must use per-capability fields, not hardcoded dict."""
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="restricted_cap",
        available_in_dev=True,
        available_in_research=True,
        available_in_prod=False,
    )
    spec = CapabilitySpec(name="restricted_cap", handler=lambda _: {}, descriptor=desc)
    registry.register(spec)
    manifest = registry.to_extension_manifest_dict("restricted_cap")
    posture = manifest.get("posture_support", {})
    assert posture.get("dev") is True
    assert posture.get("research") is True
    assert posture.get("prod") is False  # was hardcoded True before this fix
