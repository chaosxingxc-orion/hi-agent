"""Unit tests: spine field enforcement on evolve dataclasses.

Covers RunPostmortem, CalibrationSignal, and ProjectPostmortem under
dev (permissive) and research (fail-closed) postures per Rule 11.
"""

from __future__ import annotations

import pytest
from hi_agent.evolve.contracts import CalibrationSignal, ProjectPostmortem, RunPostmortem


def _make_run_postmortem(**overrides) -> RunPostmortem:
    kwargs: dict = {
        "run_id": "run-001",
        "task_id": "task-001",
        "task_family": "quick_task",
        "outcome": "completed",
        "stages_completed": ["stage1"],
        "stages_failed": [],
        "branches_explored": 1,
        "branches_pruned": 0,
        "total_actions": 3,
        "failure_codes": [],
        "duration_seconds": 1.5,
    }
    kwargs.update(overrides)
    return RunPostmortem(**kwargs)


def _make_calibration_signal(**overrides) -> CalibrationSignal:
    kwargs: dict = {
        "project_id": "proj-1",
        "run_id": "run-001",
        "model": "gpt-4o",
        "tier": "standard",
    }
    kwargs.update(overrides)
    return CalibrationSignal(**kwargs)


def _make_project_postmortem(**overrides) -> ProjectPostmortem:
    kwargs: dict = {
        "project_id": "proj-1",
        "run_ids": ["run-001"],
    }
    kwargs.update(overrides)
    return ProjectPostmortem(**kwargs)


# ---------------------------------------------------------------------------
# RunPostmortem
# ---------------------------------------------------------------------------


def test_research_rejects_empty_tenant_runpostmortem(monkeypatch: pytest.MonkeyPatch) -> None:
    """RunPostmortem with tenant_id='' must raise ValueError under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    with pytest.raises(ValueError, match="tenant_id"):
        _make_run_postmortem(tenant_id="")


def test_dev_allows_empty_tenant_runpostmortem(monkeypatch: pytest.MonkeyPatch) -> None:
    """RunPostmortem with tenant_id='' must succeed under dev posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    pm = _make_run_postmortem(tenant_id="")
    assert pm.tenant_id == ""


def test_research_allows_nonempty_tenant_runpostmortem(monkeypatch: pytest.MonkeyPatch) -> None:
    """RunPostmortem with valid tenant_id must succeed under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    pm = _make_run_postmortem(tenant_id="tenant-abc")
    assert pm.tenant_id == "tenant-abc"


# ---------------------------------------------------------------------------
# CalibrationSignal
# ---------------------------------------------------------------------------


def test_research_rejects_empty_tenant_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    """CalibrationSignal with tenant_id='' must raise ValueError under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    with pytest.raises(ValueError, match="tenant_id"):
        _make_calibration_signal(tenant_id="")


def test_dev_allows_empty_tenant_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    """CalibrationSignal with tenant_id='' must succeed under dev posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    sig = _make_calibration_signal(tenant_id="")
    assert sig.tenant_id == ""


def test_research_allows_nonempty_tenant_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    """CalibrationSignal with valid tenant_id must succeed under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    sig = _make_calibration_signal(tenant_id="tenant-abc")
    assert sig.tenant_id == "tenant-abc"


# ---------------------------------------------------------------------------
# ProjectPostmortem
# ---------------------------------------------------------------------------


def test_research_rejects_empty_tenant_project_postmortem(monkeypatch: pytest.MonkeyPatch) -> None:
    """ProjectPostmortem with tenant_id='' must raise ValueError under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    with pytest.raises(ValueError, match="tenant_id"):
        _make_project_postmortem(tenant_id="")


def test_dev_allows_empty_tenant_project_postmortem(monkeypatch: pytest.MonkeyPatch) -> None:
    """ProjectPostmortem with tenant_id='' must succeed under dev posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    pm = _make_project_postmortem(tenant_id="")
    assert pm.tenant_id == ""


def test_research_allows_nonempty_tenant_project_postmortem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ProjectPostmortem with valid tenant_id must succeed under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    pm = _make_project_postmortem(tenant_id="tenant-abc")
    assert pm.tenant_id == "tenant-abc"
