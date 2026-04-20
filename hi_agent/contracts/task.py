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

    ## Field Consumption Levels

    Fields are annotated with their consumption level so that integrators
    know exactly what the default TRACE pipeline acts on:

    - **ACTIVE**: field is read by platform execution logic and directly
      influences run behavior or outcome.
    - **PASSTHROUGH**: field is accepted, stored, returned in the result,
      and passed to the executor — but the *default* TRACE pipeline does
      not consume it.  Business agents that define custom profiles,
      middleware, or stage graphs are responsible for implementing
      consumption of these fields.
    - **QUEUE_ONLY**: field is used for scheduling / prioritization before
      execution begins, but has no effect once a stage is running.

    Attributes:
        task_id: [ACTIVE] Unique identifier for this task contract.
        goal: [ACTIVE] Natural-language description of the desired outcome.
            Injected into every stage task-view prompt.
        constraints: [ACTIVE] Free-form constraint strings parsed by the
            runner for built-in prefixes: ``"fail_action:<stage>"``,
            ``"action_max_retries:<n>"``, ``"invoker_role:<role>"``.
            Unrecognized constraint strings are stored and returned but not
            acted upon by the default pipeline.
        acceptance_criteria: [ACTIVE] Post-run acceptance conditions.
            Supported patterns: ``"required_stage:<stage_id>"`` (stage must
            have outcome ``"succeeded"``), ``"required_artifact:<id>"``
            (artifact must be present).  Any unmet criterion downgrades the
            final outcome from ``"completed"`` to ``"failed"``.  Arbitrary
            criterion strings beyond these two patterns are stored and
            returned but are not enforced by the default pipeline.
        task_family: [ACTIVE] Routing hint selecting a task-family config
            profile.
        budget: [ACTIVE] Optional execution budget governing resource
            consumption (LLM calls, wall-clock time, action count, cost).
        deadline: [ACTIVE] Optional ISO-8601 datetime string; the runner
            aborts execution and returns ``"failed"`` when wall-clock time
            exceeds this value.
        risk_level: [ACTIVE] Categorical risk tag (``low``, ``medium``,
            ``high``, ``critical``) used by harness governance to decide
            approval requirements.
        profile_id: [ACTIVE] Business agents pass a profile_id to activate
            a ProfileSpec from the platform's ProfileRegistry, selecting
            custom stage graphs and capability routes.
        decomposition_strategy: [ACTIVE] Hint for task decomposition
            (``"dag"``, ``"tree"``, ``"linear"``).  Read by
            TaskOrchestrator when orchestrator-mode execution is used.
        priority: [QUEUE_ONLY] Numeric priority from 1 (highest) to 10
            (lowest).  Used by RunManager to order queued runs; has no
            effect once a run is executing.
        environment_scope: [PASSTHROUGH] List of environment identifiers
            the task may touch (e.g. ``["staging"]``).  Stored and
            returned but not consumed by the default TRACE pipeline.
            Business agents implementing environment-aware execution should
            read this field from the contract in their custom stage logic.
        input_refs: [PASSTHROUGH] URIs or identifiers for input artifacts
            required by the task.  Stored and returned but not consumed by
            the default TRACE pipeline.  Business agents should read this
            field to locate pre-existing artifacts before starting work.
        parent_task_id: [PASSTHROUGH] Optional parent task identifier for
            sub-task hierarchy.  Stored and returned but not consumed by
            the default TRACE pipeline.  Business agents building
            hierarchical task trees should use this for their own lineage
            tracking.
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
    # Runtime profile injection — business agents pass a profile_id to activate
    # a ProfileSpec from the platform's ProfileRegistry.
    profile_id: str | None = None
