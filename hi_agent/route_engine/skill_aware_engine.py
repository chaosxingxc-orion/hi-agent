"""Skill-aware route engine wrapper."""

from __future__ import annotations

from typing import Any

from hi_agent.contracts import deterministic_id
from hi_agent.route_engine.base import BranchProposal
from hi_agent.skill.matcher import SkillMatcher


class SkillAwareRouteEngine:
    """Route engine that prioritises certified skills.

    Wraps an inner engine and enhances proposals with skill matching:

    1. Query :class:`SkillMatcher` for applicable skills.
    2. Generate skill-based proposals.
    3. Merge with inner engine proposals.
    4. Rank by skill confidence + evidence count.
    """

    def __init__(
        self,
        inner: Any,
        skill_matcher: SkillMatcher,
        task_family: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the skill-aware engine.

        Parameters
        ----------
        inner:
            An object satisfying the :class:`RouteEngine` protocol
            (must expose ``propose(stage_id, run_id, seq)``).
        skill_matcher:
            Matcher used to find certified skills for the current context.
        task_family:
            Task family string for skill applicability matching.
        context:
            Optional context dict for precondition evaluation.
        """
        self._inner = inner
        self._skill_matcher = skill_matcher
        self._task_family = task_family
        self._context: dict[str, Any] = context or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        """Propose branches, prioritising skill-matched ones.

        Skill proposals are generated first, then merged with the inner
        engine's proposals.  The final list is ranked so that skill-based
        proposals with higher evidence counts appear before generic ones.

        Args:
            stage_id: Current stage identifier.
            run_id: Deterministic run identifier.
            seq: Monotonic action sequence number.

        Returns:
            Merged and ranked list of :class:`BranchProposal` objects.
        """
        skill_props = self._skill_proposals(stage_id, run_id, seq)
        inner_props = self._inner.propose(stage_id, run_id, seq)
        return self._merge_and_rank(skill_props, inner_props)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _skill_proposals(
        self, stage_id: str, run_id: str, seq: int,
    ) -> list[BranchProposal]:
        """Build proposals from matched certified skills."""
        matched = self._skill_matcher.match(
            task_family=self._task_family,
            stage_id=stage_id,
            context=self._context,
        )
        proposals: list[BranchProposal] = []
        for skill in matched:
            branch_id = deterministic_id(
                run_id, stage_id, str(seq), "skill", skill.skill_id,
            )
            proposals.append(
                BranchProposal(
                    branch_id=branch_id,
                    rationale=(
                        f"skill:{skill.skill_id}"
                        f"(evidence={skill.evidence_count})"
                    ),
                    action_kind=skill.name,
                )
            )
        return proposals

    def _merge_and_rank(
        self,
        skill_props: list[BranchProposal],
        inner_props: list[BranchProposal],
    ) -> list[BranchProposal]:
        """Merge skill and inner proposals, ranking skill-based ones first.

        Ordering strategy:
        - Skill proposals come first, preserving their evidence-count order
          (the matcher already sorts by evidence_count descending).
        - Inner proposals follow in their original order.
        - Duplicates (same branch_id) are removed, keeping the first seen.
        """
        seen: set[str] = set()
        merged: list[BranchProposal] = []
        for prop in (*skill_props, *inner_props):
            if prop.branch_id not in seen:
                seen.add(prop.branch_id)
                merged.append(prop)
        return merged
