"""Posture-matrix coverage for stage contracts (AX-B B5).

Covers:
  hi_agent/contracts/stage.py — StageState

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# StageState
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_state_importable_under_posture(monkeypatch, posture_name):
    """StageState must be importable and have expected values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.stage import StageState

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    assert StageState.PENDING == "pending"
    assert StageState.ACTIVE == "active"
    assert StageState.BLOCKED == "blocked"
    assert StageState.COMPLETED == "completed"
    assert StageState.FAILED == "failed"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_state_all_members_under_posture(monkeypatch, posture_name):
    """StageState has exactly 5 members under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.stage import StageState

    members = list(StageState)
    assert len(members) == 5


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_state_string_comparison_under_posture(monkeypatch, posture_name):
    """StageState members compare equal to their string values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.stage import StageState

    for state in StageState:
        assert state == state.value
        assert isinstance(state, str)
