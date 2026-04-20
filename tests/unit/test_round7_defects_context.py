"""Unit tests for I-4: ContextBudget.from_config() reflection_context forwarding.

Tests verify:
- from_config() forwards context_reflection_context_budget when present.
- from_config() falls back to 500 when the attribute is absent (backward compat).
"""

from types import SimpleNamespace

from hi_agent.context.manager import ContextBudget


def _base_cfg(**overrides):
    """Return a minimal config namespace with all required fields."""
    defaults = dict(
        context_total_window=200_000,
        context_output_reserve=8_000,
        context_system_prompt_budget=2_000,
        context_tool_definitions_budget=3_000,
        context_skill_prompts_budget=5_000,
        memory_retriever_default_budget=1_500,
        context_knowledge_context_budget=1_500,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_from_config_forwards_reflection_budget():
    """from_config() must use context_reflection_context_budget when provided."""
    cfg = _base_cfg(context_reflection_context_budget=800)
    budget = ContextBudget.from_config(cfg)
    assert budget.reflection_context == 800


def test_from_config_fallback_reflection_budget():
    """from_config() must fall back to 500 when context_reflection_context_budget is absent."""
    cfg = _base_cfg()  # no context_reflection_context_budget attribute
    budget = ContextBudget.from_config(cfg)
    assert budget.reflection_context == 500
