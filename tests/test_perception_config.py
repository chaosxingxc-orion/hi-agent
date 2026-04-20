# tests/test_perception_config.py
from hi_agent.config.trace_config import TraceConfig
from hi_agent.middleware.perception import PerceptionMiddleware


def test_perception_from_config_thresholds():
    cfg = TraceConfig(
        perception_summary_threshold_tokens=5_000,
        perception_summarize_char_threshold=1_000,
        perception_max_entities=25,
    )
    p = PerceptionMiddleware.from_config(cfg)
    assert p._summary_threshold == 5_000
    assert p._llm_summarize_char_threshold == 1_000
    assert p._max_entities == 25


def test_perception_from_config_llm_params():
    cfg = TraceConfig(
        perception_summarize_temperature=0.5,
        perception_summarize_max_tokens=400,
    )
    p = PerceptionMiddleware.from_config(cfg)
    assert p._summarize_temperature == 0.5
    assert p._summarize_max_tokens == 400
