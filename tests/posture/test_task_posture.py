"""Posture-matrix coverage for task contracts (AX-B B5).

Covers:
  hi_agent/contracts/task.py — TaskBudget, TaskContract

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture


# ---------------------------------------------------------------------------
# TaskBudget
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_task_budget_instantiates_under_posture(monkeypatch, posture_name):
    """TaskBudget must be instantiable with defaults under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.task import TaskBudget

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    budget = TaskBudget()
    assert budget.max_llm_calls == 100
    assert budget.max_wall_clock_seconds == 3600
    assert budget.max_actions == 50
    assert budget.max_cost_cents == 1000


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_task_budget_custom_values_under_posture(monkeypatch, posture_name):
    """TaskBudget with custom values is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.task import TaskBudget

    budget = TaskBudget(max_llm_calls=50, max_wall_clock_seconds=1800)
    assert budget.max_llm_calls == 50
    assert budget.max_wall_clock_seconds == 1800


# ---------------------------------------------------------------------------
# TaskContract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_task_contract_instantiates_under_posture(monkeypatch, posture_name):
    """TaskContract must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.task import TaskContract

    contract = TaskContract(
        task_id="t1",
        goal="Summarize the document",
        project_id="proj-abc",
    )
    assert contract.task_id == "t1"
    assert contract.goal == "Summarize the document"
    assert contract.project_id == "proj-abc"
    assert contract.task_family == "quick_task"
    assert contract.risk_level == "low"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_task_contract_requires_task_id_and_goal(monkeypatch, posture_name):
    """TaskContract without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.task import TaskContract

    with pytest.raises(TypeError):
        TaskContract()  # missing task_id, goal


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_task_contract_empty_project_id_warns_under_posture(
    monkeypatch, posture_name, caplog
):
    """TaskContract with empty project_id emits a warning under all postures."""
    import logging

    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.task import TaskContract

    with caplog.at_level(logging.WARNING):
        contract = TaskContract(task_id="t1", goal="test")
    assert contract.project_id == ""
    assert any("project_id" in r.message for r in caplog.records)


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_task_contract_from_dict_under_posture(monkeypatch, posture_name):
    """TaskContract.from_dict constructs from payload dict under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.task import TaskContract

    payload = {
        "task_id": "t2",
        "goal": "Analyze data",
        "project_id": "p1",
        "task_family": "research_task",
    }
    contract = TaskContract.from_dict(payload)
    assert contract.task_id == "t2"
    assert contract.task_family == "research_task"
    assert contract.project_id == "p1"
