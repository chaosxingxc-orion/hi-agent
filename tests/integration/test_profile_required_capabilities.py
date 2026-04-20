"""Tests for profile required_capabilities enforcement."""
from __future__ import annotations

import pytest


class TestRequiredCapabilitiesEnforcement:
    def test_missing_capability_raises_before_execution(self):
        """Executor construction fails fast when required capabilities are absent."""
        import uuid

        from hi_agent.config.builder import MissingCapabilityError, SystemBuilder
        from hi_agent.contracts.task import TaskContract
        from hi_agent.profiles.contracts import ProfileSpec

        builder = SystemBuilder()
        builder.build_profile_registry().register(ProfileSpec(
            profile_id="strict_profile",
            display_name="Strict",
            stage_actions={"step": "do_it"},
            required_capabilities=["web_search", "missing_cap_xyz"],
        ))

        contract = TaskContract(
            task_id=uuid.uuid4().hex[:12],
            goal="test",
            profile_id="strict_profile",
        )
        with pytest.raises(MissingCapabilityError) as exc_info:
            builder.build_executor(contract)

        assert "missing_cap_xyz" in str(exc_info.value)
        assert "strict_profile" in str(exc_info.value)

    def test_all_capabilities_present_succeeds(self):
        """Executor construction succeeds when all required capabilities are registered."""
        import uuid

        from hi_agent.capability.registry import CapabilitySpec
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.contracts.task import TaskContract
        from hi_agent.profiles.contracts import ProfileSpec

        builder = SystemBuilder()
        # Register the required capability into the shared singleton registry.
        cap_registry = builder.build_capability_registry()
        cap_registry.register(CapabilitySpec(
            name="my_cap",
            handler=lambda payload: {"output": "ok"},
        ))

        builder.build_profile_registry().register(ProfileSpec(
            profile_id="satisfied_profile",
            display_name="Satisfied",
            stage_actions={"step": "my_cap"},
            required_capabilities=["my_cap"],
        ))

        contract = TaskContract(
            task_id=uuid.uuid4().hex[:12],
            goal="test",
            profile_id="satisfied_profile",
        )
        # Should not raise
        executor = builder.build_executor(contract)
        assert executor is not None

    def test_no_required_capabilities_always_succeeds(self):
        """Profiles without required_capabilities never fail the check."""
        import uuid

        from hi_agent.config.builder import SystemBuilder
        from hi_agent.contracts.task import TaskContract
        from hi_agent.profiles.contracts import ProfileSpec

        builder = SystemBuilder()
        builder.build_profile_registry().register(ProfileSpec(
            profile_id="open_profile",
            display_name="Open",
            stage_actions={"step": "anything"},
        ))
        contract = TaskContract(
            task_id=uuid.uuid4().hex[:12],
            goal="test",
            profile_id="open_profile",
        )
        executor = builder.build_executor(contract)
        assert executor is not None
