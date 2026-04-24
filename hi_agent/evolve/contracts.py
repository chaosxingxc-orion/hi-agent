"""Data contracts for the Evolve subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class EvolveChange:
    """A single change proposed by evolve.

    Attributes:
        change_type: Category of change (skill_candidate, routing_heuristic,
            knowledge_update, baseline_update).
        target_id: Identifier for the entity being changed.
        description: Human-readable description of the proposed change.
        confidence: Confidence score between 0.0 and 1.0.
        evidence_refs: References to supporting evidence (run IDs, etc.).
    """

    change_type: str
    target_id: str
    description: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class EvolveMetrics:
    """Metrics from evolve execution.

    Attributes:
        runs_analyzed: Number of runs analyzed.
        llm_calls_used: Number of LLM calls consumed.
        tokens_used: Total tokens consumed.
        skill_candidates_found: Number of skill candidates extracted.
        regressions_detected: Number of regressions detected.
    """

    runs_analyzed: int = 0
    llm_calls_used: int = 0
    tokens_used: int = 0
    skill_candidates_found: int = 0
    regressions_detected: int = 0


@dataclass
class EvolveResult:
    """Result of one evolve execution.

    Attributes:
        trigger: The trigger mode that initiated this evolve.
        change_scope: The scope of changes produced.
        changes: List of proposed changes.
        metrics: Execution metrics.
        run_ids_analyzed: IDs of runs analyzed.
        timestamp: ISO-8601 timestamp of when the evolve completed.
    """

    trigger: str
    change_scope: str
    changes: list[EvolveChange]
    metrics: EvolveMetrics
    run_ids_analyzed: list[str]
    timestamp: str


@dataclass
class RunPostmortem:
    """Structured postmortem data for a completed run.

    Attributes:
        run_id: Unique identifier for the run.
        task_id: Identifier for the task that was executed.
        task_family: Category/family of the task.
        outcome: Final outcome (completed, failed, aborted).
        stages_completed: List of stage names that completed successfully.
        stages_failed: List of stage names that failed.
        branches_explored: Total number of branches explored.
        branches_pruned: Number of branches pruned.
        total_actions: Total number of actions executed.
        failure_codes: Standard failure codes encountered.
        duration_seconds: Wall-clock duration of the run.
        quality_score: Optional quality assessment score (0.0-1.0).
        efficiency_score: Optional efficiency assessment score (0.0-1.0).
        trajectory_summary: Textual summary of the trajectory taken.
        human_feedback: Feedback received from human gates.
    """

    run_id: str
    task_id: str
    task_family: str
    outcome: str
    stages_completed: list[str]
    stages_failed: list[str]
    branches_explored: int
    branches_pruned: int
    total_actions: int
    failure_codes: list[str]
    duration_seconds: float
    quality_score: float | None = None
    efficiency_score: float | None = None
    trajectory_summary: str = ""
    human_feedback: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    policy_versions: dict[str, str] = field(default_factory=dict)
    project_id: str = ""


@dataclass
class CalibrationSignal:
    """Cost/quality signal for TierRouter calibration."""

    project_id: str
    run_id: str
    model: str
    tier: str
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    quality_score: float = 0.0
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ProjectPostmortem:
    """Aggregated postmortem for a completed research project.

    Produced by EvolveEngine.on_project_completed() after all runs finish.
    This is a platform-level record; downstream populates domain fields
    (hypothesis_outcomes, failed_assumptions) via the postmortem API.
    """

    project_id: str
    run_ids: list[str]
    backtrack_count: int = 0
    hypothesis_outcomes: list[str] = field(default_factory=list)
    failed_assumptions: list[str] = field(default_factory=list)
    cost_by_phase: dict[str, float] = field(default_factory=dict)
    accepted_artifact_ids: list[str] = field(default_factory=list)
    rejected_artifact_ids: list[str] = field(default_factory=list)
    skill_deltas: list[str] = field(default_factory=list)
    routing_deltas: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
