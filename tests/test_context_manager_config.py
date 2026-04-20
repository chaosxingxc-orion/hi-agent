# tests/test_context_manager_config.py
from hi_agent.config.trace_config import TraceConfig
from hi_agent.context.manager import ContextBudget, ContextManager


def test_context_budget_from_config():
    cfg = TraceConfig(
        context_total_window=128_000,
        context_output_reserve=4_000,
        context_system_prompt_budget=1_000,
        context_tool_definitions_budget=2_000,
        context_knowledge_context_budget=800,
    )
    budget = ContextBudget.from_config(cfg)
    assert budget.total_window == 128_000
    assert budget.output_reserve == 4_000
    assert budget.system_prompt == 1_000
    assert budget.tool_definitions == 2_000
    assert budget.knowledge_context == 800

def test_context_manager_thresholds_from_config():
    cfg = TraceConfig(
        context_health_green_threshold=0.60,
        context_health_yellow_threshold=0.75,
        context_health_orange_threshold=0.90,
        context_max_compression_failures=5,
        context_diminishing_window=4,
        context_diminishing_threshold=50,
    )
    cm = ContextManager.from_config(cfg)
    assert cm._green_threshold == 0.60
    assert cm._yellow_threshold == 0.75
    assert cm._orange_threshold == 0.90
    assert cm._max_compression_failures == 5
    assert cm._diminishing_window == 4
    assert cm._diminishing_threshold == 50
