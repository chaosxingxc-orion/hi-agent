"""Context-token-space budget contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CTSBudget:
    """Token budget allocation for layered context."""

    l0_raw_tokens: int
    l1_summary_tokens: int
    l2_index_tokens: int

    @property
    def total_tokens(self) -> int:
        """Return total token budget."""
        return self.l0_raw_tokens + self.l1_summary_tokens + self.l2_index_tokens


@dataclass(frozen=True)
class CTSBudgetTemplate:
    """Reusable budget template by task family."""

    task_family: str
    budget: CTSBudget
