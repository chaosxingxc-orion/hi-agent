"""Tests for model registry, tier routing, and cost-aware model selection."""

from __future__ import annotations

import pytest
from hi_agent.llm.model_selector import ModelSelector, SelectionResult
from hi_agent.llm.registry import ModelRegistry, ModelTier, RegisteredModel
from hi_agent.llm.tier_router import TierRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(
    model_id: str,
    tier: str = ModelTier.MEDIUM,
    cost_in: float = 2.0,
    cost_out: float = 8.0,
    provider: str = "test",
    capabilities: list[str] | None = None,
    context_window: int = 128_000,
    is_available: bool = True,
) -> RegisteredModel:
    return RegisteredModel(
        model_id=model_id,
        provider=provider,
        tier=tier,
        cost_input_per_mtok=cost_in,
        cost_output_per_mtok=cost_out,
        capabilities=capabilities or [],
        context_window=context_window,
        is_available=is_available,
    )


def _populated_registry() -> ModelRegistry:
    """Registry with a few test models across tiers."""
    reg = ModelRegistry()
    reg.register(
        _make_model(
            "strong-a", ModelTier.STRONG, 15.0, 75.0, capabilities=["reasoning", "code", "vision"]
        )
    )
    reg.register(
        _make_model("strong-b", ModelTier.STRONG, 20.0, 80.0, capabilities=["reasoning", "code"])
    )
    reg.register(
        _make_model("medium-a", ModelTier.MEDIUM, 3.0, 15.0, capabilities=["code", "tool_use"])
    )
    reg.register(_make_model("medium-b", ModelTier.MEDIUM, 2.0, 8.0, capabilities=["code"]))
    reg.register(_make_model("light-a", ModelTier.LIGHT, 0.8, 4.0, capabilities=["code"]))
    reg.register(_make_model("light-b", ModelTier.LIGHT, 0.1, 0.4, capabilities=["code"]))
    return reg


# ===========================================================================
# Registry tests
# ===========================================================================


class TestModelRegistry:
    def test_register_and_get(self) -> None:
        reg = ModelRegistry()
        m = _make_model("test-1")
        reg.register(m)
        assert reg.get("test-1") is m

    def test_get_missing_returns_none(self) -> None:
        reg = ModelRegistry()
        assert reg.get("nonexistent") is None

    def test_unregister(self) -> None:
        reg = ModelRegistry()
        reg.register(_make_model("m1"))
        reg.unregister("m1")
        assert reg.get("m1") is None

    def test_unregister_missing_no_error(self) -> None:
        reg = ModelRegistry()
        reg.unregister("nonexistent")  # should not raise

    def test_list_all(self) -> None:
        reg = _populated_registry()
        assert len(reg.list_all()) == 6

    def test_list_by_tier_sorted_by_cost(self) -> None:
        reg = _populated_registry()
        lights = reg.list_by_tier(ModelTier.LIGHT)
        assert len(lights) == 2
        # Should be sorted cheapest first
        assert lights[0].model_id == "light-b"  # 0.1+0.4 = 0.5
        assert lights[1].model_id == "light-a"  # 0.8+4.0 = 4.8

    def test_list_by_capability(self) -> None:
        reg = _populated_registry()
        vision_models = reg.list_by_capability("vision")
        assert len(vision_models) == 1
        assert vision_models[0].model_id == "strong-a"

    def test_list_by_capability_multiple(self) -> None:
        reg = _populated_registry()
        code_models = reg.list_by_capability("code")
        assert len(code_models) == 6  # all have "code"

    def test_cheapest_in_tier(self) -> None:
        reg = _populated_registry()
        cheapest = reg.cheapest_in_tier(ModelTier.LIGHT)
        assert cheapest is not None
        assert cheapest.model_id == "light-b"

    def test_cheapest_in_tier_empty(self) -> None:
        reg = ModelRegistry()
        assert reg.cheapest_in_tier(ModelTier.STRONG) is None

    def test_cheapest_in_tier_respects_availability(self) -> None:
        reg = ModelRegistry()
        reg.register(_make_model("cheap", ModelTier.LIGHT, 0.1, 0.1, is_available=False))
        reg.register(_make_model("expensive", ModelTier.LIGHT, 5.0, 5.0, is_available=True))
        cheapest = reg.cheapest_in_tier(ModelTier.LIGHT)
        assert cheapest is not None
        assert cheapest.model_id == "expensive"

    def test_get_or_cheapest_returns_exact(self) -> None:
        reg = _populated_registry()
        m = reg.get_or_cheapest("medium-a")
        assert m.model_id == "medium-a"

    def test_get_or_cheapest_fallback(self) -> None:
        reg = _populated_registry()
        m = reg.get_or_cheapest("nonexistent", fallback_tier=ModelTier.LIGHT)
        assert m.model_id == "light-b"

    def test_get_or_cheapest_unavailable_falls_back(self) -> None:
        reg = ModelRegistry()
        reg.register(_make_model("target", ModelTier.MEDIUM, is_available=False))
        reg.register(_make_model("fallback", ModelTier.LIGHT, 0.1, 0.4))
        m = reg.get_or_cheapest("target", fallback_tier=ModelTier.LIGHT)
        assert m.model_id == "fallback"

    def test_get_or_cheapest_raises_when_empty(self) -> None:
        reg = ModelRegistry()
        with pytest.raises(KeyError):
            reg.get_or_cheapest("nonexistent")

    def test_register_defaults(self) -> None:
        reg = ModelRegistry()
        reg.register_defaults()
        all_models = reg.list_all()
        assert len(all_models) == 8
        # Check tiers
        strong = reg.list_by_tier(ModelTier.STRONG)
        assert len(strong) == 1
        assert strong[0].model_id == "claude-opus-4-6"
        medium = reg.list_by_tier(ModelTier.MEDIUM)
        assert len(medium) >= 2
        light = reg.list_by_tier(ModelTier.LIGHT)
        assert len(light) >= 3

    def test_list_available_filters_unavailable(self) -> None:
        reg = ModelRegistry()
        reg.register(_make_model("avail", is_available=True))
        reg.register(_make_model("unavail", is_available=False))
        available = reg.list_available()
        assert len(available) == 1
        assert available[0].model_id == "avail"

    def test_estimated_cost(self) -> None:
        m = _make_model("m", cost_in=10.0, cost_out=50.0)
        # 1M input + 1M output = 10 + 50 = 60
        assert abs(m.estimated_cost(1_000_000, 1_000_000) - 60.0) < 0.001
        # 1K input + 1K output
        assert abs(m.estimated_cost(1000, 1000) - 0.06) < 0.001

    def test_register_override(self) -> None:
        """Re-registering a model_id replaces the old entry."""
        reg = ModelRegistry()
        reg.register(_make_model("m1", cost_in=1.0))
        reg.register(_make_model("m1", cost_in=99.0))
        assert reg.get("m1") is not None
        assert reg.get("m1").cost_input_per_mtok == 99.0


