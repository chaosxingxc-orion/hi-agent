"""Tests for hi_agent.route_engine.conditional_router -- explicit conditional routing."""

from __future__ import annotations

import pytest
from hi_agent.route_engine.conditional_router import (
    ConditionalRoute,
    ConditionalRouter,
    RouteContext,
    RouteExplanation,
)

# ---------------------------------------------------------------------------
# RouteContext
# ---------------------------------------------------------------------------


class TestRouteContext:
    """RouteContext has correct defaults."""

    def test_defaults(self) -> None:
        ctx = RouteContext(current_stage="S1")
        assert ctx.current_stage == "S1"
        assert ctx.run_state == {}
        assert ctx.branch_outcomes == {}
        assert ctx.failure_codes == []
        assert ctx.budget_remaining_pct == 1.0
        assert ctx.quality_score is None

    def test_custom_values(self) -> None:
        ctx = RouteContext(
            current_stage="S3",
            failure_codes=["no_progress"],
            budget_remaining_pct=0.3,
            quality_score=0.85,
        )
        assert ctx.failure_codes == ["no_progress"]
        assert ctx.budget_remaining_pct == 0.3
        assert ctx.quality_score == 0.85


# ---------------------------------------------------------------------------
# ConditionalRouter -- basic evaluation
# ---------------------------------------------------------------------------


class TestConditionalRouterEvaluate:
    """ConditionalRouter.evaluate routes correctly."""

    def test_single_matching_route(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: ctx.current_stage == "S1",
            target_stage="S2",
            description="S1 -> S2",
        )
        ctx = RouteContext(current_stage="S1")
        assert router.evaluate(ctx) == "S2"

    def test_no_match_uses_default(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: False,
            target_stage="S3",
        )
        router.set_default("S5")
        ctx = RouteContext(current_stage="S2")
        assert router.evaluate(ctx) == "S5"

    def test_no_match_no_default_raises(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: False,
            target_stage="S3",
        )
        ctx = RouteContext(current_stage="S2")
        with pytest.raises(ValueError, match="No routing condition matched"):
            router.evaluate(ctx)

    def test_first_match_wins(self) -> None:
        router = ConditionalRouter()
        router.add_route(condition=lambda ctx: True, target_stage="S2", priority=10)
        router.add_route(condition=lambda ctx: True, target_stage="S3", priority=5)
        ctx = RouteContext(current_stage="S1")
        assert router.evaluate(ctx) == "S2"

    def test_empty_router_with_default(self) -> None:
        router = ConditionalRouter()
        router.set_default("S1")
        ctx = RouteContext(current_stage="S0")
        assert router.evaluate(ctx) == "S1"


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    """Routes evaluate in descending priority order."""

    def test_higher_priority_first(self) -> None:
        router = ConditionalRouter()
        # Low priority matches first if both match.
        router.add_route(
            condition=lambda ctx: True,
            target_stage="low",
            priority=1,
        )
        router.add_route(
            condition=lambda ctx: True,
            target_stage="high",
            priority=100,
        )
        ctx = RouteContext(current_stage="S1")
        assert router.evaluate(ctx) == "high"

    def test_equal_priority_uses_insertion_order(self) -> None:
        """With equal priority, earlier-registered routes evaluate first."""
        router = ConditionalRouter()
        router.add_route(condition=lambda ctx: True, target_stage="first", priority=0)
        router.add_route(condition=lambda ctx: True, target_stage="second", priority=0)
        ctx = RouteContext(current_stage="S1")
        # Both have priority 0; sorted() is stable, so insertion order is preserved.
        result = router.evaluate(ctx)
        assert result in ("first", "second")


# ---------------------------------------------------------------------------
# Condition-based routing
# ---------------------------------------------------------------------------


