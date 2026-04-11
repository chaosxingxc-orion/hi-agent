# tests/test_skill_config.py
from hi_agent.config.trace_config import TraceConfig
from hi_agent.skill.evolver import SkillEvolver
from hi_agent.skill.observer import SkillObservation


def test_skill_evolver_thresholds_from_config():
    cfg = TraceConfig(
        skill_evolver_success_threshold=0.85,
        skill_evolver_min_pattern_occurrences=5,
    )
    evolver = SkillEvolver.from_config(cfg)
    assert evolver._success_threshold == 0.85
    assert evolver._min_pattern_occurrences == 5


def test_skill_observer_summary_len_from_config():
    cfg = TraceConfig(skill_observer_max_summary_len=200)
    obs = SkillObservation(
        observation_id="obs_test",
        skill_id="s1",
        skill_version="1.0.0",
        run_id="r1",
        stage_id="st1",
        timestamp="2026-01-01T00:00:00",
        success=True,
        input_summary="x" * 300,
        output_summary="y" * 300,
        max_summary_len=200,
    )
    assert len(obs.input_summary) == 200
    assert len(obs.output_summary) == 200


def test_skill_loader_limits_from_config():
    from hi_agent.skill.loader import SkillLoader
    cfg = TraceConfig(
        skill_loader_max_skills_in_prompt=10,
        skill_loader_max_prompt_tokens=3_000,
    )
    loader = SkillLoader(
        search_dirs=[],
        max_skills_in_prompt=cfg.skill_loader_max_skills_in_prompt,
        max_prompt_tokens=cfg.skill_loader_max_prompt_tokens,
    )
    assert loader._max_skills == 10
    assert loader._max_tokens == 3_000
