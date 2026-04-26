"""Integration tests: RunPostmortem spine fields are preserved through construction."""

from __future__ import annotations

import pytest
from hi_agent.evolve.contracts import RunPostmortem


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


def test_postmortem_spine_fields_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """RunPostmortem spine fields are accessible after construction under dev posture.

    Integration: real RunPostmortem dataclass; no mocks on the subject under test.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    pm = _make_run_postmortem(
        tenant_id="tenant-abc",
        user_id="user-xyz",
        session_id="sess-123",
        project_id="proj-456",
    )
    assert pm.tenant_id == "tenant-abc"
    assert pm.user_id == "user-xyz"
    assert pm.session_id == "sess-123"
    assert pm.project_id == "proj-456"
    assert pm.run_id == "run-001"


def test_postmortem_spine_under_research_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    """RunPostmortem with tenant_id set succeeds under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    pm = _make_run_postmortem(tenant_id="tenant-abc", project_id="proj-1")
    assert pm.tenant_id == "tenant-abc"
    assert pm.project_id == "proj-1"
