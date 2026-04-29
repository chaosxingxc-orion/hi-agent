"""Posture-matrix coverage for memory contracts (AX-B B5).

Covers:
  hi_agent/contracts/memory.py — StageSummary, RunIndex

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture


# ---------------------------------------------------------------------------
# StageSummary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_summary_instantiates_under_posture(monkeypatch, posture_name):
    """StageSummary must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.memory import StageSummary

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    summary = StageSummary(stage_id="s1", stage_name="research")
    assert summary.stage_id == "s1"
    assert summary.stage_name == "research"
    assert summary.findings == []
    assert summary.decisions == []
    assert summary.outcome == "active"
    assert summary.artifact_ids == []


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_summary_requires_stage_id_and_name(monkeypatch, posture_name):
    """StageSummary without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.memory import StageSummary

    with pytest.raises(TypeError):
        StageSummary()  # missing stage_id, stage_name


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_summary_with_findings_under_posture(monkeypatch, posture_name):
    """StageSummary with findings and decisions is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.memory import StageSummary

    summary = StageSummary(
        stage_id="s1",
        stage_name="research",
        findings=["finding-1", "finding-2"],
        decisions=["decision-1"],
        outcome="completed",
    )
    assert len(summary.findings) == 2
    assert summary.outcome == "completed"


# ---------------------------------------------------------------------------
# RunIndex
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_run_index_instantiates_under_posture(monkeypatch, posture_name):
    """RunIndex must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.memory import RunIndex

    idx = RunIndex(run_id="run-123")
    assert idx.run_id == "run-123"
    assert idx.task_goal_summary == ""
    assert idx.stages_status == []
    assert idx.current_stage == ""
    assert idx.key_decisions == []


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_run_index_requires_run_id(monkeypatch, posture_name):
    """RunIndex without run_id raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.memory import RunIndex

    with pytest.raises(TypeError):
        RunIndex()  # missing run_id
