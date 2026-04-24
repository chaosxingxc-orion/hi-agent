"""Integration test: project_id round-trips correctly across Artifact, GateRecord, RunPostmortem.

Uses real objects (no mocks on SUT).
"""
from __future__ import annotations

from hi_agent.artifacts.contracts import Artifact
from hi_agent.evolve.contracts import RunPostmortem
from hi_agent.management.gate_api import GateRecord, GateStatus
from hi_agent.management.gate_context import GateContext
from hi_agent.management.gate_timeout import GateTimeoutPolicy


def test_artifact_project_id_round_trip() -> None:
    a = Artifact(artifact_id="a1", artifact_type="base", project_id="proj-X")
    d = a.to_dict()
    assert d["project_id"] == "proj-X"
    a2 = Artifact.from_dict(d)
    assert a2.project_id == "proj-X"


def test_artifact_project_id_default_empty() -> None:
    a = Artifact(artifact_id="a2", artifact_type="base")
    assert a.project_id == ""


def test_run_postmortem_project_id_round_trip() -> None:
    pm = RunPostmortem(
        run_id="r1",
        task_id="t1",
        task_family="quick_task",
        outcome="completed",
        stages_completed=["s1"],
        stages_failed=[],
        branches_explored=1,
        branches_pruned=0,
        total_actions=2,
        failure_codes=[],
        duration_seconds=1.0,
        project_id="proj-Y",
    )
    assert pm.project_id == "proj-Y"


def test_gate_record_project_id() -> None:
    ctx = GateContext(
        gate_ref="g1",
        run_id="r1",
        stage_id="s1",
        branch_id="b1",
        submitter="test",
    )
    record = GateRecord(
        context=ctx,
        status=GateStatus.PENDING,
        timeout_seconds=60.0,
        timeout_policy=GateTimeoutPolicy.REJECT,
        project_id="proj-Z",
    )
    assert record.project_id == "proj-Z"
