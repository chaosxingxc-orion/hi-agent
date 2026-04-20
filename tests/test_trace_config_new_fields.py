# tests/test_trace_config_new_fields.py
from hi_agent.config.trace_config import TraceConfig


def test_new_context_fields_exist():
    cfg = TraceConfig()
    assert cfg.context_total_window == 200_000
    assert cfg.context_output_reserve == 8_000
    assert cfg.context_system_prompt_budget == 2_000
    assert cfg.context_tool_definitions_budget == 3_000
    assert cfg.context_knowledge_context_budget == 1_500
    assert cfg.context_health_green_threshold == 0.70
    assert cfg.context_health_yellow_threshold == 0.85
    assert cfg.context_health_orange_threshold == 0.95
    assert cfg.context_max_compression_failures == 3
    assert cfg.context_diminishing_window == 3
    assert cfg.context_diminishing_threshold == 100


def test_new_perception_fields_exist():
    cfg = TraceConfig()
    assert cfg.perception_summary_threshold_tokens == 2_000
    assert cfg.perception_summarize_char_threshold == 500
    assert cfg.perception_max_entities == 50
    assert cfg.perception_summarize_temperature == 0.3
    assert cfg.perception_summarize_max_tokens == 200


def test_new_budget_guard_fields_exist():
    cfg = TraceConfig()
    assert cfg.budget_guard_low_threshold == 0.10
    assert cfg.budget_guard_mid_threshold == 0.30
    assert cfg.budget_guard_high_threshold == 0.70


def test_new_skill_fields_exist():
    cfg = TraceConfig()
    assert cfg.skill_evolver_success_threshold == 0.70
    assert cfg.skill_evolver_min_pattern_occurrences == 3
    assert cfg.skill_loader_max_skills_in_prompt == 50
    assert cfg.skill_loader_max_prompt_tokens == 10_000
    assert cfg.skill_observer_max_summary_len == 500


def test_new_llm_fields_exist():
    cfg = TraceConfig()
    assert cfg.llm_retry_base_seconds == 1.0


def test_new_fields_override_via_json(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"context_total_window": 128000, "budget_guard_high_threshold": 0.80}')
    cfg = TraceConfig.from_file(str(cfg_file))
    assert cfg.context_total_window == 128_000
    assert cfg.budget_guard_high_threshold == 0.80


def test_new_fields_override_via_env(monkeypatch):
    monkeypatch.setenv("HI_AGENT_CONTEXT_TOTAL_WINDOW", "64000")
    monkeypatch.setenv("HI_AGENT_SKILL_EVOLVER_SUCCESS_THRESHOLD", "0.85")
    cfg = TraceConfig.from_env()
    assert cfg.context_total_window == 64_000
    assert cfg.skill_evolver_success_threshold == 0.85