# ===========================================================================
# TierRouter tests
# ===========================================================================


class TestTierRouter:
    def _router_with_models(self) -> TierRouter:
        return TierRouter(_populated_registry())

    def test_default_tier_mapping(self) -> None:
        router = self._router_with_models()
        assert router.get_tier_for_purpose("perception") == ModelTier.LIGHT
        assert router.get_tier_for_purpose("control") == ModelTier.MEDIUM
        assert router.get_tier_for_purpose("execution") == ModelTier.MEDIUM
        assert router.get_tier_for_purpose("evaluation") == ModelTier.LIGHT
        assert router.get_tier_for_purpose("compression") == ModelTier.LIGHT
        assert router.get_tier_for_purpose("routing") == ModelTier.MEDIUM
        assert router.get_tier_for_purpose("skill_extraction") == ModelTier.MEDIUM

    def test_unknown_purpose_defaults_medium(self) -> None:
        router = self._router_with_models()
        assert router.get_tier_for_purpose("unknown") == ModelTier.MEDIUM

    def test_set_tier_override(self) -> None:
        router = self._router_with_models()
        router.set_tier("perception", ModelTier.STRONG)
        assert router.get_tier_for_purpose("perception") == ModelTier.STRONG

    def test_select_model_default(self) -> None:
        router = self._router_with_models()
        model = router.select_model("perception")  # light by default
        assert model.tier == ModelTier.LIGHT

    def test_select_model_complexity_simple_downgrades(self) -> None:
        router = self._router_with_models()
        # control defaults to medium; simple should downgrade to light
        model = router.select_model("control", complexity="simple")
        assert model.tier == ModelTier.LIGHT

    def test_select_model_complexity_complex_upgrades(self) -> None:
        router = self._router_with_models()
        # perception defaults to light; complex should upgrade to strong
        model = router.select_model("perception", complexity="complex")
        assert model.tier == ModelTier.STRONG

    def test_select_model_budget_forces_downgrade(self) -> None:
        router = self._router_with_models()
        # control defaults to medium; very low budget should force light
        model = router.select_model("control", budget_remaining_usd=0.05)
        assert model.tier == ModelTier.LIGHT

    def test_select_model_low_budget_one_tier_down(self) -> None:
        router = self._router_with_models()
        # execution defaults to medium; low budget -> light
        model = router.select_model("execution", budget_remaining_usd=0.30)
        assert model.tier == ModelTier.LIGHT

    def test_select_model_required_capabilities(self) -> None:
        router = self._router_with_models()
        # Only strong-a has "vision"
        model = router.select_model(
            "execution", complexity="complex", required_capabilities=["vision"]
        )
        assert model.model_id == "strong-a"

    def test_select_model_min_context_window(self) -> None:
        reg = ModelRegistry()
        reg.register(_make_model("small", ModelTier.MEDIUM, context_window=32_000))
        reg.register(_make_model("big", ModelTier.MEDIUM, context_window=200_000))
        router = TierRouter(reg)
        model = router.select_model("execution", min_context_window=100_000)
        assert model.model_id == "big"

    def test_select_with_fallback_returns_actual_tier(self) -> None:
        reg = ModelRegistry()
        # Only light models available
        reg.register(_make_model("only-light", ModelTier.LIGHT, 0.1, 0.4))
        router = TierRouter(reg)
        model, actual_tier = router.select_with_fallback("control")  # wants medium
        assert actual_tier == ModelTier.LIGHT
        assert model.model_id == "only-light"

    def test_select_with_fallback_target_tier(self) -> None:
        router = self._router_with_models()
        _model, actual_tier = router.select_with_fallback("perception")
        assert actual_tier == ModelTier.LIGHT

    def test_estimate_cost(self) -> None:
        router = self._router_with_models()
        cost = router.estimate_cost("perception", "moderate", 1_000_000, 1_000_000)
        # perception -> light, cheapest is light-b: 0.1 + 0.4 = 0.5
        assert abs(cost - 0.5) < 0.001

    def test_list_mappings(self) -> None:
        router = self._router_with_models()
        mappings = router.list_mappings()
        assert len(mappings) == 7
        purposes = {m.purpose for m in mappings}
        assert "perception" in purposes
        assert "control" in purposes

    def test_select_no_models_raises(self) -> None:
        reg = ModelRegistry()
        router = TierRouter(reg)
        with pytest.raises(KeyError):
            router.select_model("execution")

    def test_set_tier_no_upgrade(self) -> None:
        router = self._router_with_models()
        router.set_tier("perception", ModelTier.LIGHT, allow_upgrade=False)
        # Even with complex, should stay light because upgrade not allowed
        model = router.select_model("perception", complexity="complex")
        assert model.tier == ModelTier.LIGHT

    def test_set_tier_no_downgrade(self) -> None:
        router = self._router_with_models()
        router.set_tier("control", ModelTier.MEDIUM, allow_downgrade=False)
        # Even with simple complexity, should stay medium
        model = router.select_model("control", complexity="simple")
        assert model.tier == ModelTier.MEDIUM


