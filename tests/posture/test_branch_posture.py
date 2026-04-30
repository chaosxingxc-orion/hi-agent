"""Posture-matrix coverage for branch contracts (AX-B B5).

Covers:
  hi_agent/contracts/branch.py — BranchState

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# BranchState
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_branch_state_importable_under_posture(monkeypatch, posture_name):
    """BranchState must be importable and have expected values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.branch import BranchState

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    assert BranchState.PROPOSED == "proposed"
    assert BranchState.ACTIVE == "active"
    assert BranchState.WAITING == "waiting"
    assert BranchState.PRUNED == "pruned"
    assert BranchState.SUCCEEDED == "succeeded"
    assert BranchState.FAILED == "failed"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_branch_state_all_members_under_posture(monkeypatch, posture_name):
    """BranchState has exactly 6 members under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.branch import BranchState

    members = list(BranchState)
    assert len(members) == 6


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_branch_state_string_comparison_under_posture(monkeypatch, posture_name):
    """BranchState members compare equal to their string values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.branch import BranchState

    # StrEnum — member == string_value must hold
    for state in BranchState:
        assert state == state.value
        assert isinstance(state, str)
