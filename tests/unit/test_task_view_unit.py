"""Unit tests for hi_agent.task_view — Layer 1 (unit).

Covers:
  - token_budget: count_tokens, enforce_budget, enforce_layer_budget, set_token_counter
  - builder: TaskView, TaskViewSection, format_run_index, format_stage_summary

No network, no real LLM, no external mocks.
Profile validated: default-offline
"""

from __future__ import annotations

import pytest
from hi_agent.task_view.token_budget import (
    DEFAULT_BUDGET,
    LAYER_BUDGETS,
    count_tokens,
    enforce_budget,
    enforce_layer_budget,
    set_token_counter,
)

# ---------------------------------------------------------------------------
# count_tokens — default heuristic
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_empty_string_returns_one(self) -> None:
        """Empty string returns at least 1 (per the max(1, ...) guard)."""
        assert count_tokens("") == 1

    def test_four_chars_is_one_token(self) -> None:
        assert count_tokens("abcd") == 1

    def test_eight_chars_is_two_tokens(self) -> None:
        assert count_tokens("abcdefgh") == 2

    def test_custom_counter_used_when_set(self) -> None:
        set_token_counter(lambda text: len(text))
        try:
            assert count_tokens("hello") == 5
        finally:
            set_token_counter(None)  # always restore default

    def test_restore_default_after_custom(self) -> None:
        set_token_counter(lambda text: 999)
        set_token_counter(None)
        # Back to heuristic: "abcd" → 1
        assert count_tokens("abcd") == 1


# ---------------------------------------------------------------------------
# enforce_budget — item count
# ---------------------------------------------------------------------------


class TestEnforceBudget:
    def test_empty_list_returns_empty(self) -> None:
        assert enforce_budget([], 5) == []

    def test_trim_to_max_items(self) -> None:
        assert enforce_budget(["a", "b", "c", "d"], 2) == ["a", "b"]

    def test_max_items_larger_than_list_returns_all(self) -> None:
        items = ["x", "y"]
        assert enforce_budget(items, 10) == items

    def test_zero_max_items_returns_empty(self) -> None:
        assert enforce_budget(["a", "b"], 0) == []

    def test_negative_max_items_raises(self) -> None:
        with pytest.raises(ValueError):
            enforce_budget(["a"], -1)


# ---------------------------------------------------------------------------
# enforce_layer_budget — token truncation
# ---------------------------------------------------------------------------


class TestEnforceLayerBudget:
    def test_content_within_budget_returned_unchanged(self) -> None:
        short = "hi"
        assert enforce_layer_budget(short, max_tokens=100) == short

    def test_zero_max_tokens_returns_empty(self) -> None:
        assert enforce_layer_budget("any content", max_tokens=0) == ""

    def test_truncation_reduces_token_count(self) -> None:
        # 100 chars → ~25 tokens; truncate to 5 tokens max
        long_text = "a" * 100
        result = enforce_layer_budget(long_text, max_tokens=5)
        assert len(result) <= 20  # 5 tokens * 4 chars each

    def test_exact_budget_fit_returns_content(self) -> None:
        text = "abcd"  # exactly 1 token
        result = enforce_layer_budget(text, max_tokens=1)
        assert len(result) >= 4  # fits in budget


# ---------------------------------------------------------------------------
# LAYER_BUDGETS and DEFAULT_BUDGET constants
# ---------------------------------------------------------------------------


class TestBudgetConstants:
    def test_default_budget_is_positive(self) -> None:
        assert DEFAULT_BUDGET > 0

    def test_layer_budgets_not_empty(self) -> None:
        assert len(LAYER_BUDGETS) >= 5

    def test_layer_budgets_all_positive(self) -> None:
        for layer, budget in LAYER_BUDGETS.items():
            assert budget > 0, f"{layer} budget is non-positive"

    def test_known_layers_present(self) -> None:
        expected = {"l2_index", "l1_current_stage", "l1_previous_stage"}
        assert expected.issubset(LAYER_BUDGETS.keys())


# ---------------------------------------------------------------------------
# TaskView and TaskViewSection dataclasses
# ---------------------------------------------------------------------------


class TestTaskViewDataclasses:
    def test_task_view_section_stores_fields(self) -> None:
        from hi_agent.task_view.builder import TaskViewSection

        sec = TaskViewSection(layer="l2_index", content="run map", token_count=10)
        assert sec.layer == "l2_index"
        assert sec.content == "run map"
        assert sec.token_count == 10

    def test_task_view_defaults(self) -> None:
        from hi_agent.task_view.builder import TaskView

        tv = TaskView()
        assert tv.sections == []
        assert tv.total_tokens == 0
        assert tv.budget == DEFAULT_BUDGET
        assert tv.budget_utilization == 0.0

    def test_task_view_with_sections(self) -> None:
        from hi_agent.task_view.builder import TaskView, TaskViewSection

        sec = TaskViewSection(layer="l2_index", content="...", token_count=5)
        tv = TaskView(sections=[sec], total_tokens=5, budget=100, budget_utilization=0.05)
        assert len(tv.sections) == 1
        assert tv.total_tokens == 5
        assert tv.budget_utilization == pytest.approx(0.05)
