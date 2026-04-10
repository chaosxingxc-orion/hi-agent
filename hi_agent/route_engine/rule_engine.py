"""Minimal rule-based Route Engine for spike."""

from __future__ import annotations

from typing import Any, ClassVar

from hi_agent.contracts import deterministic_id
from hi_agent.route_engine.base import BranchProposal


class RuleRouteEngine:
    """Fixed rule route engine.

    This implementation intentionally uses one branch per stage to validate
    execution wiring before introducing probabilistic/multi-branch routing.

    When a :class:`SkillMatcher` is provided, the engine also queries for
    certified skills applicable to the current stage and task family.  Matched
    skills are emitted as additional branch proposals with higher priority
    (placed before the generic rule proposal).
    """

    STAGE_ACTIONS: ClassVar[dict[str, str]] = {
        "S1_understand": "analyze_goal",
        "S2_gather": "search_evidence",
        "S3_build": "build_draft",
        "S4_synthesize": "synthesize",
        "S5_review": "evaluate_acceptance",
    }

    # Priority constants - lower numeric value = higher priority.
    _SKILL_BASE_PRIORITY: ClassVar[int] = 10
    _SKILL_PRECONDITION_BOOST: ClassVar[int] = 5
    _RULE_PRIORITY: ClassVar[int] = 50

    def __init__(
        self,
        *,
        skill_matcher: Any | None = None,
        task_family: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the rule engine with optional skill matching.

        Parameters
        ----------
        skill_matcher:
            A :class:`~hi_agent.skill.matcher.SkillMatcher` instance.  When
            provided, ``propose()`` will also return skill-based proposals.
        task_family:
            Task family string used for skill applicability matching.
        context:
            Optional context dict passed to the skill matcher for
            precondition / forbidden-condition evaluation.
        """
        self._skill_matcher = skill_matcher
        self._task_family = task_family
        self._context: dict[str, Any] = context or {}

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        """Create branch proposals for the given stage.

        When a skill matcher is configured, certified skills that match the
        current task family and stage are returned as additional proposals
        *before* the generic rule proposal.

        Args:
          stage_id: Current stage.
          run_id: Deterministic run ID.
          seq: Monotonic action sequence.

        Returns:
          A list of branch proposals.  Skill-based proposals appear first.
        """
        proposals: list[BranchProposal] = []

        # --- Skill-based proposals ------------------------------------------
        if self._skill_matcher is not None:
            matched = self._skill_matcher.match(
                task_family=self._task_family,
                stage_id=stage_id,
                context=self._context,
            )
            for _idx, skill in enumerate(matched):
                skill_branch_id = deterministic_id(
                    run_id, stage_id, str(seq), "skill", skill.skill_id,
                )
                proposals.append(
                    BranchProposal(
                        branch_id=skill_branch_id,
                        rationale=f"skill:{skill.skill_id}(evidence={skill.evidence_count})",
                        action_kind=skill.name,
                    )
                )

        # --- Generic rule proposal ------------------------------------------
        action = self.STAGE_ACTIONS.get(stage_id, "unknown")
        branch_id = deterministic_id(run_id, stage_id, str(seq))
        proposals.append(
            BranchProposal(
                branch_id=branch_id,
                rationale=f"rule: {action}",
                action_kind=action,
            )
        )

        return proposals
