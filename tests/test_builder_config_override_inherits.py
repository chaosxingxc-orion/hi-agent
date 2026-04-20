"""Tests that config_patch and config_overrides paths inherit registry state."""
from __future__ import annotations


class TestConfigOverrideInheritsRegistries:
    def test_config_patch_inherits_capability_registry(self):
        """build_executor with config_patch must see capabilities registered before the call."""
        import uuid

        from hi_agent.capability.registry import CapabilitySpec
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.contracts.task import TaskContract
        from hi_agent.profiles.contracts import ProfileSpec

        builder = SystemBuilder()

        # Register profile with required capabilities
        builder.register_profile(ProfileSpec(
            profile_id="patch_test",
            display_name="Patch Test",
            stage_actions={"step": "patch_cap"},
            required_capabilities=["patch_cap"],
        ))

        # Register the required capability
        builder.build_capability_registry().register(
            CapabilitySpec(name="patch_cap", handler=lambda p: {"output": "ok"})
        )

        contract = TaskContract(
            task_id=uuid.uuid4().hex[:12],
            goal="test",
            profile_id="patch_test",
        )

        # With config_patch — must NOT raise MissingCapabilityError
        executor = builder.build_executor(contract, config_patch={"max_stages": 3})
        assert executor is not None

    def test_no_config_patch_and_with_config_patch_see_same_capabilities(self):
        """Same capabilities visible regardless of whether config_patch is used."""
        import uuid

        from hi_agent.capability.registry import CapabilitySpec
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.contracts.task import TaskContract
        from hi_agent.profiles.contracts import ProfileSpec

        builder = SystemBuilder()
        builder.register_profile(ProfileSpec(
            profile_id="consistency_test",
            display_name="Consistency",
            stage_actions={"step": "my_cap"},
            required_capabilities=["my_cap"],
        ))
        builder.build_capability_registry().register(
            CapabilitySpec(name="my_cap", handler=lambda p: {"output": "ok"})
        )

        def make_contract():
            return TaskContract(
                task_id=uuid.uuid4().hex[:12],
                goal="test consistency",
                profile_id="consistency_test",
            )

        # Both should succeed without MissingCapabilityError
        e1 = builder.build_executor(make_contract())
        e2 = builder.build_executor(make_contract(), config_patch={"max_stages": 5})
        assert e1 is not None
        assert e2 is not None
