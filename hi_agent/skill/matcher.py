"""Match certified skills to execution context."""

from __future__ import annotations

from typing import Any

from hi_agent.skill.registry import ManagedSkill, SkillRegistry


class SkillMatcher:
    """Matches certified skills to current execution context.

    Checks: applicability_scope matches task_family,
    preconditions are met, forbidden_conditions are not present.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        """Initialize SkillMatcher."""
        self._registry = registry

    def match(
        self,
        task_family: str,
        stage_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[ManagedSkill]:
        """Find matching skills, ranked by evidence_count.

        A skill matches when:
        1. It is certified.
        2. Its applicability_scope matches the task_family (or is ``"*"``).
        3. All preconditions are satisfied (if context is provided).
        4. No forbidden_conditions are present (if context is provided).

        Args:
            task_family: The task family to match against.
            stage_id: The current stage identifier.
            context: Optional dict of context values for condition checks.

        Returns:
            List of matching ManagedSkill objects, sorted by evidence_count
            descending.
        """
        ctx = context or {}
        candidates = self._registry.list_applicable(task_family, stage_id)
        results: list[ManagedSkill] = []
        for skill in candidates:
            if not self.check_preconditions(skill, ctx):
                continue
            if not self.check_forbidden(skill, ctx):
                continue
            results.append(skill)
        return results

    def check_preconditions(self, skill: ManagedSkill, context: dict[str, Any]) -> bool:
        """Check that all preconditions are met.

        Each precondition is a string of the form ``"key == 'value'"`` or
        simply a key name. If the context is empty and there are
        preconditions, they are assumed met (caller did not provide data).

        Args:
            skill: The skill whose preconditions to check.
            context: The context dict.

        Returns:
            True if all preconditions are satisfied.
        """
        if not context:
            return True
        return all(_evaluate_condition(cond, context) for cond in skill.preconditions)

    def check_forbidden(self, skill: ManagedSkill, context: dict[str, Any]) -> bool:
        """Check that no forbidden conditions are present.

        Returns True if the skill is safe to use (none of the forbidden
        conditions are met).

        Args:
            skill: The skill whose forbidden conditions to check.
            context: The context dict.

        Returns:
            True if no forbidden conditions are triggered.
        """
        if not context:
            return True
        return all(not _evaluate_condition(cond, context) for cond in skill.forbidden_conditions)


def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a simple condition string against a context dict.

    Supported forms:
    - ``"key == 'value'"`` -- equality check
    - ``"key"`` -- truthy check (key exists and is truthy)

    Args:
        condition: The condition string.
        context: The context dict.

    Returns:
        True if the condition holds.
    """
    if "==" in condition:
        parts = condition.split("==", 1)
        key = parts[0].strip()
        expected = parts[1].strip().strip("'\"")
        return str(context.get(key, "")) == expected
    # Simple truthy check
    key = condition.strip()
    return bool(context.get(key))
