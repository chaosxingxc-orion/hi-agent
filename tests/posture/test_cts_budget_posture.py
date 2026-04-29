"""Posture-matrix coverage for cts_budget contracts (AX-B B5).

Covers:
  hi_agent/contracts/cts_budget.py — CTSBudget, CTSBudgetTemplate,
      CTSExplorationBudget

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture


# ---------------------------------------------------------------------------
# CTSBudget
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_cts_budget_instantiates_under_posture(monkeypatch, posture_name):
    """CTSBudget must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.cts_budget import CTSBudget

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    budget = CTSBudget(l0_raw_tokens=1000, l1_summary_tokens=500, l2_index_tokens=250)
    assert budget.l0_raw_tokens == 1000
    assert budget.l1_summary_tokens == 500
    assert budget.l2_index_tokens == 250
    assert budget.total_tokens == 1750


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_cts_budget_requires_all_fields(monkeypatch, posture_name):
    """CTSBudget without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.cts_budget import CTSBudget

    with pytest.raises(TypeError):
        CTSBudget()  # missing l0, l1, l2


# ---------------------------------------------------------------------------
# CTSBudgetTemplate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_cts_budget_template_instantiates_under_posture(monkeypatch, posture_name):
    """CTSBudgetTemplate must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.cts_budget import CTSBudget, CTSBudgetTemplate

    budget = CTSBudget(l0_raw_tokens=2000, l1_summary_tokens=1000, l2_index_tokens=500)
    template = CTSBudgetTemplate(task_family="research_task", budget=budget)
    assert template.task_family == "research_task"
    assert template.budget.total_tokens == 3500


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_cts_budget_template_requires_fields(monkeypatch, posture_name):
    """CTSBudgetTemplate without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.cts_budget import CTSBudgetTemplate

    with pytest.raises(TypeError):
        CTSBudgetTemplate()  # missing task_family, budget


# ---------------------------------------------------------------------------
# CTSExplorationBudget
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_cts_exploration_budget_instantiates_under_posture(monkeypatch, posture_name):
    """CTSExplorationBudget must be instantiable with defaults under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.cts_budget import CTSExplorationBudget

    budget = CTSExplorationBudget()
    assert budget.max_active_branches_per_stage == 3
    assert budget.max_total_branches_per_run == 20
    assert budget.max_route_compare_calls_per_cycle == 5
    assert budget.max_route_compare_token_budget == 4096
    assert budget.max_exploration_wall_clock_budget == 1800
