"""Tests for hi_agent.profiles contracts and registry."""

from __future__ import annotations

import pytest

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.registry import ProfileRegistry


# ---------------------------------------------------------------------------
# ProfileSpec
# ---------------------------------------------------------------------------

class TestProfileSpec:
    def test_minimal_creation(self):
        p = ProfileSpec(profile_id="minimal", display_name="Minimal Profile")
        assert p.profile_id == "minimal"
        assert p.display_name == "Minimal Profile"
        assert p.description == ""
        assert p.required_capabilities == []
        assert p.stage_actions == {}
        assert p.stage_graph_factory is None
        assert p.evaluator_factory is None
        assert p.config_overrides == {}
        assert p.metadata == {}

    def test_full_creation(self):
        p = ProfileSpec(
            profile_id="cs",
            display_name="Customer Support",
            description="Routes customer queries",
            required_capabilities=["classify_intent", "lookup_kb", "generate_reply"],
            stage_actions={"intake": "classify_intent", "resolve": "lookup_kb", "respond": "generate_reply"},
            config_overrides={"gate_quality_threshold": 0.7},
            metadata={"owner": "support-team"},
        )
        assert "classify_intent" in p.required_capabilities
        assert p.stage_actions["intake"] == "classify_intent"
        assert p.config_overrides["gate_quality_threshold"] == 0.7

    def test_to_dict_omits_callables(self):
        p = ProfileSpec(
            profile_id="test",
            display_name="Test",
            stage_graph_factory=lambda: None,
            evaluator_factory=lambda: None,
        )
        d = p.to_dict()
        assert "stage_graph_factory" not in d
        assert "evaluator_factory" not in d
        assert "profile_id" in d

    def test_from_dict_roundtrip(self):
        p = ProfileSpec(
            profile_id="p1",
            display_name="Profile One",
            description="A test profile",
            required_capabilities=["cap_a", "cap_b"],
            stage_actions={"s1": "action_a", "s2": "action_b"},
            config_overrides={"max_llm_calls": 10},
            metadata={"version": "1.0"},
        )
        d = p.to_dict()
        p2 = ProfileSpec.from_dict(d)
        assert p2.profile_id == p.profile_id
        assert p2.display_name == p.display_name
        assert p2.description == p.description
        assert p2.required_capabilities == p.required_capabilities
        assert p2.stage_actions == p.stage_actions
        assert p2.config_overrides == p.config_overrides
        assert p2.metadata == p.metadata
        assert p2.stage_graph_factory is None  # not serialized
        assert p2.evaluator_factory is None

    def test_from_dict_missing_optional_fields(self):
        d = {"profile_id": "minimal", "display_name": "Min"}
        p = ProfileSpec.from_dict(d)
        assert p.profile_id == "minimal"
        assert p.required_capabilities == []
        assert p.stage_actions == {}


# ---------------------------------------------------------------------------
# ProfileRegistry
# ---------------------------------------------------------------------------

class TestProfileRegistry:
    def test_register_and_get(self):
        reg = ProfileRegistry()
        p = ProfileSpec(profile_id="p1", display_name="P1")
        reg.register(p)
        assert reg.get("p1") is p

    def test_get_missing_returns_none(self):
        reg = ProfileRegistry()
        assert reg.get("nonexistent") is None

    def test_has(self):
        reg = ProfileRegistry()
        reg.register(ProfileSpec(profile_id="p1", display_name="P1"))
        assert reg.has("p1") is True
        assert reg.has("p2") is False

    def test_count(self):
        reg = ProfileRegistry()
        assert reg.count() == 0
        reg.register(ProfileSpec(profile_id="p1", display_name="P1"))
        reg.register(ProfileSpec(profile_id="p2", display_name="P2"))
        assert reg.count() == 2

    def test_list_profiles(self):
        reg = ProfileRegistry()
        p1 = ProfileSpec(profile_id="p1", display_name="P1")
        p2 = ProfileSpec(profile_id="p2", display_name="P2")
        reg.register(p1)
        reg.register(p2)
        profiles = reg.list_profiles()
        assert len(profiles) == 2
        assert p1 in profiles
        assert p2 in profiles

    def test_remove_existing(self):
        reg = ProfileRegistry()
        reg.register(ProfileSpec(profile_id="p1", display_name="P1"))
        removed = reg.remove("p1")
        assert removed is True
        assert reg.has("p1") is False
        assert reg.count() == 0

    def test_remove_missing_returns_false(self):
        reg = ProfileRegistry()
        assert reg.remove("nonexistent") is False

    def test_clear(self):
        reg = ProfileRegistry()
        reg.register(ProfileSpec(profile_id="p1", display_name="P1"))
        reg.register(ProfileSpec(profile_id="p2", display_name="P2"))
        reg.clear()
        assert reg.count() == 0

    def test_duplicate_registration_raises(self):
        reg = ProfileRegistry()
        p = ProfileSpec(profile_id="p1", display_name="P1")
        reg.register(p)
        with pytest.raises(ValueError, match="p1"):
            reg.register(ProfileSpec(profile_id="p1", display_name="P1 duplicate"))

    def test_integration_with_rule_route_engine(self):
        """ProfileSpec.stage_actions can be passed directly to RuleRouteEngine."""
        from hi_agent.route_engine.rule_engine import RuleRouteEngine

        profile = ProfileSpec(
            profile_id="support",
            display_name="Support Profile",
            stage_actions={
                "intake": "classify_intent",
                "resolve": "lookup_kb",
                "respond": "generate_reply",
            },
        )

        engine = RuleRouteEngine(stage_actions=profile.stage_actions)
        # Engine should use profile's stage_actions, not the TRACE defaults
        proposals = engine.propose("intake", "run-001", 1)
        assert len(proposals) >= 1
        action_kinds = [p.action_kind for p in proposals]
        assert "classify_intent" in action_kinds

    def test_integration_custom_stage_not_in_defaults(self):
        """A profile with non-TRACE stage names works correctly."""
        from hi_agent.route_engine.rule_engine import RuleRouteEngine

        profile = ProfileSpec(
            profile_id="data_pipeline",
            display_name="Data Pipeline",
            stage_actions={"ingest": "load_data", "transform": "apply_rules", "export": "write_output"},
        )
        engine = RuleRouteEngine(stage_actions=profile.stage_actions)
        proposals = engine.propose("ingest", "run-002", 1)
        action_kinds = [p.action_kind for p in proposals]
        assert "load_data" in action_kinds
