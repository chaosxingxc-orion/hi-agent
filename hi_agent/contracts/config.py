"""Task-family runtime configuration contracts."""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.contracts.cts_budget import CTSBudget


# scope: process-internal — task-family descriptor, not a stored tenant record
@dataclass(frozen=True)
class TaskFamilyConfig:
    """Task family execution profile."""

    task_family: str
    max_stage_retries: int
    default_budget: CTSBudget
    enable_dead_end_recovery: bool = True