# ===========================================================================
# ModelSelector tests
# ===========================================================================


class TestModelSelector:
    def _selector(self, budget: float = 10.0) -> ModelSelector:
        reg = _populated_registry()
        router = TierRouter(reg)
        return ModelSelector(reg, router, budget_usd=budget)

    def test_select_returns_result(self) -> None:
        sel = self._selector()
        result = sel.select("perception")
        assert isinstance(result, SelectionResult)
        assert result.model is not None
        assert result.tier_actual == ModelTier.LIGHT

    def test_select_within_budget(self) -> None:
        sel = self._selector(budget=10.0)
        result = sel.select("perception", input_tokens=1000, output_tokens=500)
        assert result.estimated_cost_usd < sel.remaining_budget + result.estimated_cost_usd

    def test_budget_enforcement_downgrade(self) -> None:
        sel = self._selector(budget=0.001)
        # Very tight budget should force downgrade
        result = sel.select("control", input_tokens=100_000, output_tokens=50_000)
        # Should pick the cheapest available
        assert result.model.tier in (ModelTier.LIGHT, ModelTier.MEDIUM)

    def test_record_actual_usage(self) -> None:
        sel = self._selector()
        assert sel.total_spent == 0.0
        cost = sel.record_actual_usage("light-b", 1_000_000, 1_000_000)
        assert cost > 0
        assert sel.total_spent == cost

    def test_record_actual_usage_unknown_model(self) -> None:
        sel = self._selector()
        cost = sel.record_actual_usage("nonexistent", 1000, 1000)
        assert cost == 0.0

    def test_request_upgrade(self) -> None:
        sel = self._selector()
        # perception defaults to light; upgrade should go to medium
        result = sel.request_upgrade("perception")
        assert result is not None
        assert result.upgraded is True
        assert result.tier_actual == ModelTier.MEDIUM

    def test_request_upgrade_already_strong(self) -> None:
        sel = self._selector()
        sel._router.set_tier("custom", ModelTier.STRONG)
        result = sel.request_upgrade("custom")
        assert result is None

    def test_remaining_budget_decreases(self) -> None:
        sel = self._selector(budget=1.0)
        initial = sel.remaining_budget
        sel.record_actual_usage("light-b", 1_000_000, 1_000_000)
        assert sel.remaining_budget < initial

    def test_remaining_budget_never_negative(self) -> None:
        sel = self._selector(budget=0.001)
        sel.record_actual_usage("strong-a", 10_000_000, 10_000_000)
        assert sel.remaining_budget == 0.0

    def test_get_cost_breakdown(self) -> None:
        sel = self._selector()
        sel.select("perception")
        sel.select("control")
        breakdown = sel.get_cost_breakdown()
        assert "total_spent" in breakdown
        assert "remaining_budget" in breakdown
        assert "total_selections" in breakdown
        assert breakdown["total_selections"] == 2
        assert "by_tier" in breakdown

    def test_selection_history(self) -> None:
        sel = self._selector()
        sel.select("perception")
        sel.select("control")
        sel.select("execution", complexity="complex")
        history = sel.get_selection_history()
        assert len(history) == 3

    def test_select_no_models_best_effort(self) -> None:
        """With models available but tight budget, still returns something."""
        sel = self._selector(budget=0.0001)
        result = sel.select("execution", complexity="complex")
        # Should still return a model (cheapest available)
        assert result.model is not None


