"""Task-level contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskBudget:
    """Execution budget limits for a single task run.

    All fields carry sensible defaults so callers can construct a budget
    with only the dimensions they care about.

    Attributes:
        max_llm_calls: Maximum number of LLM inference calls allowed.
        max_wall_clock_seconds: Maximum wall-clock time in seconds.
        max_actions: Maximum number of harness actions executed.
        max_cost_cents: Maximum spend in US cents across all resources.
    """

    max_llm_calls: int = 100
    max_wall_clock_seconds: int = 3600
    max_actions: int = 50
    max_cost_cents: int = 1000


@dataclass
class TaskContract:
    """Top-level task intent and acceptance boundaries.

    Attributes:
        task_id: Unique identifier for this task contract.
        goal: Natural-language description of the desired outcome.
        constraints: Free-form constraint strings (e.g. ``"no_internet"``).
        acceptance_criteria: Conditions that must hold for the task to pass.
        task_family: Routing hint selecting a task-family config profile.
        budget: Optional execution budget governing resource consumption.
        deadline: Optional ISO-8601 datetime string for hard deadline.
        risk_level: Categorical risk tag (``low``, ``medium``, ``high``,
            ``critical``).
        environment_scope: List of environment identifiers the task may
            touch (e.g. ``["staging"]``).
        input_refs: URIs or identifiers for input artifacts required by
            the task.
        priority: Numeric priority from 1 (highest) to 10 (lowest).
        parent_task_id: Optional parent task identifier for sub-task
            hierarchy.
        decomposition_strategy: Optional hint for how the task should be
            decomposed (``"dag"``, ``"tree"``, ``"linear"``).
    """

    task_id: str
    goal: str
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    task_family: str = "quick_task"
    # --- Extended fields from TRACE architecture v2.0 ---
    budget: TaskBudget | None = None
    deadline: str | None = None
    risk_level: str = "low"
    environment_scope: list[str] = field(default_factory=list)
    input_refs: list[str] = field(default_factory=list)
    priority: int = 5
    parent_task_id: str | None = None
    decomposition_strategy: str | None = None

