"""Regression tests: profile-provided topology must not be overridden by TRACE sample defaults."""

from __future__ import annotations


class TestProfileDoesNotLeakTraceSampleDefaults:
    def test_resolved_profile_stage_actions_are_used_not_trace(self):
        """When profile provides stage_actions, RuleRouteEngine uses them, not TRACE defaults.

        The isolation guarantee lives in RuleRouteEngine: when a profile-scoped
        stage_actions dict is injected, the engine's STAGE_ACTIONS is replaced
        with the profile dict.  Consequently, a TRACE-only stage like S1_understand
        maps to "unknown" (not the TRACE default "analyze_goal"), which is the
        correct isolation behaviour.  The HybridRouteEngine layer calls LLM for
        low-confidence proposals; we verify isolation at the rule layer where the
        contract is defined.
        """
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.profiles.contracts import ProfileSpec
        from hi_agent.route_engine.rule_engine import RuleRouteEngine

        builder = SystemBuilder()
        reg = builder.build_profile_registry()
        reg.register(
            ProfileSpec(
                profile_id="custom",
                display_name="Custom",
                stage_actions={"plan": "run_planner", "execute": "run_executor"},
            )
        )
        resolved = builder._resolve_profile("custom")
        assert resolved is not None

        # Build the rule engine directly with profile's stage_actions to verify isolation.
        # This is the layer that owns the isolation guarantee.
        rule_engine = RuleRouteEngine(stage_actions=resolved.stage_actions)

        # Profile stages route to profile capabilities
        proposals = rule_engine.propose("plan", "run-1", 1)
        kinds = [p.action_kind for p in proposals]
        assert "run_planner" in kinds

        # TRACE stages should NOT appear when using profile stage_actions
        # (profile only has 'plan' and 'execute', not TRACE's S1-S5)
        trace_proposals = rule_engine.propose("S1_understand", "run-1", 1)
        # S1_understand is not in profile stage_actions, so no profile-specific routing
        # But it should not inject TRACE defaults when a profile is active
        for p in trace_proposals:
            assert p.action_kind not in ("analyze_goal",), (
                "TRACE default 'analyze_goal' leaked into profile runtime "
                f"for stage S1_understand: {p}"
            )

    def test_no_profile_trace_fallback_works(self):
        """Without profile, TRACE S1-S5 defaults are available as fallback."""
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        engine = builder._build_route_engine(stage_actions=None)

        proposals = engine.propose("S1_understand", "run-trace", 1)
        assert len(proposals) >= 1

    def test_profile_and_trace_runtimes_are_isolated(self):
        """Two builders with different profiles do not share stage_actions state."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.profiles.contracts import ProfileSpec

        b1 = SystemBuilder()
        b1.build_profile_registry().register(
            ProfileSpec(
                profile_id="p1",
                display_name="P1",
                stage_actions={"alpha": "do_alpha"},
            )
        )
        b2 = SystemBuilder()
        b2.build_profile_registry().register(
            ProfileSpec(
                profile_id="p2",
                display_name="P2",
                stage_actions={"beta": "do_beta"},
            )
        )

        r1 = b1._resolve_profile("p1")
        r2 = b2._resolve_profile("p2")

        assert r1 is not None and r1.stage_actions == {"alpha": "do_alpha"}
        assert r2 is not None and r2.stage_actions == {"beta": "do_beta"}

        # Cross-check: p1 registry does not see p2
        assert b1._resolve_profile("p2") is None
