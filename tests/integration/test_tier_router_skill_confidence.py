"""Tests for skill_confidence signal in TierRouter tier selection.

Verifies that a high-confidence skill (success_rate >= 0.85) causes
_resolve_tier() and select_model() to downgrade by one tier, enabling
cost reduction as skills improve (P2 principle).
"""

from __future__ import annotations

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
) -> RegisteredModel:
    return RegisteredModel(
        model_id=model_id,
        provider="test",
        tier=tier,
        cost_input_per_mtok=cost_in,
        cost_output_per_mtok=cost_out,
        capabilities=[],
        context_window=128_000,
        is_available=True,
    )


def _populated_registry() -> ModelRegistry:
    """Registry with one model per tier."""
    reg = ModelRegistry()
    reg.register(_make_model("strong-1", ModelTier.STRONG, 15.0, 75.0))
    reg.register(_make_model("medium-1", ModelTier.MEDIUM, 3.0, 15.0))
    reg.register(_make_model("light-1", ModelTier.LIGHT, 0.5, 2.0))
    return reg


# ---------------------------------------------------------------------------
# _resolve_tier tests
# ---------------------------------------------------------------------------


class TestResolveTierSkillConfidence:
    def setup_method(self) -> None:
        self.router = TierRouter(registry=_populated_registry())

    def test_no_skill_confidence_returns_base_tier(self) -> None:
        """Without skill_confidence, purpose mapping is unchanged."""
        tier = self.router._resolve_tier("execution", "moderate", None, skill_confidence=None)
        # "execution" defaults to MEDIUM
        assert tier == ModelTier.MEDIUM

    def test_low_skill_confidence_does_not_downgrade(self) -> None:
        """skill_confidence below threshold should not trigger downgrade."""
        tier = self.router._resolve_tier("execution", "moderate", None, skill_confidence=0.80)
        assert tier == ModelTier.MEDIUM

    def test_exact_threshold_triggers_downgrade(self) -> None:
        """skill_confidence == 0.85 should trigger one-step downgrade."""
        tier = self.router._resolve_tier("execution", "moderate", None, skill_confidence=0.85)
        assert tier == ModelTier.LIGHT

    def test_high_skill_confidence_downgrades_one_step(self) -> None:
        """skill_confidence > 0.85 downgrades medium -> light."""
        tier = self.router._resolve_tier("execution", "moderate", None, skill_confidence=0.90)
        assert tier == ModelTier.LIGHT

    def test_high_skill_confidence_downgrades_strong_to_medium(self) -> None:
        """skill_confidence > 0.85 downgrades strong -> medium (not all the way to light)."""
        # Set a purpose that maps to STRONG
        self.router.set_tier("heavy_analysis", ModelTier.STRONG)
        tier = self.router._resolve_tier("heavy_analysis", "moderate", None, skill_confidence=0.92)
        assert tier == ModelTier.MEDIUM

    def test_skill_confidence_does_not_downgrade_below_light(self) -> None:
        """skill_confidence should not push tier below LIGHT (already at minimum)."""
        self.router.set_tier("low_purpose", ModelTier.LIGHT)
        tier = self.router._resolve_tier("low_purpose", "moderate", None, skill_confidence=0.95)
        assert tier == ModelTier.LIGHT

    def test_skill_confidence_downgrade_is_one_step_only(self) -> None:
        """A single skill_confidence signal causes at most one step of downgrade."""
        self.router.set_tier("heavy_analysis", ModelTier.STRONG)
        base_tier = self.router._resolve_tier(
            "heavy_analysis", "moderate", None, skill_confidence=None
        )
        confident_tier = self.router._resolve_tier(
            "heavy_analysis", "moderate", None, skill_confidence=0.95
        )
        # STRONG -> MEDIUM (one step), NOT LIGHT (two steps)
        assert base_tier == ModelTier.STRONG
        assert confident_tier == ModelTier.MEDIUM

    def test_skill_confidence_respects_allow_downgrade_false(self) -> None:
        """If allow_downgrade=False for a purpose, skill_confidence must not downgrade."""
        self.router.set_tier("critical", ModelTier.STRONG, allow_downgrade=False)
        tier = self.router._resolve_tier("critical", "moderate", None, skill_confidence=0.99)
        assert tier == ModelTier.STRONG


# ---------------------------------------------------------------------------
# select_model integration tests
# ---------------------------------------------------------------------------


class TestSelectModelSkillConfidence:
    def setup_method(self) -> None:
        self.router = TierRouter(registry=_populated_registry())

    def test_select_model_without_skill_confidence(self) -> None:
        """select_model without skill_confidence picks medium-tier model for 'execution'."""
        model = self.router.select_model("execution", skill_confidence=None)
        assert model.tier == ModelTier.MEDIUM

    def test_select_model_with_high_skill_confidence(self) -> None:
        """select_model with high skill_confidence picks light-tier model for 'execution'."""
        model = self.router.select_model("execution", skill_confidence=0.90)
        assert model.tier == ModelTier.LIGHT

    def test_select_model_skill_confidence_matches_resolve_tier(self) -> None:
        """select_model result tier matches what _resolve_tier returns."""
        base_tier = self.router._resolve_tier("execution", "moderate", None, skill_confidence=None)
        confident_tier = self.router._resolve_tier(
            "execution", "moderate", None, skill_confidence=0.90
        )
        base_model = self.router.select_model("execution", skill_confidence=None)
        confident_model = self.router.select_model("execution", skill_confidence=0.90)
        assert base_model.tier == base_tier
        assert confident_model.tier == confident_tier
        assert confident_tier != base_tier


# ---------------------------------------------------------------------------
# TierAwareLLMGateway integration tests
# ---------------------------------------------------------------------------


class TestTierAwareLLMGatewaySkillConfidence:
    def _make_gateway(self) -> object:
        from hi_agent.llm.tier_router import TierAwareLLMGateway

        registry = _populated_registry()
        router = TierRouter(registry=registry)
        selected_models: list[str] = []

        class _FakeInner:
            def complete(self, request: object) -> str:
                selected_models.append(getattr(request, "model", "unknown"))
                return "ok"

            def supports_model(self, model: str) -> bool:
                return True

        gw = TierAwareLLMGateway(inner=_FakeInner(), tier_router=router, registry=registry)
        gw._selected_models = selected_models  # type: ignore[attr-defined]  expiry_wave: permanent
        return gw

    def test_gateway_reads_skill_confidence_from_metadata(self) -> None:
        """TierAwareLLMGateway picks a light model when skill_confidence=0.95 in metadata."""
        from hi_agent.llm.protocol import LLMRequest

        gw = self._make_gateway()
        request = LLMRequest(
            messages=[],
            model="default",
            metadata={
                "purpose": "execution",
                "skill_confidence": 0.95,
            },
        )
        gw.complete(request)
        # The selected model should be the light tier model
        assert gw._selected_models[-1] == "light-1"  # type: ignore[attr-defined]  expiry_wave: permanent

    def test_gateway_ignores_low_skill_confidence(self) -> None:
        """TierAwareLLMGateway does not downgrade with skill_confidence < 0.85."""
        from hi_agent.llm.protocol import LLMRequest

        gw = self._make_gateway()
        request = LLMRequest(
            messages=[],
            model="default",
            metadata={
                "purpose": "execution",
                "skill_confidence": 0.70,
            },
        )
        gw.complete(request)
        # execution maps to MEDIUM; low confidence should not change that
        assert gw._selected_models[-1] == "medium-1"  # type: ignore[attr-defined]  expiry_wave: permanent
