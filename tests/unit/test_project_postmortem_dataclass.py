"""Unit: ProjectRetrospective and CalibrationSignal dataclasses."""

from __future__ import annotations

from hi_agent.evolve.contracts import CalibrationSignal, ProjectRetrospective


def test_project_postmortem_defaults():
    pm = ProjectRetrospective(project_id="proj-1", run_ids=["run-1", "run-2"])
    assert pm.project_id == "proj-1"
    assert pm.run_ids == ["run-1", "run-2"]
    assert pm.backtrack_count == 0
    assert pm.outcome_assessments == []
    assert pm.invalidated_assumptions == []
    assert pm.cost_by_phase == {}
    assert pm.accepted_artifact_ids == []
    assert pm.rejected_artifact_ids == []
    assert pm.skill_deltas == []
    assert pm.routing_deltas == []
    assert pm.created_at  # not empty


def test_project_postmortem_custom_fields():
    pm = ProjectRetrospective(
        project_id="proj-2",
        run_ids=["r1"],
        backtrack_count=3,
        outcome_assessments=["confirmed"],
        invalidated_assumptions=["assumption-X"],
    )
    assert pm.backtrack_count == 3
    assert pm.outcome_assessments == ["confirmed"]
    assert pm.invalidated_assumptions == ["assumption-X"]


def test_calibration_signal_fields():
    sig = CalibrationSignal(project_id="p1", run_id="r1", model="gpt-4", tier="tier_a")
    assert sig.cost_usd == 0.0
    assert sig.latency_ms == 0.0
    assert sig.quality_score == 0.0
    assert sig.recorded_at  # not empty


def test_calibration_signal_custom_values():
    sig = CalibrationSignal(
        project_id="p1",
        run_id="r1",
        model="claude-3",
        tier="strong",
        cost_usd=0.05,
        latency_ms=1200.0,
        quality_score=0.85,
    )
    assert sig.cost_usd == 0.05
    assert sig.latency_ms == 1200.0
    assert sig.quality_score == 0.85