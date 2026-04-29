"""Posture-matrix tests for miscellaneous module callsites (Rule 11).

Covers:
  hi_agent/cli_commands/extensions.py — _load_posture
  hi_agent/server/recovery.py         — fire_if_needed, decide_recovery_action
  hi_agent/server/routes_artifacts.py — _belongs_to_tenant (inline function)
  hi_agent/evolve/contracts.py        — __post_init__ (all four dataclasses)

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to the corresponding callsite function names.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# cli_commands.extensions._load_posture
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test__load_posture(monkeypatch, posture_name):
    """_load_posture: when no explicit posture arg, resolves from HI_AGENT_POSTURE."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.cli_commands.extensions import _load_posture
    result = _load_posture(None)
    assert result == Posture(posture_name)


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test__load_posture_explicit_arg(monkeypatch, posture_name):
    """_load_posture: explicit arg takes precedence over env."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    from hi_agent.cli_commands.extensions import _load_posture
    result = _load_posture(posture_name)
    assert result == Posture(posture_name)


# ---------------------------------------------------------------------------
# server.recovery.fire_if_needed (RecoveryAlarm.fire_if_needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,reenqueue_disabled,should_alarm", [
    ("dev", True, False),       # dev: no alarm even when reenqueue disabled
    ("research", True, True),   # strict + disabled = alarm
    ("prod", True, True),
    ("research", False, False),  # strict but reenqueue enabled = no alarm
])
def test_fire_if_needed(monkeypatch, posture_name, reenqueue_disabled, should_alarm, caplog):
    """Posture-matrix test for RecoveryAlarm.fire_if_needed.

    Alarm fires only when posture is strict AND reenqueue is disabled.
    """
    import logging
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    if reenqueue_disabled:
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
    else:
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "1")

    from hi_agent.server.recovery import RecoveryAlarm

    with caplog.at_level(logging.WARNING):
        RecoveryAlarm.fire_if_needed("r-1", "t-1", Posture(posture_name))

    alarm_fired = any("reenqueue" in r.message.lower() for r in caplog.records)
    assert alarm_fired is should_alarm


# ---------------------------------------------------------------------------
# server.recovery.decide_recovery_action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_requeue", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_decide_recovery_action(monkeypatch, posture_name, expect_requeue):
    """Posture-matrix test for decide_recovery_action.

    dev: LEASE_EXPIRED → no requeue (warn only).
    research/prod: LEASE_EXPIRED → REQUEUED.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.server.recovery import RecoveryState, decide_recovery_action

    decision = decide_recovery_action(
        run_id="r-1",
        tenant_id="t-1",
        current_state=RecoveryState.LEASE_EXPIRED,
        posture=Posture(posture_name),
    )
    assert decision.should_requeue is expect_requeue


# ---------------------------------------------------------------------------
# evolve/contracts __post_init__ (all four dataclasses share this function name)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test___post_init__(monkeypatch, posture_name, empty_raises):
    """Posture-matrix test for evolve contracts __post_init__.

    All four dataclasses (RunRetrospective, CalibrationSignal,
    ProjectRetrospective, EvolutionTrial) enforce tenant_id in strict posture.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.evolve.contracts import (
        CalibrationSignal,
        EvolutionTrial,
        ProjectRetrospective,
        RunRetrospective,
    )

    # RunRetrospective
    rr = RunRetrospective(
        run_id="r1", task_id="t1", task_family="test", outcome="done",
        stages_completed=[], stages_failed=[], branches_explored=0,
        branches_pruned=0, total_actions=0, failure_codes=[],
        duration_seconds=1.0, project_id="p1", tenant_id="t-abc",
    )
    assert rr.tenant_id == "t-abc"

    if empty_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            RunRetrospective(
                run_id="r1", task_id="t1", task_family="test", outcome="done",
                stages_completed=[], stages_failed=[], branches_explored=0,
                branches_pruned=0, total_actions=0, failure_codes=[],
                duration_seconds=1.0, project_id="p1", tenant_id="",
            )

        with pytest.raises(ValueError, match="tenant_id"):
            CalibrationSignal(project_id="p1", run_id="r1", model="gpt", tier="t1", tenant_id="")

        with pytest.raises(ValueError, match="tenant_id"):
            ProjectRetrospective(project_id="p1", run_ids=["r1"], tenant_id="")

        with pytest.raises(ValueError, match="tenant_id"):
            EvolutionTrial(
                experiment_id="e1", capability_name="cap", baseline_version="1.0",
                candidate_version="2.0", metric_name="quality",
                started_at="2026-01-01T00:00:00Z", status="active", tenant_id="",
            )
    else:
        cs = CalibrationSignal(project_id="p1", run_id="r1", model="gpt", tier="t1", tenant_id="")
        assert cs.tenant_id == ""
        pr = ProjectRetrospective(project_id="p1", run_ids=["r1"], tenant_id="")
        assert pr.tenant_id == ""
        et = EvolutionTrial(
            experiment_id="e1", capability_name="cap", baseline_version="1.0",
            candidate_version="2.0", metric_name="quality",
            started_at="2026-01-01T00:00:00Z", status="active", tenant_id="",
        )
        assert et.tenant_id == ""
