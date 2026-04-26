"""Test TeamRun.lead_run_id deprecation alias for pi_run_id."""
from __future__ import annotations

import warnings

import pytest
from hi_agent.contracts.team_runtime import TeamRun


def _make_base(**kwargs) -> TeamRun:
    defaults = {
        "team_id": "team-1",
        "project_id": "proj-1",
        "member_runs": (),
        "created_at": "2026-04-27T00:00:00",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "session_id": "sess-1",
    }
    defaults.update(kwargs)
    return TeamRun(**defaults)


def test_lead_run_id_only_no_warning():
    """lead_run_id= alone works without DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tr = _make_base(lead_run_id="run-leader")
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not dep_warns
    assert tr.lead_run_id == "run-leader"


def test_pi_run_id_only_warns_and_copies():
    """pi_run_id= alone emits DeprecationWarning and copies value to lead_run_id."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tr = _make_base(pi_run_id="run-pi")
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warns, "Expected DeprecationWarning"
    assert "lead_run_id" in str(dep_warns[0].message)
    assert tr.lead_run_id == "run-pi"


def test_both_set_same_value_ok():
    """Setting both to the same value is allowed (idempotent)."""
    tr = _make_base(pi_run_id="run-x", lead_run_id="run-x")
    assert tr.lead_run_id == "run-x"


def test_both_set_different_raises():
    """Setting pi_run_id and lead_run_id to different values raises ValueError."""
    with pytest.raises(ValueError, match="differ"):
        _make_base(pi_run_id="run-a", lead_run_id="run-b")
