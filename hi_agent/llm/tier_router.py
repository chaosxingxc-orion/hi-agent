"""Tier-based model routing: task complexity -> model tier -> specific model.

Three tiers: strong, medium, light.
Each middleware/stage/purpose maps to a default tier.
Task complexity can override: simple->light, moderate->medium, complex->strong.
Cost budget can force downgrade: strong->medium->light.
Quality failure can force upgrade: light->medium->strong.
"""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.llm.registry import ModelRegistry, ModelTier, RegisteredModel

# Tier ordering for upgrade/downgrade logic
_TIER_ORDER = [ModelTier.LIGHT, ModelTier.MEDIUM, ModelTier.STRONG]


def _tier_index(tier: str) -> int:
    """Return numeric index for a tier (0=light, 1=medium, 2=strong)."""
    try:
        return _TIER_ORDER.index(tier)
    except ValueError:
        return 1  # default to medium


@dataclass
class TierMapping:
    """Maps a purpose to a default model tier."""

    purpose: str  # middleware name, stage_id, or custom label
    default_tier: str  # strong/medium/light
    allow_upgrade: bool = True  # can upgrade if quality is low
    allow_downgrade: bool = True  # can downgrade if budget is tight


class TierRouter:
    """Routes requests to models based on tier + complexity + budget."""

    def __init__(self, registry: ModelRegistry) -> None:
        """Initialize TierRouter."""
        self._registry = registry
        self._tier_map: dict[str, TierMapping] = {}
        self._complexity_overrides: dict[str, str] = {
            "simple": ModelTier.LIGHT,
            "moderate": ModelTier.MEDIUM,
            "complex": ModelTier.STRONG,
        }
        self._setup_defaults()

    def _setup_defaults(self) -> None:
        """Default middleware -> tier mapping."""
        defaults = [
            TierMapping("perception", ModelTier.LIGHT),
            TierMapping("control", ModelTier.MEDIUM),
            TierMapping("execution", ModelTier.MEDIUM),
            TierMapping("evaluation", ModelTier.LIGHT),
            TierMapping("compression", ModelTier.LIGHT),
            TierMapping("routing", ModelTier.MEDIUM),
            TierMapping("skill_extraction", ModelTier.MEDIUM),
        ]
        for mapping in defaults:
            self._tier_map[mapping.purpose] = mapping

    def set_tier(
        self,
        purpose: str,
        tier: str,
        allow_upgrade: bool = True,
        allow_downgrade: bool = True,
    ) -> None:
        """Override the tier for a purpose."""
        self._tier_map[purpose] = TierMapping(
            purpose=purpose,
            default_tier=tier,
            allow_upgrade=allow_upgrade,
            allow_downgrade=allow_downgrade,
        )

    def _resolve_tier(
        self,
        purpose: str,
        complexity: str,
        budget_remaining_usd: float | None,
    ) -> str:
        """Determine effective tier considering purpose, complexity, and budget."""
        mapping = self._tier_map.get(purpose)
        base_tier = mapping.default_tier if mapping else ModelTier.MEDIUM
        allow_upgrade = mapping.allow_upgrade if mapping else True
        allow_downgrade = mapping.allow_downgrade if mapping else True

        # Complexity override: only "simple" and "complex" move the tier.
        # "moderate" is neutral and does not override the purpose mapping.
        if complexity != "moderate":
            complexity_tier = self._complexity_overrides.get(complexity)
            if complexity_tier is not None:
                ci = _tier_index(complexity_tier)
                bi = _tier_index(base_tier)
                if (ci > bi and allow_upgrade) or (ci < bi and allow_downgrade):
                    base_tier = complexity_tier

        # Budget pressure: if budget is low, try to downgrade
        if budget_remaining_usd is not None and allow_downgrade:
            if budget_remaining_usd < 0.10:
                base_tier = ModelTier.LIGHT
            elif budget_remaining_usd < 0.50:
                idx = _tier_index(base_tier)
                if idx > 0:
                    base_tier = _TIER_ORDER[idx - 1]

        return base_tier

    def select_model(
        self,
        purpose: str,
        complexity: str = "moderate",
        required_capabilities: list[str] | None = None,
        budget_remaining_usd: float | None = None,
        min_context_window: int = 0,
    ) -> RegisteredModel:
        """Select the best model for a given request.

        Algorithm:
        1. Determine tier from purpose mapping
        2. Override tier based on complexity (simple->light, complex->strong)
        3. If budget_remaining is low, downgrade tier
        4. Filter by required_capabilities and min_context_window
        5. From matching models, pick cheapest available
        6. If no match in target tier, try adjacent tier

        Raises:
            KeyError: If no suitable model can be found.
        """
        target_tier = self._resolve_tier(purpose, complexity, budget_remaining_usd)
        model = self._find_in_tier(
            target_tier, required_capabilities, min_context_window
        )
        if model is not None:
            return model

        # Fallback: try adjacent tiers
        idx = _tier_index(target_tier)
        # Try one tier down, then one tier up
        for offset in [-1, 1, -2, 2]:
            adj = idx + offset
            if 0 <= adj < len(_TIER_ORDER):
                model = self._find_in_tier(
                    _TIER_ORDER[adj], required_capabilities, min_context_window
                )
                if model is not None:
                    return model

        # Last resort: any available model
        available = self._registry.list_available()
        if available:
            return min(
                available,
                key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
            )

        raise KeyError(
            f"No suitable model found for purpose={purpose!r}, "
            f"complexity={complexity!r}"
        )

    def _find_in_tier(
        self,
        tier: str,
        required_capabilities: list[str] | None,
        min_context_window: int,
    ) -> RegisteredModel | None:
        """Find cheapest available model in tier matching constraints."""
        candidates = [
            m
            for m in self._registry.list_by_tier(tier)
            if m.is_available and m.context_window >= min_context_window
        ]
        if required_capabilities:
            candidates = [
                m
                for m in candidates
                if all(cap in m.capabilities for cap in required_capabilities)
            ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
        )

    def select_with_fallback(
        self,
        purpose: str,
        complexity: str = "moderate",
        **kwargs: object,
    ) -> tuple[RegisteredModel, str]:
        """Select model with fallback chain. Returns (model, actual_tier).

        Fallback: target_tier -> one tier down -> one tier up -> any available.
        """
        target_tier = self._resolve_tier(
            purpose,
            complexity,
            kwargs.get("budget_remaining_usd"),  # type: ignore[arg-type]
        )
        required_caps: list[str] | None = kwargs.get("required_capabilities")  # type: ignore[assignment]
        min_ctx: int = kwargs.get("min_context_window", 0)  # type: ignore[assignment]

        # Try target tier
        model = self._find_in_tier(target_tier, required_caps, min_ctx)
        if model is not None:
            return model, target_tier

        # Try adjacent tiers
        idx = _tier_index(target_tier)
        for offset in [-1, 1, -2, 2]:
            adj = idx + offset
            if 0 <= adj < len(_TIER_ORDER):
                adj_tier = _TIER_ORDER[adj]
                model = self._find_in_tier(adj_tier, required_caps, min_ctx)
                if model is not None:
                    return model, adj_tier

        # Any available
        available = self._registry.list_available()
        if available:
            best = min(
                available,
                key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
            )
            return best, best.tier

        raise KeyError(f"No models available for purpose={purpose!r}")

    def estimate_cost(
        self,
        purpose: str,
        complexity: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost for a request without actually selecting."""
        model = self.select_model(purpose, complexity)
        return model.estimated_cost(input_tokens, output_tokens)

    def get_tier_for_purpose(self, purpose: str) -> str:
        """Get the configured tier for a purpose."""
        mapping = self._tier_map.get(purpose)
        return mapping.default_tier if mapping else ModelTier.MEDIUM

    def list_mappings(self) -> list[TierMapping]:
        """List all purpose -> tier mappings."""
        return list(self._tier_map.values())
