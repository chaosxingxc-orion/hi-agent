from hi_agent.task_mgmt.budget_guard import BudgetGuard, TierDecision


def test_full_budget_returns_original_tier():
    guard = BudgetGuard(total_budget_tokens=10_000)
    guard.consume(1_000)  # 10% used, 90% remaining
    decision = guard.decide_tier(requested_tier="strong", estimated_cost=500)
    assert decision == TierDecision(tier="strong", skipped=False)


def test_low_budget_downgrades_strong_to_medium():
    guard = BudgetGuard(total_budget_tokens=10_000)
    guard.consume(6_500)  # 65% used, 35% remaining
    decision = guard.decide_tier(requested_tier="strong", estimated_cost=500)
    assert decision.tier == "medium"
    assert not decision.skipped


def test_very_low_budget_skips_optional_node():
    guard = BudgetGuard(total_budget_tokens=10_000)
    guard.consume(9_500)  # 95% used, 5% remaining
    decision = guard.decide_tier(requested_tier="medium", estimated_cost=500, is_optional=True)
    assert decision.skipped


def test_very_low_budget_forces_light_for_required_node():
    guard = BudgetGuard(total_budget_tokens=10_000)
    guard.consume(9_500)
    decision = guard.decide_tier(requested_tier="strong", estimated_cost=500, is_optional=False)
    assert decision.tier == "light"
    assert not decision.skipped


def test_critical_budget_cancels_optional():
    guard = BudgetGuard(total_budget_tokens=10_000)
    guard.consume(9_900)  # 99% used
    decision = guard.decide_tier(requested_tier="light", estimated_cost=200, is_optional=True)
    assert decision.skipped
