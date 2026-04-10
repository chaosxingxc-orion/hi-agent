"""Conditional routing based on explicit rules.

Inspired by LangGraph's conditional_edges pattern:
explicit route_fn returns next stage based on state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RouteContext:
    """State available to condition functions for routing decisions."""

    current_stage: str
    run_state: dict[str, Any] = field(default_factory=dict)
    branch_outcomes: dict[str, str] = field(default_factory=dict)
    failure_codes: list[str] = field(default_factory=list)
    budget_remaining_pct: float = 1.0
    quality_score: float | None = None


@dataclass
class ConditionalRoute:
    """A single routing rule: condition -> target stage."""

    condition: Callable[[RouteContext], bool]
    target_stage: str
    priority: int = 0
    description: str = ""


@dataclass
class RouteExplanation:
    """Result of evaluating a single route condition -- used for audit."""

    route: ConditionalRoute
    matched: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class ConditionalRouter:
    """Route to next stage based on explicit conditions.

    Unlike LLM-based routing (implicit), this uses explicit
    condition functions to determine the path -- more predictable,
    auditable, and debuggable.

    Routes are evaluated in *descending* priority order; the first
    matching condition wins.  If no condition matches, the default
    stage is returned (or ``ValueError`` is raised if no default
    has been set).
    """

    def __init__(self) -> None:
        """Initialize ConditionalRouter."""
        self._routes: list[ConditionalRoute] = []
        self._default: str | None = None

    def add_route(
        self,
        condition: Callable[[RouteContext], bool],
        target_stage: str,
        priority: int = 0,
        description: str = "",
    ) -> None:
        """Register a conditional routing rule.

        Args:
            condition: Callable that receives a :class:`RouteContext` and
                returns ``True`` if this route should activate.
            target_stage: Stage identifier to route to on match.
            priority: Higher values are evaluated first.
            description: Human-readable explanation for audit logs.
        """
        self._routes.append(
            ConditionalRoute(
                condition=condition,
                target_stage=target_stage,
                priority=priority,
                description=description,
            )
        )

    def set_default(self, target_stage: str) -> None:
        """Set the fallback stage when no condition matches."""
        self._default = target_stage

    def evaluate(self, context: RouteContext) -> str:
        """Evaluate conditions in priority order, return first matching target.

        Raises:
            ValueError: If no condition matches and no default is set.
        """
        for route in self._sorted_routes():
            try:
                if route.condition(context):
                    return route.target_stage
            except Exception:
                # Condition functions must not crash routing;
                # a failing condition is treated as non-matching.
                continue

        if self._default is not None:
            return self._default

        raise ValueError(
            f"No routing condition matched for stage '{context.current_stage}' "
            "and no default stage is configured."
        )

    def explain(self, context: RouteContext) -> list[RouteExplanation]:
        """Return all conditions and whether they matched -- for audit trail.

        Every registered route is evaluated and reported, regardless of
        whether an earlier route already matched.  This gives full
        visibility into the routing decision.
        """
        explanations: list[RouteExplanation] = []
        for route in self._sorted_routes():
            try:
                matched = route.condition(context)
                explanations.append(
                    RouteExplanation(
                        route=route,
                        matched=matched,
                        reason=route.description if matched else "",
                    )
                )
            except Exception as exc:
                explanations.append(
                    RouteExplanation(
                        route=route,
                        matched=False,
                        reason=f"condition raised: {exc}",
                    )
                )
        return explanations

    def _sorted_routes(self) -> list[ConditionalRoute]:
        """Return routes sorted by descending priority."""
        return sorted(self._routes, key=lambda r: r.priority, reverse=True)
