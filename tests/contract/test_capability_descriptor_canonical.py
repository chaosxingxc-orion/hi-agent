"""Contract tests: single canonical CapabilityDescriptor import point.

CO-6: verifies that:
- CapabilityDescriptor is importable from hi_agent.capability.registry (canonical).
- CapabilityDescriptor is re-exported from descriptor_factory (backward compat).
- Both import paths resolve to the *same* class object.
- build_capability_view() produces the expected dict shape.
- CapabilityDescriptorFactory.build_descriptor() returns canonical instances.
"""

from __future__ import annotations


def test_canonical_import_from_registry() -> None:
    """CapabilityDescriptor must be importable from hi_agent.capability.registry."""
    from hi_agent.capability.registry import CapabilityDescriptor

    desc = CapabilityDescriptor(name="test_cap")
    assert desc.name == "test_cap"


def test_backward_compat_import_from_descriptor_factory() -> None:
    """CapabilityDescriptor must still be importable from descriptor_factory."""
    from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor

    desc = CapabilityDescriptor(name="test_cap_factory")
    assert desc.name == "test_cap_factory"


def test_both_import_paths_same_class() -> None:
    """Both import paths must resolve to the identical class object."""
    from hi_agent.capability.adapters.descriptor_factory import (
        CapabilityDescriptor as FactoryCD,
    )
    from hi_agent.capability.registry import CapabilityDescriptor as RegistryCD

    assert FactoryCD is RegistryCD, (
        "descriptor_factory.CapabilityDescriptor must be the registry canonical class"
    )


def test_descriptor_has_platform_governance_fields() -> None:
    """Canonical CapabilityDescriptor must have all platform governance fields."""
    from hi_agent.capability.registry import CapabilityDescriptor

    desc = CapabilityDescriptor(name="gov_cap")
    assert hasattr(desc, "risk_class")
    assert hasattr(desc, "side_effect_class")
    assert hasattr(desc, "requires_auth")
    assert hasattr(desc, "requires_approval")
    assert hasattr(desc, "source_reference_policy")
    assert hasattr(desc, "provenance_required")
    assert hasattr(desc, "reproducibility_level")
    assert hasattr(desc, "license_policy")


def test_descriptor_has_adapter_fields() -> None:
    """Canonical CapabilityDescriptor must have all adapter/factory fields."""
    from hi_agent.capability.registry import CapabilityDescriptor

    desc = CapabilityDescriptor(name="adapter_cap")
    assert hasattr(desc, "effect_class")
    assert hasattr(desc, "tags")
    assert hasattr(desc, "sandbox_level")
    assert hasattr(desc, "description")
    assert hasattr(desc, "parameters")
    assert hasattr(desc, "extra")
    assert hasattr(desc, "toolset_id")
    assert hasattr(desc, "output_budget_tokens")


def test_build_capability_view_output_shape() -> None:
    """build_capability_view() must return a dict with all required keys."""
    from hi_agent.capability.adapters.descriptor_factory import (
        CapabilityDescriptor,
        build_capability_view,
    )

    desc = CapabilityDescriptor(
        name="my_cap",
        effect_class="read_only",
        tags=("search", "web"),
        description="A web search capability",
        toolset_id="web-tools",
        required_env={"API_KEY": "search API key"},
        output_budget_tokens=1024,
    )
    view = build_capability_view(desc)

    required_keys = (
        "name", "effect_class", "tags", "sandbox_level", "description",
        "parameters", "extra", "toolset_id", "required_env", "output_budget_tokens",
        "availability_probe", "risk_class", "requires_approval", "requires_auth",
        "source_reference_policy", "provenance_required",
    )
    for key in required_keys:
        assert key in view, f"build_capability_view() missing key {key!r}"

    assert view["name"] == "my_cap"
    assert view["effect_class"] == "read_only"
    assert view["tags"] == ["search", "web"]
    assert view["toolset_id"] == "web-tools"
    assert view["required_env"] == {"API_KEY": "search API key"}
    assert view["output_budget_tokens"] == 1024


def test_factory_build_descriptor_returns_canonical_instance() -> None:
    """CapabilityDescriptorFactory.build_descriptor() must return a canonical instance."""
    from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptorFactory
    from hi_agent.capability.registry import CapabilityDescriptor

    factory = CapabilityDescriptorFactory()
    desc = factory.build_descriptor("search_web")
    assert isinstance(desc, CapabilityDescriptor)
    assert desc.name == "search_web"
    assert desc.effect_class == "read_only"  # inferred from "search" verb


def test_factory_infers_effect_class_for_write_verbs() -> None:
    """CapabilityDescriptorFactory must infer effect_class from leading verb."""
    from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptorFactory

    factory = CapabilityDescriptorFactory()
    assert factory.build_descriptor("delete_record").effect_class == "irreversible_write"
    assert factory.build_descriptor("create_entry").effect_class == "idempotent_write"
    assert factory.build_descriptor("unknown_thing").effect_class == "unknown_effect"
