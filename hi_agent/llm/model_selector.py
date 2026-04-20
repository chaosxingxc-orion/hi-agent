"""Model selector: integrates registry + tier router + cost tracking.

Provides the main entry point for all model selection decisions.
Tracks per-run cost and enforces budget limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hi_agent.llm.registry import ModelRegistry, ModelTier, RegisteredModel
from hi_agent.llm.tier_router import _TIER_ORDER, TierRouter, _tier_index


@dataclass
class SelectionResult:
    """Result of a model selection decision."""

    model: RegisteredModel
    tier_requested: str
    tier_actual: str  # may differ if downgraded/upgraded
    downgraded: bool = False
    upgraded: bool = False
    estimated_cost_usd: float = 0.0
    reason: str = ""  # why this model was chosen


class ModelSelector:
    """Cost-aware model selection with budget enforcement."""

    def __init__(
        self,
        registry: ModelRegistry,
        tier_router: TierRouter,
        budget_usd: float = 10.0,
    ) -> None:
        """Initialize ModelSelector."""
        self._registry = registry
        self._router = tier_router
        self._budget = budget_usd
        self._spent: float = 0.0
        self._selections: list[SelectionResult] = []
        self._upgrade_history: dict[str, int] = {}

    def select(
        self,
        purpose: str,
        complexity: str = "moderate",
        input_tokens: int = 1000,
        output_tokens: int = 500,
        required_capabilities: list[str] | None = None,
    ) -> SelectionResult:
        """Select model with full cost awareness.

        1. Check remaining budget
        2. Route via TierRouter
        3. If cost exceeds remaining budget, downgrade
        4. Record selection
        """
        remaining = self.remaining_budget
        requested_tier = self._router.get_tier_for_purpose(purpose)

        # Select with budget awareness
        model, actual_tier = self._router.select_with_fallback(
            purpose,
            complexity,
            required_capabilities=required_capabilities,
            budget_remaining_usd=remaining,
        )

        estimated = model.estimated_cost(input_tokens, output_tokens)

        # If estimated cost exceeds remaining budget, try to downgrade
        if estimated > remaining and remaining > 0:
            idx = _tier_index(actual_tier)
            while idx > 0 and estimated > remaining:
                idx -= 1
                downgrade_tier = _TIER_ORDER[idx]
                cheaper = self._registry.cheapest_in_tier(downgrade_tier)
                if cheaper is not None:
                    model = cheaper
                    actual_tier = downgrade_tier
                    estimated = model.estimated_cost(input_tokens, output_tokens)

        ri = _tier_index(requested_tier)
        ai = _tier_index(actual_tier)

        result = SelectionResult(
            model=model,
            tier_requested=requested_tier,
            tier_actual=actual_tier,
            downgraded=ai < ri,
            upgraded=ai > ri,
            estimated_cost_usd=estimated,
            reason=self._build_reason(requested_tier, actual_tier, remaining),
        )
        self._selections.append(result)
        return result

    def _build_reason(self, requested: str, actual: str, remaining: float) -> str:
        """Build a human-readable reason for the selection."""
        if requested == actual:
            return f"Selected {actual} tier as configured"
        ri = _tier_index(requested)
        ai = _tier_index(actual)
        if ai < ri:
            return f"Downgraded from {requested} to {actual} (budget remaining: ${remaining:.4f})"
        return f"Upgraded from {requested} to {actual} based on complexity"

    def record_actual_usage(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> float:
        """Record actual token usage. Returns actual cost USD."""
        model = self._registry.get(model_id)
        if model is None:
            return 0.0
        cost = model.estimated_cost(input_tokens, output_tokens)
        # Add cache costs
        cost += (cache_read / 1_000_000) * model.cost_cache_read_per_mtok
        cost += (cache_write / 1_000_000) * model.cost_cache_write_per_mtok
        self._spent += cost
        return cost

    def request_upgrade(self, purpose: str, reason: str = "quality") -> SelectionResult | None:
        """Request tier upgrade (e.g., light model output was poor).

        Returns new selection or None if already at strong.
        """
        current_tier = self._router.get_tier_for_purpose(purpose)
        idx = _tier_index(current_tier)
        if idx >= len(_TIER_ORDER) - 1:
            return None  # already at strong

        upgrade_count = self._upgrade_history.get(purpose, 0)
        self._upgrade_history[purpose] = upgrade_count + 1

        next_tier = _TIER_ORDER[idx + 1]
        model = self._registry.cheapest_in_tier(next_tier)
        if model is None:
            # Try strong if medium failed
            if next_tier != ModelTier.STRONG:
                model = self._registry.cheapest_in_tier(ModelTier.STRONG)
            if model is None:
                return None

        result = SelectionResult(
            model=model,
            tier_requested=current_tier,
            tier_actual=model.tier,
            upgraded=True,
            reason=f"Upgraded due to {reason} (upgrade #{upgrade_count + 1})",
        )
        self._selections.append(result)
        return result

    @property
    def remaining_budget(self) -> float:
        """Remaining budget in USD."""
        return max(0.0, self._budget - self._spent)

    @property
    def total_spent(self) -> float:
        """Total spent in USD."""
        return self._spent

    def get_cost_breakdown(self) -> dict[str, Any]:
        """Cost breakdown by purpose and tier."""
        by_purpose: dict[str, float] = {}
        by_tier: dict[str, float] = {}
        for sel in self._selections:
            purpose_key = sel.reason.split()[0] if sel.reason else "unknown"
            by_purpose[purpose_key] = by_purpose.get(purpose_key, 0.0) + sel.estimated_cost_usd
            by_tier[sel.tier_actual] = by_tier.get(sel.tier_actual, 0.0) + sel.estimated_cost_usd
        return {
            "total_spent": self._spent,
            "remaining_budget": self.remaining_budget,
            "total_selections": len(self._selections),
            "by_tier": by_tier,
            "upgrades": dict(self._upgrade_history),
        }

    def get_selection_history(self) -> list[SelectionResult]:
        """Get all selection results."""
        return list(self._selections)
