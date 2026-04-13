"""Tests that capability registry and invoker share the same instance."""
from __future__ import annotations
import pytest


class TestCapabilityChainUnity:
    def test_invoker_uses_shared_registry(self):
        """build_invoker() must return an invoker backed by build_capability_registry()."""
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        registry = builder.build_capability_registry()
        invoker = builder.build_invoker()

        # Must be the SAME registry instance
        assert invoker.registry is registry

    def test_registered_capability_reachable_via_invoker(self):
        """A capability registered in build_capability_registry() is accessible via invoker."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.capability.registry import CapabilitySpec

        builder = SystemBuilder()
        registry = builder.build_capability_registry()
        registry.register(CapabilitySpec(name="custom_test_cap", handler=lambda p: {"result": "ok"}))

        invoker = builder.build_invoker()
        # Must find it without raising KeyError
        spec = invoker.registry.get("custom_test_cap")
        assert spec is not None
        assert spec.name == "custom_test_cap"

    def test_build_capability_registry_is_singleton(self):
        """build_capability_registry() returns the same instance on multiple calls."""
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        r1 = builder.build_capability_registry()
        r2 = builder.build_capability_registry()
        assert r1 is r2

    def test_constructor_injected_capability_registry_is_used(self):
        """Constructor-injected registry is used by build_capability_registry()."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec

        pre_built = CapabilityRegistry()
        pre_built.register(CapabilitySpec(name="injected_cap", handler=lambda p: {}))

        builder = SystemBuilder(capability_registry=pre_built)
        assert builder.build_capability_registry() is pre_built
        assert "injected_cap" in builder.build_capability_registry().list_names()
