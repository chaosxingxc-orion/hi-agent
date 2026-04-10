"""Budget-aware model tier selection for graph nodes.

Thresholds (remaining budget):
  > 70%  → use requested tier as-is
  30-70% → downgrade strong→medium
  10-30% → force light; skip optional nodes
  < 10%  → skip optional; force light for required
"""
from __future__ import annotations

from dataclasses import dataclass

TIER_ORDER = ["light", "medium", "strong"]


@dataclass(frozen=True)
class TierDecision:
    """TierDecision class."""
    tier: str
    skipped: bool = False


class BudgetGuard:
    """Tracks token budget and decides tier/skip per node."""

    def __init__(self, total_budget_tokens: int) -> None:
        """Initialize BudgetGuard."""
        self._total = total_budget_tokens
        self._consumed = 0

    def consume(self, tokens: int) -> None:
        """Run consume."""
        self._consumed += tokens

    @property
    def remaining_fraction(self) -> float:
        """Return remaining_fraction."""
        return max(0.0, 1.0 - self._consumed / self._total)

    def can_afford(self, estimated_cost: int) -> bool:
        """Run can_afford."""
        return self._consumed + estimated_cost <= self._total

    def decide_tier(
        self,
        requested_tier: str,
        estimated_cost: int = 0,
        is_optional: bool = False,
    ) -> TierDecision:
        """Run decide_tier."""
        frac = self.remaining_fraction

        if frac < 0.10:
            # Critical: skip optional, force light for required
            if is_optional:
                return TierDecision(tier=requested_tier, skipped=True)
            return TierDecision(tier="light")

        if frac < 0.30:
            # Very low: skip optional, force light for required
            if is_optional:
                return TierDecision(tier=requested_tier, skipped=True)
            return TierDecision(tier="light")

        if frac < 0.70:
            # Low: downgrade one level
            tier = _downgrade(requested_tier)
            return TierDecision(tier=tier)

        return TierDecision(tier=requested_tier)


def _downgrade(tier: str) -> str:
    """Run _downgrade."""
    idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 1
    return TIER_ORDER[max(0, idx - 1)]
