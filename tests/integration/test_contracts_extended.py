"""Tests for extended contracts."""

from hi_agent.contracts import CTSBudget, TaskFamilyConfig


def test_cts_budget_total_tokens() -> None:
    """Budget should expose token sum."""
    budget = CTSBudget(l0_raw_tokens=100, l1_summary_tokens=200, l2_index_tokens=50)
    assert budget.total_tokens == 350


def test_task_family_config_defaults() -> None:
    """Task family config should keep defaults and values."""
    budget = CTSBudget(l0_raw_tokens=1, l1_summary_tokens=2, l2_index_tokens=3)
    cfg = TaskFamilyConfig(task_family="quick_task", max_stage_retries=1, default_budget=budget)
    assert cfg.enable_dead_end_recovery is True
