"""Extract reusable skill candidates from successful run trajectories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


from hi_agent.evolve.contracts import RunPostmortem


@dataclass
class SkillCandidate:
    """A candidate skill extracted from successful trajectories.

    Attributes:
        skill_id: Unique identifier for this skill candidate.
        name: Human-readable name.
        description: What the skill does and when to apply it.
        applicability_scope: Task families or contexts where this skill applies.
        preconditions: Conditions that must hold before applying the skill.
        evidence_count: Number of runs that produced this pattern.
        confidence: Confidence score (0.0-1.0).
        source_run_ids: Run IDs that contributed evidence for this candidate.
        lifecycle_stage: Current lifecycle stage (candidate, validated, promoted).
    """

    skill_id: str
    name: str
    description: str
    applicability_scope: str
    preconditions: list[str]
    evidence_count: int = 1
    confidence: float = 0.5
    source_run_ids: list[str] = field(default_factory=list)
    lifecycle_stage: str = "candidate"


class SkillExtractor:
    """Extracts reusable skill candidates from successful run trajectories.

    Only successful runs (outcome == "completed") with a minimum quality score
    are considered.
    """

    def __init__(self, min_confidence: float = 0.6) -> None:
        """Initialize the skill extractor.

        Args:
            min_confidence: Minimum confidence threshold for emitting a candidate.
        """
        self._min_confidence = min_confidence

    def extract(self, postmortem: RunPostmortem) -> list[SkillCandidate]:
        """Extract skill candidates from a successful run.

        Only runs with outcome ``"completed"`` are eligible for skill extraction.
        Failed or aborted runs are skipped.

        Args:
            postmortem: Structured postmortem data for the run.

        Returns:
            List of skill candidates (may be empty).
        """
        if postmortem.outcome != "completed":
            return []

        candidates: list[SkillCandidate] = []

        # Heuristic 1: efficient multi-stage completion is a skill pattern.
        if len(postmortem.stages_completed) >= 3 and not postmortem.stages_failed:
            skill_id = _make_skill_id(postmortem.task_family, "full_pipeline")
            confidence = 0.5
            if postmortem.quality_score is not None:
                confidence = max(confidence, postmortem.quality_score)
            if confidence >= self._min_confidence:
                candidates.append(
                    SkillCandidate(
                        skill_id=skill_id,
                        name=f"Pipeline:{postmortem.task_family}",
                        description=(
                            f"Full pipeline completion for task family "
                            f"'{postmortem.task_family}' across stages: "
                            f"{', '.join(postmortem.stages_completed)}."
                        ),
                        applicability_scope=postmortem.task_family,
                        preconditions=[
                            f"task_family == '{postmortem.task_family}'"
                        ],
                        confidence=confidence,
                        source_run_ids=[postmortem.run_id],
                    )
                )

        # Heuristic 2: low branch pruning with good outcome.
        if (
            postmortem.branches_explored >= 2
            and postmortem.branches_pruned == 0
            and postmortem.outcome == "completed"
        ):
            skill_id = _make_skill_id(postmortem.task_family, "efficient_exploration")
            confidence = 0.6
            if postmortem.efficiency_score is not None:
                confidence = max(confidence, postmortem.efficiency_score)
            if confidence >= self._min_confidence:
                candidates.append(
                    SkillCandidate(
                        skill_id=skill_id,
                        name=f"EfficientExplore:{postmortem.task_family}",
                        description=(
                            f"Efficient branch exploration "
                            f"({postmortem.branches_explored} branches, 0 pruned) "
                            f"for task family '{postmortem.task_family}'."
                        ),
                        applicability_scope=postmortem.task_family,
                        preconditions=[
                            f"task_family == '{postmortem.task_family}'",
                            "branches_available >= 2",
                        ],
                        confidence=confidence,
                        source_run_ids=[postmortem.run_id],
                    )
                )

        return candidates

    def merge_candidates(
        self,
        existing: list[SkillCandidate],
        new: list[SkillCandidate],
    ) -> list[SkillCandidate]:
        """Merge new candidates with existing, deduplicating by skill_id.

        When a duplicate is found the evidence count is incremented, confidence
        is raised, and source run IDs are merged.

        Args:
            existing: Previously accumulated candidates.
            new: Newly extracted candidates.

        Returns:
            Merged list of candidates.
        """
        index: dict[str, SkillCandidate] = {c.skill_id: c for c in existing}

        for candidate in new:
            if candidate.skill_id in index:
                found = index[candidate.skill_id]
                found.evidence_count += candidate.evidence_count
                found.confidence = min(
                    found.confidence + 0.05 * candidate.evidence_count, 1.0
                )
                for rid in candidate.source_run_ids:
                    if rid not in found.source_run_ids:
                        found.source_run_ids.append(rid)
            else:
                index[candidate.skill_id] = candidate

        return list(index.values())


def _make_skill_id(task_family: str, pattern: str) -> str:
    """Generate a deterministic skill ID from family and pattern.

    Args:
        task_family: The task family string.
        pattern: The pattern name.

    Returns:
        A stable short hash-based ID.
    """
    raw = f"{task_family}::{pattern}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"skill_{digest}"
