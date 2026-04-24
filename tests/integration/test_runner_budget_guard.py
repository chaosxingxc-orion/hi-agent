"""Tests for BudgetGuard tier decisions and runner integration."""

from __future__ import annotations

import pytest
from hi_agent.task_mgmt.budget_guard import BudgetGuard, TierDecision


class TestBudgetGuard:
    """BudgetGuard decision logic tests."""

    def test_tier_decision_dataclass(self):
        td = TierDecision(tier="strong", skipped=False)
        assert td.tier == "strong"
        assert td.skipped is False

    def test_tier_decision_event_at_high_budget(self):
        """Above 70%: use requested tier as-is."""
        guard = BudgetGuard(total_budget_tokens=10000)
        decision = guard.decide_tier("strong")
        assert decision.tier == "strong"
        assert decision.skipped is False

    def test_downgrade_at_medium_budget(self):
        """Between 30-70%: downgrade strong -> medium."""
        guard = BudgetGuard(total_budget_tokens=10000)
        guard.consume(5000)  # 50% remaining
        decision = guard.decide_tier("strong")
        assert decision.tier == "medium"
        assert decision.skipped is False

    def test_downgrade_medium_to_light(self):
        """Between 30-70%: downgrade medium -> light."""
        guard = BudgetGuard(total_budget_tokens=10000)
        guard.consume(5000)
        decision = guard.decide_tier("medium")
        assert decision.tier == "light"
        assert decision.skipped is False

    def test_light_stays_light_at_medium_budget(self):
        """Light can't be downgraded further."""
        guard = BudgetGuard(total_budget_tokens=10000)
        guard.consume(5000)
        decision = guard.decide_tier("light")
        assert decision.tier == "light"

    def test_optional_stage_skip_at_low_budget(self):
        """Below 30%: skip optional stages."""
        guard = BudgetGuard(total_budget_tokens=10000)
        guard.consume(8000)  # 20% remaining
        decision = guard.decide_tier("strong", is_optional=True)
        assert decision.skipped is True

    def test_required_stage_not_skipped_at_low_budget(self):
        """Below 30%: required stages forced to light, not skipped."""
        guard = BudgetGuard(total_budget_tokens=10000)
        guard.consume(8000)
        decision = guard.decide_tier("strong", is_optional=False)
        assert decision.tier == "light"
        assert decision.skipped is False

    def test_critical_budget_optional_skip(self):
        """Below 10%: optional stages skipped."""
        guard = BudgetGuard(total_budget_tokens=10000)
        guard.consume(9500)  # 5% remaining
        decision = guard.decide_tier("strong", is_optional=True)
        assert decision.skipped is True

    def test_critical_budget_required_forced_light(self):
        """Below 10%: required stages forced to light."""
        guard = BudgetGuard(total_budget_tokens=10000)
        guard.consume(9500)
        decision = guard.decide_tier("strong", is_optional=False)
        assert decision.tier == "light"
        assert decision.skipped is False

    def test_remaining_fraction(self):
        guard = BudgetGuard(total_budget_tokens=10000)
        assert guard.remaining_fraction == 1.0
        guard.consume(2500)
        assert guard.remaining_fraction == pytest.approx(0.75)
        guard.consume(7500)
        assert guard.remaining_fraction == pytest.approx(0.0)

    def test_can_afford(self):
        guard = BudgetGuard(total_budget_tokens=10000)
        assert guard.can_afford(5000) is True
        guard.consume(6000)
        assert guard.can_afford(5000) is False
        assert guard.can_afford(4000) is True

    def test_backward_compat_none(self):
        """BudgetGuard with None-like behavior: no guard means no constraints."""
        guard = BudgetGuard(total_budget_tokens=10000)
        decision = guard.decide_tier("strong", estimated_cost=0, is_optional=False)
        assert decision.tier == "strong"
        assert decision.skipped is False
