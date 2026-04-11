# tests/test_budget_guard_config.py
from hi_agent.config.trace_config import TraceConfig
from hi_agent.task_mgmt.budget_guard import BudgetGuard, TierDecision

def test_budget_guard_from_config_thresholds():
    cfg = TraceConfig(
        budget_guard_low_threshold=0.05,
        budget_guard_mid_threshold=0.20,
        budget_guard_high_threshold=0.60,
    )
    guard = BudgetGuard.from_config(cfg, total_budget_tokens=1000)
    # consume 45% → remaining 55%, below high (60%) → should downgrade
    guard.consume(450)
    decision = guard.decide_tier("strong")
    assert decision.tier == "medium"

def test_budget_guard_default_thresholds_match_config_defaults():
    cfg = TraceConfig()
    guard = BudgetGuard.from_config(cfg, total_budget_tokens=1000)
    # At 75% remaining (consumed 250/1000) → above high (0.70) → no downgrade
    guard.consume(250)
    decision = guard.decide_tier("strong")
    assert decision.tier == "strong"
