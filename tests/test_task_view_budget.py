"""Tests for task view budgeting."""

import pytest
from hi_agent.task_view import enforce_budget


def test_enforce_budget_truncates() -> None:
    """Budget helper should keep first N items."""
    assert enforce_budget(["a", "b", "c"], 2) == ["a", "b"]


def test_enforce_budget_rejects_negative() -> None:
    """Budget helper should reject invalid max_items."""
    with pytest.raises(ValueError):
        enforce_budget(["a"], -1)
