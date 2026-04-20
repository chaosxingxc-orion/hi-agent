"""Extract reusable skill candidates from successful run trajectories."""

from __future__ import annotations

import hashlib
import json as _json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from hi_agent.evolve.contracts import RunPostmortem

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway


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

    def __init__(
        self,
        min_confidence: float = 0.6,
        gateway: LLMGateway | None = None,
    ) -> None:
        """Initialize the skill extractor.

        Args:
            min_confidence: Minimum confidence threshold for emitting a candidate.
            gateway: Optional LLM gateway for LLM-based skill extraction.
        """
        self._min_confidence = min_confidence
        self._gateway = gateway

    def extract(self, postmortem: RunPostmortem) -> list[SkillCandidate]:
        """Extract skill candidates from a successful run.

        If an LLM gateway is available, attempts LLM-based extraction first.
        Falls back to heuristic extraction on any error or empty result.

        Only runs with outcome ``"completed"`` are eligible for skill extraction.
        Failed or aborted runs are skipped.

        Args:
            postmortem: Structured postmortem data for the run.

        Returns:
            List of skill candidates (may be empty).
        """
        if postmortem.outcome != "completed":
            return []

        if self._gateway is not None:
            try:
                llm_skills = self._llm_extract(postmortem)
                if llm_skills:
                    return llm_skills
            except Exception as exc:
                logger.warning(
                    "SkillExtractor._llm_extract failed, falling back to heuristics: %s", exc
                )

        return self._heuristic_extract(postmortem)

    # ------------------------------------------------------------------
    # LLM-based extraction
    # ------------------------------------------------------------------

    def _llm_extract(self, postmortem: RunPostmortem) -> list[SkillCandidate]:
        """Use LLM to analyze trajectory and extract reusable patterns."""
        from hi_agent.llm.protocol import LLMRequest

        prompt = (
            "Analyze this completed run and identify reusable patterns "
            "that could become skills:\n\n"
            f"Run: {postmortem.run_id}\n"
            f"Task Family: {postmortem.task_family}\n"
            f"Goal: {postmortem.trajectory_summary}\n"
            f"Outcome: {postmortem.outcome}\n"
            f"Stages Completed: {postmortem.stages_completed}\n"
            f"Branches Explored: {postmortem.branches_explored}\n"
            f"Quality Score: {postmortem.quality_score}\n\n"
            "Identify 0-3 reusable patterns. For each, provide:\n"
            "- name: short name\n"
            "- description: what this pattern does\n"
            "- applicability: when to use it\n"
            "- preconditions: what must be true\n\n"
            'Respond in JSON: [{"name": "...", "description": "...", '
            '"applicability": "...", "preconditions": ["..."]}]'
        )

        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert at identifying reusable execution "
                        "patterns from task trajectories."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        assert self._gateway is not None
        response = self._gateway.complete(request)
        return self._parse_llm_skills(response.content, postmortem)

    def _parse_llm_skills(self, content: str, postmortem: RunPostmortem) -> list[SkillCandidate]:
        """Parse JSON response from LLM into SkillCandidate objects."""
        try:
            items = _json.loads(content)
        except _json.JSONDecodeError as exc:
            logger.warning(
                "SkillExtractor._parse_llm_skills: failed to parse LLM response: %s", exc
            )
            return []
        if not isinstance(items, list):
            return []

        candidates: list[SkillCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if not name:
                continue
            skill_id = _make_skill_id(postmortem.task_family, name)
            candidates.append(
                SkillCandidate(
                    skill_id=skill_id,
                    name=name,
                    description=item.get("description", ""),
                    applicability_scope=item.get("applicability", postmortem.task_family),
                    preconditions=item.get("preconditions", []),
                    confidence=0.7,
                    source_run_ids=[postmortem.run_id],
                )
            )
        return candidates

    # ------------------------------------------------------------------
    # Heuristic-based extraction
    # ------------------------------------------------------------------

    def _heuristic_extract(self, postmortem: RunPostmortem) -> list[SkillCandidate]:
        """Extract skill candidates using rule-based heuristics."""
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
                        preconditions=[f"task_family == '{postmortem.task_family}'"],
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
                found.confidence = min(found.confidence + 0.05 * candidate.evidence_count, 1.0)
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
