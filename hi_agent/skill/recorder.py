"""Record skill usage during runs for the feedback loop."""

from __future__ import annotations

from typing import Any

from hi_agent.skill.registry import SkillRegistry


class SkillUsageRecorder:
    """Records skill usage during run execution for feedback loop.

    After a run, feeds usage data back to registry to update evidence counts.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        # run_id -> list of skill_ids used in that run
        self._run_skills: dict[str, list[str]] = {}

    def record_usage(
        self, skill_id: str, run_id: str, success: bool
    ) -> None:
        """Record that a skill was used in a run with given outcome.

        Updates the skill's evidence_count, success_count or failure_count,
        and tracks the run_id in source_run_ids.

        Args:
            skill_id: The skill that was used.
            run_id: The run in which it was used.
            success: Whether the usage was successful.

        Raises:
            KeyError: If the skill_id is not in the registry.
        """
        skill = self._registry.get(skill_id)
        if skill is None:
            raise KeyError(f"Skill '{skill_id}' not found in registry")

        skill.evidence_count += 1
        if success:
            skill.success_count += 1
        else:
            skill.failure_count += 1

        if run_id not in skill.source_run_ids:
            skill.source_run_ids.append(run_id)

        # Track run -> skills mapping
        if run_id not in self._run_skills:
            self._run_skills[run_id] = []
        if skill_id not in self._run_skills[run_id]:
            self._run_skills[run_id].append(skill_id)

    def get_usage_stats(self, skill_id: str) -> dict[str, Any]:
        """Get usage statistics for a skill.

        Args:
            skill_id: The skill to query.

        Returns:
            Dict with evidence_count, success_count, failure_count,
            and success_rate.

        Raises:
            KeyError: If the skill_id is not in the registry.
        """
        skill = self._registry.get(skill_id)
        if skill is None:
            raise KeyError(f"Skill '{skill_id}' not found in registry")

        total = skill.success_count + skill.failure_count
        rate = skill.success_count / total if total > 0 else 0.0

        return {
            "skill_id": skill_id,
            "evidence_count": skill.evidence_count,
            "success_count": skill.success_count,
            "failure_count": skill.failure_count,
            "success_rate": rate,
        }

    def get_run_skills(self, run_id: str) -> list[str]:
        """Get all skill IDs used in a given run.

        Args:
            run_id: The run to query.

        Returns:
            List of skill IDs (may be empty).
        """
        return list(self._run_skills.get(run_id, []))
