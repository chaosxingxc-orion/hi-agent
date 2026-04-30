"""Memory-layer summary contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


# scope: process-internal — memory primitive (CLAUDE.md Rule 12 carve-out for RunIndex/StageSummary)
@dataclass
class StageSummary:
    """Compressed L1 summary for one stage."""

    stage_id: str
    stage_name: str
    findings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    outcome: str = "active"
    artifact_ids: list[str] = field(default_factory=list)


# scope: process-internal — memory primitive (CLAUDE.md Rule 12 carve-out for RunIndex/StageSummary)
@dataclass
class RunIndex:
    """Compact navigation summary for a run."""

    run_id: str
    task_goal_summary: str = ""
    stages_status: list[dict] = field(default_factory=list)
    current_stage: str = ""
    key_decisions: list[str] = field(default_factory=list)