# ===========================================================================
# Integration tests
# ===========================================================================


class TestIntegration:
    def test_full_flow_register_select_track(self) -> None:
        """Register models and verify end-to-end tier routing.

        Flow: perception(light) -> control(medium) -> execution(complex->strong).
        """
        reg = _populated_registry()
        router = TierRouter(reg)
        selector = ModelSelector(reg, router, budget_usd=5.0)

        # Perception -> light
        r1 = selector.select("perception", complexity="simple")
        assert r1.tier_actual == ModelTier.LIGHT

        # Control -> medium
        r2 = selector.select("control", complexity="moderate")
        assert r2.tier_actual == ModelTier.MEDIUM

        # Execution with complex -> strong
        r3 = selector.select("execution", complexity="complex")
        assert r3.tier_actual == ModelTier.STRONG

        assert len(selector.get_selection_history()) == 3

    def test_cost_tracking_across_selections(self) -> None:
        reg = _populated_registry()
        router = TierRouter(reg)
        selector = ModelSelector(reg, router, budget_usd=1.0)

        selector.select("perception")
        selector.record_actual_usage("light-b", 50_000, 10_000)
        first_spent = selector.total_spent

        selector.select("control")
        selector.record_actual_usage("medium-b", 50_000, 10_000)
        assert selector.total_spent > first_spent

    def test_downgrade_chain_under_budget_pressure(self) -> None:
        """Budget pressure: strong -> medium -> light."""
        reg = _populated_registry()
        router = TierRouter(reg)
        selector = ModelSelector(reg, router, budget_usd=0.001)

        # Even requesting complex, tight budget forces downgrade
        result = selector.select(
            "execution", complexity="complex", input_tokens=100_000, output_tokens=50_000
        )
        # Should have been downgraded from strong
        assert result.model.tier in (ModelTier.LIGHT, ModelTier.MEDIUM)

    def test_upgrade_on_quality_failure(self) -> None:
        """Quality failure: light -> medium."""
        reg = _populated_registry()
        router = TierRouter(reg)
        selector = ModelSelector(reg, router, budget_usd=10.0)

        # First select perception (light)
        r1 = selector.select("perception")
        assert r1.tier_actual == ModelTier.LIGHT

        # Quality was poor, request upgrade
        r2 = selector.request_upgrade("perception", reason="poor quality output")
        assert r2 is not None
        assert r2.upgraded is True
        assert r2.tier_actual == ModelTier.MEDIUM

    def test_register_defaults_then_route(self) -> None:
        """Use register_defaults and route through the full stack."""
        reg = ModelRegistry()
        reg.register_defaults()
        router = TierRouter(reg)
        selector = ModelSelector(reg, router, budget_usd=10.0)

        r = selector.select("perception")
        assert r.model.provider in ("anthropic", "openai")
        assert r.tier_actual == ModelTier.LIGHT

        r = selector.select("control", complexity="complex")
        assert r.tier_actual == ModelTier.STRONG
        assert r.model.model_id == "claude-opus-4-6"
