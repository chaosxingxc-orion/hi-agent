"""Posture-matrix coverage for directives contracts (AX-B B5).

Covers:
  hi_agent/contracts/directives.py — StageDirective

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# StageDirective
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_directive_instantiates_under_posture(monkeypatch, posture_name):
    """StageDirective must be instantiable with defaults under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.directives import StageDirective

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    directive = StageDirective()
    assert directive.action == "continue"
    assert directive.target_stage_id == ""
    assert directive.new_stage_specs == []
    assert directive.reason == ""


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_directive_continue_action_under_posture(monkeypatch, posture_name):
    """StageDirective with continue action is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.directives import StageDirective

    directive = StageDirective(action="continue", reason="no change needed")
    assert directive.action == "continue"
    assert directive.reason == "no change needed"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_directive_skip_action_under_posture(monkeypatch, posture_name):
    """StageDirective with skip action is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.directives import StageDirective

    directive = StageDirective(action="skip", target_stage_id="stage-3")
    assert directive.action == "skip"
    assert directive.target_stage_id == "stage-3"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_directive_insert_action_under_posture(monkeypatch, posture_name):
    """StageDirective with insert action carries new_stage_specs under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.directives import StageDirective

    new_specs = [{"stage_id": "new-stage", "name": "Extra Analysis"}]
    directive = StageDirective(action="insert", new_stage_specs=new_specs)
    assert directive.action == "insert"
    assert len(directive.new_stage_specs) == 1


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_directive_all_actions_under_posture(monkeypatch, posture_name):
    """StageDirective accepts all valid action values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.directives import StageDirective

    for action in ("continue", "skip", "repeat", "insert"):
        directive = StageDirective(action=action)
        assert directive.action == action
