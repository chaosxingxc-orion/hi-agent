"""Unit tests: EpisodeRecord spine field round-trip."""

from __future__ import annotations

from hi_agent.memory.episodic import EpisodeRecord


def test_round_trip_preserves_spine() -> None:
    """EpisodeRecord spine fields survive construction and are accessible."""
    rec = EpisodeRecord(
        run_id="run-001",
        task_id="task-001",
        task_family="quick_task",
        goal="do something",
        outcome="completed",
        stages_completed=["s1"],
        key_findings=["finding"],
        key_decisions=["decision"],
        failure_codes=[],
        tenant_id="tenant-abc",
        user_id="user-xyz",
        session_id="sess-123",
        project_id="proj-456",
    )
    assert rec.tenant_id == "tenant-abc"
    assert rec.user_id == "user-xyz"
    assert rec.session_id == "sess-123"
    assert rec.project_id == "proj-456"
    assert rec.run_id == "run-001"


def test_spine_defaults_are_empty_strings() -> None:
    """EpisodeRecord spine fields default to empty string for backwards-compat."""
    rec = EpisodeRecord(
        run_id="run-002",
        task_id="task-002",
        task_family="quick_task",
        goal="do something",
        outcome="failed",
        stages_completed=[],
        key_findings=[],
        key_decisions=[],
        failure_codes=["ERR_001"],
    )
    assert rec.tenant_id == ""
    assert rec.user_id == ""
    assert rec.session_id == ""
    assert rec.project_id == ""
