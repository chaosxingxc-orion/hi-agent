"""Integration: EvolveEngine aggregates ProjectPostmortem for multiple runs.

Uses real EvolveEngine with no mocks on the SUT.
"""

from __future__ import annotations

from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.contracts import ProjectPostmortem
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.regression_detector import RegressionDetector
from hi_agent.evolve.skill_extractor import SkillExtractor


def test_on_project_completed_returns_postmortem():
    """on_project_completed returns a ProjectPostmortem with correct project_id and run_ids."""
    engine = EvolveEngine(
        skill_extractor=SkillExtractor(),
        regression_detector=RegressionDetector(),
        champion_challenger=ChampionChallenger(),
    )
    pm = engine.on_project_completed(project_id="proj-1", run_ids=["r1", "r2", "r3"])
    assert isinstance(pm, ProjectPostmortem)
    assert pm.project_id == "proj-1"
    assert set(pm.run_ids) == {"r1", "r2", "r3"}


def test_on_project_completed_empty_run_list():
    """on_project_completed handles empty run list."""
    engine = EvolveEngine(
        skill_extractor=SkillExtractor(),
        regression_detector=RegressionDetector(),
        champion_challenger=ChampionChallenger(),
    )
    pm = engine.on_project_completed(project_id="proj-empty", run_ids=[])
    assert pm.project_id == "proj-empty"
    assert pm.run_ids == []
    assert pm.backtrack_count == 0


def test_on_project_completed_created_at_populated():
    """ProjectPostmortem from on_project_completed has a non-empty created_at."""
    engine = EvolveEngine(
        skill_extractor=SkillExtractor(),
        regression_detector=RegressionDetector(),
        champion_challenger=ChampionChallenger(),
    )
    pm = engine.on_project_completed(project_id="proj-ts", run_ids=["r1"])
    assert pm.created_at  # ISO timestamp populated


def test_on_project_completed_preserves_run_ids_order():
    """run_ids in ProjectPostmortem match the input list."""
    run_ids = ["run-a", "run-b", "run-c", "run-d"]
    engine = EvolveEngine(
        skill_extractor=SkillExtractor(),
        regression_detector=RegressionDetector(),
        champion_challenger=ChampionChallenger(),
    )
    pm = engine.on_project_completed(project_id="proj-ordered", run_ids=run_ids)
    assert pm.run_ids == run_ids
