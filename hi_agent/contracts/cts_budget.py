"""Context-token-space budget contracts."""

from __future__ import annotations

from dataclasses import dataclass


# scope: process-internal — pure value object (CLAUDE.md Rule 12 carve-out)
@dataclass(frozen=True)
class CTSBudget:
    """Token budget allocation for layered context.

    Attributes:
        l0_raw_tokens: Token budget for raw (L0) context.
        l1_summary_tokens: Token budget for summary (L1) context.
        l2_index_tokens: Token budget for index (L2) context.
    """

    l0_raw_tokens: int
    l1_summary_tokens: int
    l2_index_tokens: int

    @property
    def total_tokens(self) -> int:
        """Return total token budget."""
        return self.l0_raw_tokens + self.l1_summary_tokens + self.l2_index_tokens


# scope: process-internal — pure value object (CLAUDE.md Rule 12 carve-out)
@dataclass(frozen=True)
class CTSBudgetTemplate:
    """Reusable budget template by task family."""

    task_family: str
    budget: CTSBudget


# scope: process-internal — pure value object (CLAUDE.md Rule 12 carve-out)
@dataclass(frozen=True)
class CTSExplorationBudget:
    """Budget constraints governing the Constrained Trajectory Space.

    These limits prevent unbounded exploration by capping branch counts,
    route-comparison LLM usage, and wall-clock time for the exploration
    phase.

    Attributes:
        max_active_branches_per_stage: Maximum concurrently active
            branches within a single stage.
        max_total_branches_per_run: Maximum branches opened across the
            entire run.
        max_route_compare_calls_per_cycle: Maximum LLM calls allowed for
            route comparison in one routing cycle.
        max_route_compare_token_budget: Token cap for a single
            route-comparison call.
        max_exploration_wall_clock_budget: Wall-clock seconds allocated
            to the exploration phase before forcing convergence.
    """

    max_active_branches_per_stage: int = 3
    max_total_branches_per_run: int = 20
    max_route_compare_calls_per_cycle: int = 5
    max_route_compare_token_budget: int = 4096
    max_exploration_wall_clock_budget: int = 1800
