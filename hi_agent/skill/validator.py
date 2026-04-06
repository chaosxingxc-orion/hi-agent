"""Validate skill promotion criteria and lifecycle transitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.skill.registry import ManagedSkill

# Legal transitions in the skill lifecycle.
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"provisional"},
    "provisional": {"certified"},
    "certified": {"deprecated"},
    "deprecated": {"retired"},
    "retired": set(),
}


class SkillValidator:
    """Validates whether a skill can be promoted to the next stage.

    Rules:
    - candidate -> provisional: evidence_count >= min_provisional_evidence
    - provisional -> certified: evidence_count >= min_certified_evidence,
      success_rate >= min_certified_success_rate
    - certified -> deprecated: explicit reason required (handled by registry)
    - deprecated -> retired: no additional criteria (active run check is
      the caller's responsibility)
    """

    def __init__(
        self,
        min_provisional_evidence: int = 2,
        min_certified_evidence: int = 5,
        min_certified_success_rate: float = 0.8,
    ) -> None:
        self._min_provisional_evidence = min_provisional_evidence
        self._min_certified_evidence = min_certified_evidence
        self._min_certified_success_rate = min_certified_success_rate

    def can_promote(
        self, skill: ManagedSkill, to_stage: str
    ) -> tuple[bool, str]:
        """Check if promotion is valid.

        Args:
            skill: The skill to evaluate.
            to_stage: The target lifecycle stage.

        Returns:
            A tuple of (allowed, reason). If allowed is False, reason
            explains why.
        """
        if not self.validate_transition(skill.lifecycle_stage, to_stage):
            return False, (
                f"Transition from '{skill.lifecycle_stage}' to "
                f"'{to_stage}' is not a legal lifecycle transition"
            )

        if skill.lifecycle_stage == "candidate" and to_stage == "provisional":
            if skill.evidence_count < self._min_provisional_evidence:
                return False, (
                    f"Need at least {self._min_provisional_evidence} evidence "
                    f"runs, have {skill.evidence_count}"
                )

        if skill.lifecycle_stage == "provisional" and to_stage == "certified":
            if skill.evidence_count < self._min_certified_evidence:
                return False, (
                    f"Need at least {self._min_certified_evidence} evidence "
                    f"runs, have {skill.evidence_count}"
                )
            total = skill.success_count + skill.failure_count
            if total == 0:
                return False, "No usage data to compute success rate"
            rate = skill.success_count / total
            if rate < self._min_certified_success_rate:
                return False, (
                    f"Success rate {rate:.2f} is below minimum "
                    f"{self._min_certified_success_rate}"
                )

        return True, "Promotion allowed"

    def validate_transition(self, from_stage: str, to_stage: str) -> bool:
        """Check if a lifecycle transition is legal.

        Args:
            from_stage: Current lifecycle stage.
            to_stage: Target lifecycle stage.

        Returns:
            True if the transition is allowed.
        """
        allowed = _LEGAL_TRANSITIONS.get(from_stage, set())
        return to_stage in allowed
