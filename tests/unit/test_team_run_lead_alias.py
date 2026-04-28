"""Test TeamRun.lead_run_id field (W18: pi_run_id deprecation shim removed)."""
from __future__ import annotations

import warnings

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


def test_pi_run_id_field_still_exists():
    """pi_run_id field still present for backward compat; no longer triggers DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tr = _make_base(pi_run_id="run-pi")
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    # W18: no DeprecationWarning emitted; __post_init__ shim removed
    assert not dep_warns
    assert tr.pi_run_id == "run-pi"


def test_both_lead_and_pi_run_id_set():
    """Setting both lead_run_id and pi_run_id is allowed (no cross-validation after W18)."""
    tr = _make_base(pi_run_id="run-x", lead_run_id="run-x")
    assert tr.lead_run_id == "run-x"
    assert tr.pi_run_id == "run-x"
