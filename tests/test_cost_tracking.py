"""Tests for CostCalculator and MetricsCollector cost integration."""

from __future__ import annotations

import pytest
from hi_agent.observability.collector import MetricsCollector
from hi_agent.session.cost_tracker import CostCalculator


class TestCostCalculator:
    """CostCalculator tests."""

    def test_tracks_costs(self):
        calc = CostCalculator()
        cost = calc.calculate("claude-sonnet-4", input_tokens=1000, output_tokens=500)
        assert cost > 0.0
        assert calc.get_total_cost() == cost

    def test_per_model_breakdown(self):
        calc = CostCalculator()
        calc.calculate("claude-sonnet-4", input_tokens=1000, output_tokens=500)
        calc.calculate("claude-haiku-4", input_tokens=2000, output_tokens=1000)
        breakdown = calc.get_breakdown()
        assert "claude-sonnet-4" in breakdown["per_model"]
        assert "claude-haiku-4" in breakdown["per_model"]
        assert breakdown["call_count"] == 2

    def test_per_tier_breakdown(self):
        calc = CostCalculator()
        calc.calculate("claude-opus-4", input_tokens=1000, output_tokens=100)
        calc.calculate("claude-sonnet-4", input_tokens=1000, output_tokens=100)
        calc.calculate("claude-haiku-4", input_tokens=1000, output_tokens=100)
        breakdown = calc.get_breakdown()
        assert "strong" in breakdown["per_tier"]
        assert "medium" in breakdown["per_tier"]
        assert "light" in breakdown["per_tier"]

    def test_zero_cost_for_unknown_model(self):
        calc = CostCalculator()
        cost = calc.calculate("unknown-model-xyz", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_cumulative_tracking(self):
        calc = CostCalculator()
        c1 = calc.calculate("claude-sonnet-4", input_tokens=1000, output_tokens=500)
        c2 = calc.calculate("claude-sonnet-4", input_tokens=1000, output_tokens=500)
        assert calc.get_total_cost() == pytest.approx(c1 + c2)

    def test_cache_tokens(self):
        calc = CostCalculator()
        cost = calc.calculate(
            "claude-sonnet-4",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=500,
            cache_creation_tokens=200,
        )
        assert cost > 0.0

    def test_tier_downgrade_saves_cost(self):
        calc = CostCalculator()
        strong_cost = calc.calculate("claude-opus-4", input_tokens=1000, output_tokens=500)
        calc2 = CostCalculator()
        light_cost = calc2.calculate("claude-haiku-4", input_tokens=1000, output_tokens=500)
        assert strong_cost > light_cost


class TestMetricsCollectorCostIntegration:
    """MetricsCollector receives cost metrics."""

    def test_cost_recorded(self):
        mc = MetricsCollector()
        mc.record("llm_cost_usd_total", 0.05, {"model": "claude-sonnet-4"})
        snap = mc.snapshot()
        assert "llm_cost_usd_total" in snap

    def test_cost_per_run_histogram(self):
        mc = MetricsCollector()
        mc.record("llm_cost_per_run", 0.02)
        mc.record("llm_cost_per_run", 0.05)
        mc.record("llm_cost_per_run", 0.10)
        snap = mc.snapshot()
        assert "llm_cost_per_run" in snap
        assert snap["llm_cost_per_run"]["_total"]["count"] == 3
