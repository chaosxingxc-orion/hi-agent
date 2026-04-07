"""Per-model cost calculation inspired by claude-code's modelCost.ts.

Pricing tiers for major LLM providers. Tracks cost across a session.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Pricing per million tokens."""

    input_per_mtok: float
    output_per_mtok: float
    cache_write_per_mtok: float = 0.0
    cache_read_per_mtok: float = 0.0


# Pricing table (as of 2026)
MODEL_PRICING: dict[str, ModelPricing] = {
    # Anthropic
    "claude-opus-4": ModelPricing(15.0, 75.0, 18.75, 1.5),
    "claude-sonnet-4": ModelPricing(3.0, 15.0, 3.75, 0.3),
    "claude-haiku-4": ModelPricing(0.8, 4.0, 1.0, 0.08),
    # OpenAI
    "gpt-4o": ModelPricing(2.5, 10.0, 0.0, 0.0),
    "gpt-4o-mini": ModelPricing(0.15, 0.6, 0.0, 0.0),
    "gpt-4.1": ModelPricing(2.0, 8.0, 0.0, 0.0),
    "gpt-4.1-mini": ModelPricing(0.4, 1.6, 0.0, 0.0),
    "gpt-4.1-nano": ModelPricing(0.1, 0.4, 0.0, 0.0),
}


class CostCalculator:
    """Calculate USD cost from token usage."""

    def __init__(
        self, custom_pricing: dict[str, ModelPricing] | None = None
    ) -> None:
        self._pricing = dict(MODEL_PRICING)
        if custom_pricing:
            self._pricing.update(custom_pricing)

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> float:
        """Calculate USD cost. Returns 0.0 for unknown models."""
        pricing = self._resolve_pricing(model)
        if pricing is None:
            return 0.0
        return (
            (input_tokens / 1_000_000) * pricing.input_per_mtok
            + (output_tokens / 1_000_000) * pricing.output_per_mtok
            + (cache_read_tokens / 1_000_000) * pricing.cache_read_per_mtok
            + (cache_creation_tokens / 1_000_000) * pricing.cache_write_per_mtok
        )

    def _resolve_pricing(self, model: str) -> ModelPricing | None:
        """Match model name to pricing tier (prefix match)."""
        if model in self._pricing:
            return self._pricing[model]
        # Try prefix matching
        for key, pricing in self._pricing.items():
            if model.startswith(key):
                return pricing
        return None