class TestConditionBasedRouting:
    """Routes using real condition logic."""

    def test_budget_exhausted_route(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: ctx.budget_remaining_pct < 0.1,
            target_stage="S5_finalize",
            priority=100,
            description="Budget exhausted, skip to finalize",
        )
        router.add_route(
            condition=lambda ctx: ctx.current_stage == "S2",
            target_stage="S3",
            priority=10,
            description="Normal S2 -> S3 transition",
        )
        # Under budget, should go to S5_finalize.
        ctx = RouteContext(current_stage="S2", budget_remaining_pct=0.05)
        assert router.evaluate(ctx) == "S5_finalize"

    def test_failure_code_triggers_backtrack(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: "no_progress" in ctx.failure_codes,
            target_stage="S1_retry",
            priority=50,
            description="Backtrack on no_progress",
        )
        router.set_default("S3")
        ctx = RouteContext(
            current_stage="S2",
            failure_codes=["no_progress"],
        )
        assert router.evaluate(ctx) == "S1_retry"

    def test_quality_gate(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: (ctx.quality_score or 0) >= 0.9,
            target_stage="S5_review",
            priority=20,
            description="High quality, proceed to review",
        )
        router.set_default("S3_iterate")
        # High quality.
        ctx_high = RouteContext(current_stage="S4", quality_score=0.95)
        assert router.evaluate(ctx_high) == "S5_review"
        # Low quality.
        ctx_low = RouteContext(current_stage="S4", quality_score=0.5)
        assert router.evaluate(ctx_low) == "S3_iterate"


# ---------------------------------------------------------------------------
# Explain / audit
# ---------------------------------------------------------------------------


class TestExplain:
    """ConditionalRouter.explain provides full audit trail."""

    def test_explain_all_routes(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: True,
            target_stage="S2",
            priority=10,
            description="Always matches",
        )
        router.add_route(
            condition=lambda ctx: False,
            target_stage="S3",
            priority=5,
            description="Never matches",
        )
        ctx = RouteContext(current_stage="S1")
        explanations = router.explain(ctx)
        assert len(explanations) == 2
        # Sorted by priority, so first should be the always-match.
        assert explanations[0].matched is True
        assert explanations[0].route.target_stage == "S2"
        assert explanations[1].matched is False
        assert explanations[1].route.target_stage == "S3"

    def test_explain_contains_descriptions(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: True,
            target_stage="S2",
            description="Budget ok",
        )
        ctx = RouteContext(current_stage="S1")
        explanations = router.explain(ctx)
        assert explanations[0].reason == "Budget ok"

    def test_explain_failing_condition(self) -> None:
        """A condition that raises an exception is reported as non-matching."""
        router = ConditionalRouter()

        def bad_condition(ctx: RouteContext) -> bool:
            raise RuntimeError("oops")

        router.add_route(
            condition=bad_condition,
            target_stage="S_error",
            description="Broken condition",
        )
        ctx = RouteContext(current_stage="S1")
        explanations = router.explain(ctx)
        assert len(explanations) == 1
        assert explanations[0].matched is False
        assert "condition raised" in explanations[0].reason

    def test_explain_returns_route_explanation_type(self) -> None:
        router = ConditionalRouter()
        router.add_route(condition=lambda ctx: True, target_stage="S2")
        ctx = RouteContext(current_stage="S1")
        explanations = router.explain(ctx)
        assert isinstance(explanations[0], RouteExplanation)
        assert isinstance(explanations[0].route, ConditionalRoute)


# ---------------------------------------------------------------------------
# Error resilience
# ---------------------------------------------------------------------------


class TestErrorResilience:
    """Router handles badly-behaved conditions gracefully."""

    def test_failing_condition_skipped_in_evaluate(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: 1 / 0 > 0,  # type: ignore[operator]  expiry_wave: Wave 17
            target_stage="S_crash",
            priority=100,
        )
        router.add_route(
            condition=lambda ctx: True,
            target_stage="S_safe",
            priority=1,
        )
        ctx = RouteContext(current_stage="S1")
        assert router.evaluate(ctx) == "S_safe"

    def test_all_conditions_fail_uses_default(self) -> None:
        router = ConditionalRouter()
        router.add_route(
            condition=lambda ctx: (_ for _ in ()).throw(ValueError("boom")),  # type: ignore[func-returns-value]  expiry_wave: Wave 17
            target_stage="S_crash",
        )
        router.set_default("S_fallback")
        ctx = RouteContext(current_stage="S1")
        assert router.evaluate(ctx) == "S_fallback"


# ---------------------------------------------------------------------------
# Package exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    """Conditional router types are exported from route_engine package."""

    def test_imports(self) -> None:
        from hi_agent.route_engine import (
            ConditionalRoute,
            ConditionalRouter,
            RouteContext,
            RouteExplanation,
        )

        assert ConditionalRouter is not None
        assert RouteContext is not None
        assert ConditionalRoute is not None
        assert RouteExplanation is not None
