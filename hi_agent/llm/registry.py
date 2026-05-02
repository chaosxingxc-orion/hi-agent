"""Model registry: models register with capability tags, not hardcoded.

LLM Gateways register their models with metadata (tier, cost, speed,
context_window, capabilities). The registry is the single source of
truth for what models are available and what they can do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ModelTier:
    """Model capability tiers."""

    STRONG = "strong"  # Complex reasoning, planning, creative work
    MEDIUM = "medium"  # General tasks, code generation
    LIGHT = "light"  # Simple tasks, formatting, checking


# W31 T-24' decision: platform model registry; tenant-agnostic.
# scope: process-internal
@dataclass
class RegisteredModel:
    """A model registered with the gateway."""

    model_id: str  # e.g. "claude-opus-4", "gpt-4o-mini"
    provider: str = ""  # e.g. "anthropic", "openai"
    tier: str = ModelTier.MEDIUM  # strong/medium/light
    cost_input_per_mtok: float = 0.0
    cost_output_per_mtok: float = 0.0
    cost_cache_read_per_mtok: float = 0.0
    cost_cache_write_per_mtok: float = 0.0
    speed: str = "standard"  # fast/standard/slow
    context_window: int = 128_000
    max_output_tokens: int = 8_192
    capabilities: list[str] = field(default_factory=list)
    is_available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def estimated_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost for a given token count."""
        return (input_tokens / 1_000_000) * self.cost_input_per_mtok + (
            output_tokens / 1_000_000
        ) * self.cost_output_per_mtok


class ModelRegistry:
    """Central registry for all available models.

    Models are registered by LLM Gateways, not hardcoded in config.
    Supports querying by tier, capability, cost, provider.
    """

    def __init__(self) -> None:
        """Initialize ModelRegistry."""
        self._models: dict[str, RegisteredModel] = {}

    def register(self, model: RegisteredModel) -> None:
        """Register a model (gateway calls this on startup)."""
        self._models[model.model_id] = model

    def unregister(self, model_id: str) -> None:
        """Remove a model from the registry."""
        self._models.pop(model_id, None)

    def get(self, model_id: str) -> RegisteredModel | None:
        """Get a model by its ID, or None if not found."""
        return self._models.get(model_id)

    def list_all(self) -> list[RegisteredModel]:
        """Get all registered models."""
        return list(self._models.values())

    def list_by_tier(self, tier: str) -> list[RegisteredModel]:
        """Get all models in a tier, sorted by cost (cheapest first)."""
        models = [m for m in self._models.values() if m.tier == tier]
        models.sort(key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok)
        return models

    def list_by_capability(self, capability: str) -> list[RegisteredModel]:
        """Get models with a specific capability."""
        return [m for m in self._models.values() if capability in m.capabilities]

    def list_available(self) -> list[RegisteredModel]:
        """Get all currently available models."""
        return [m for m in self._models.values() if m.is_available]

    def cheapest_in_tier(self, tier: str) -> RegisteredModel | None:
        """Get the cheapest available model in a tier."""
        candidates = [m for m in self._models.values() if m.tier == tier and m.is_available]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
        )

    def get_or_cheapest(self, model_id: str, fallback_tier: str = "medium") -> RegisteredModel:
        """Get specific model, or cheapest in fallback_tier if not found.

        Raises:
            KeyError: If neither the model nor any model in the fallback tier
                      is available.
        """
        model = self.get(model_id)
        if model is not None and model.is_available:
            return model
        fallback = self.cheapest_in_tier(fallback_tier)
        if fallback is not None:
            return fallback
        # Try any available model
        available = self.list_available()
        if available:
            return min(
                available,
                key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
            )
        raise KeyError(f"Model {model_id!r} not found and no models in tier {fallback_tier!r}")

    def register_defaults(self) -> None:
        """Register well-known models with standard pricing.

        Called at startup. Users can override via register().
        """
        defaults = [
            # Anthropic
            RegisteredModel(
                model_id="claude-opus-4-6",
                provider="anthropic",
                tier=ModelTier.STRONG,
                cost_input_per_mtok=15.0,
                cost_output_per_mtok=75.0,
                cost_cache_read_per_mtok=1.5,
                cost_cache_write_per_mtok=18.75,
                speed="slow",
                context_window=200_000,
                max_output_tokens=32_768,
                capabilities=["reasoning", "code", "vision", "tool_use"],
            ),
            RegisteredModel(
                model_id="claude-sonnet-4-6",
                provider="anthropic",
                tier=ModelTier.MEDIUM,
                cost_input_per_mtok=3.0,
                cost_output_per_mtok=15.0,
                cost_cache_read_per_mtok=0.3,
                cost_cache_write_per_mtok=3.75,
                speed="standard",
                context_window=200_000,
                max_output_tokens=16_384,
                capabilities=["reasoning", "code", "vision", "tool_use"],
            ),
            RegisteredModel(
                model_id="claude-haiku-4-5-20251001",
                provider="anthropic",
                tier=ModelTier.LIGHT,
                cost_input_per_mtok=0.8,
                cost_output_per_mtok=4.0,
                cost_cache_read_per_mtok=0.08,
                cost_cache_write_per_mtok=1.0,
                speed="fast",
                context_window=200_000,
                max_output_tokens=8_192,
                capabilities=["code", "tool_use"],
            ),
            # OpenAI
            RegisteredModel(
                model_id="gpt-4o",
                provider="openai",
                tier=ModelTier.MEDIUM,
                cost_input_per_mtok=2.5,
                cost_output_per_mtok=10.0,
                speed="standard",
                context_window=128_000,
                max_output_tokens=16_384,
                capabilities=["reasoning", "code", "vision", "tool_use"],
            ),
            RegisteredModel(
                model_id="gpt-4o-mini",
                provider="openai",
                tier=ModelTier.LIGHT,
                cost_input_per_mtok=0.15,
                cost_output_per_mtok=0.6,
                speed="fast",
                context_window=128_000,
                max_output_tokens=16_384,
                capabilities=["code", "tool_use"],
            ),
            RegisteredModel(
                model_id="gpt-4.1",
                provider="openai",
                tier=ModelTier.MEDIUM,
                cost_input_per_mtok=2.0,
                cost_output_per_mtok=8.0,
                speed="standard",
                context_window=1_000_000,
                max_output_tokens=32_768,
                capabilities=["reasoning", "code", "tool_use"],
            ),
            RegisteredModel(
                model_id="gpt-4.1-mini",
                provider="openai",
                tier=ModelTier.LIGHT,
                cost_input_per_mtok=0.4,
                cost_output_per_mtok=1.6,
                speed="fast",
                context_window=1_000_000,
                max_output_tokens=32_768,
                capabilities=["code", "tool_use"],
            ),
            RegisteredModel(
                model_id="gpt-4.1-nano",
                provider="openai",
                tier=ModelTier.LIGHT,
                cost_input_per_mtok=0.1,
                cost_output_per_mtok=0.4,
                speed="fast",
                context_window=1_000_000,
                max_output_tokens=32_768,
                capabilities=["code"],
            ),
        ]
        for model in defaults:
            self.register(model)
