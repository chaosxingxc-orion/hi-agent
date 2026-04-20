from hi_agent.capability.adapters.descriptor_factory import (
    CapabilityDescriptor,
    CapabilityDescriptorFactory,
)


def test_descriptor_has_new_fields():
    desc = CapabilityDescriptor(name="test")
    assert desc.toolset_id == "default"
    assert desc.required_env == {}
    assert desc.output_budget_tokens == 0
    assert desc.availability_probe is None


def test_descriptor_new_fields_settable():
    desc = CapabilityDescriptor(
        name="test",
        toolset_id="llm-tools",
        required_env={"API_KEY": "test key"},
        output_budget_tokens=4096,
    )
    assert desc.toolset_id == "llm-tools"
    assert desc.required_env == {"API_KEY": "test key"}
    assert desc.output_budget_tokens == 4096


def test_factory_build_descriptor_has_new_fields():
    factory = CapabilityDescriptorFactory()
    desc = factory.build_descriptor("plan")
    assert hasattr(desc, "toolset_id")
    assert hasattr(desc, "required_env")
    assert hasattr(desc, "output_budget_tokens")
    assert hasattr(desc, "availability_probe")


def test_factory_infers_required_env_for_llm_capability():
    factory = CapabilityDescriptorFactory()
    desc = factory.build_descriptor("plan")
    # plan is LLM-backed → should have ANTHROPIC_API_KEY in required_env
    assert "ANTHROPIC_API_KEY" in desc.required_env


def test_factory_no_required_env_for_non_llm():
    factory = CapabilityDescriptorFactory()
    desc = factory.build_descriptor("read_file")
    # read_file is not LLM-backed → no required_env
    assert "ANTHROPIC_API_KEY" not in desc.required_env


def test_backward_compat_existing_fields():
    """Existing constructor calls still work."""
    desc = CapabilityDescriptor(
        name="test",
        effect_class="read_only",
        tags=("search",),
    )
    assert desc.effect_class == "read_only"
    assert desc.toolset_id == "default"  # new field has default
