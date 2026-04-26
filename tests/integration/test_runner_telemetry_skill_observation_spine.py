"""Track W2-E.2: SkillObservation carries project_id from the bound session.

Audit found that ``RunTelemetry.observe_skill_execution`` populated
``tenant_id``/``user_id``/``session_id`` from TenantContext but never passed
``project_id``, so the JSONL pool persisted ``project_id=""`` for every skill
execution.  Cross-project skill metrics could not be filtered by project.

Layer 2 — Integration: real RunTelemetry, real SkillObserver writing JSONL,
real RunSession.  No MagicMock on the subsystem under test.
"""

from __future__ import annotations

import json

import pytest
from hi_agent.events import EventEmitter
from hi_agent.memory import RawMemoryStore
from hi_agent.runner_telemetry import RunTelemetry
from hi_agent.session.run_session import RunSession
from hi_agent.skill.observer import SkillObserver

pytestmark = pytest.mark.integration


class _FakeProposal:
    """Minimal proposal with the attributes RunTelemetry reads."""

    def __init__(self, *, skill_id: str = "skill-write-file") -> None:
        self.skill_id = skill_id
        self.version = "1.2.3"


def _make_telemetry(observer: SkillObserver, session: RunSession) -> RunTelemetry:
    return RunTelemetry(
        event_emitter=EventEmitter(),
        raw_memory=RawMemoryStore(),
        observability_hook=None,
        metrics_collector=None,
        skill_observer=observer,
        skill_recorder=None,
        session=session,
        context_manager=None,
    )


def test_observe_skill_execution_persists_project_id_from_session(tmp_path):
    """W2-E.2: session.project_id flows into the persisted SkillObservation."""
    storage_dir = tmp_path / "skill_obs"
    observer = SkillObserver(storage_dir=str(storage_dir))
    session = RunSession(run_id="run-A", project_id="proj-X")
    telemetry = _make_telemetry(observer, session)

    telemetry.observe_skill_execution(
        _FakeProposal(),
        stage_id="stage-1",
        action_succeeded=True,
        payload={"action_kind": "write_file"},
        result={"score": 0.9, "tokens_used": 42},
        run_id="run-A",
        action_seq=0,
        task_family="quick_task",
    )

    # SkillObserver writes JSONL by skill_id.
    jsonl = storage_dir / "skill-write-file.jsonl"
    assert jsonl.exists(), f"expected JSONL at {jsonl}"
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["project_id"] == "proj-X", (
        "SkillObservation.project_id must be sourced from the bound RunSession; "
        f"got {rows[0]!r}"
    )


def test_observe_skill_execution_empty_project_id_when_session_unscoped(tmp_path):
    """When the RunSession has no project_id, the observation row also has ''."""
    storage_dir = tmp_path / "skill_obs"
    observer = SkillObserver(storage_dir=str(storage_dir))
    session = RunSession(run_id="run-B")  # no project_id
    telemetry = _make_telemetry(observer, session)

    telemetry.observe_skill_execution(
        _FakeProposal(skill_id="skill-noop"),
        stage_id="stage-1",
        action_succeeded=False,
        payload={},
        result=None,
        run_id="run-B",
        action_seq=1,
        task_family="quick_task",
    )

    jsonl = storage_dir / "skill-noop.jsonl"
    assert jsonl.exists()
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line]
    assert rows[0]["project_id"] == ""


def test_observe_skill_execution_no_session_falls_back_to_empty(tmp_path):
    """No session bound (e.g. legacy unit-test path) → empty project_id, no crash."""
    storage_dir = tmp_path / "skill_obs"
    observer = SkillObserver(storage_dir=str(storage_dir))
    telemetry = _make_telemetry(observer, session=None)

    telemetry.observe_skill_execution(
        _FakeProposal(skill_id="skill-legacy"),
        stage_id="stage-1",
        action_succeeded=True,
        payload={},
        result={},
        run_id="run-C",
        action_seq=0,
        task_family="quick_task",
    )

    jsonl = storage_dir / "skill-legacy.jsonl"
    assert jsonl.exists()
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line]
    assert rows[0]["project_id"] == ""
