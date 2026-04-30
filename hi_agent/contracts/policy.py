"""Policy and skill-version contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


# scope: process-internal — pure value object (policy descriptor)
@dataclass(frozen=True)
class PolicyVersionSet:
    """Policy versions bound to one run context.

    Each field pins a specific policy revision so that replays and audits
    reference the exact same rule-set that was active during the original
    run.

    Attributes:
        route_policy: Version of the route/dispatch policy.
        acceptance_policy: Version of the acceptance-criteria evaluator.
        memory_policy: Version of memory retention/eviction rules.
        evaluation_policy: Version of the post-action evaluation logic.
        task_view_policy: Version of the task-view assembly strategy.
        skill_policy: Version of the skill selection/matching policy.
    """

    route_policy: str = "route_v1"
    acceptance_policy: str = "acceptance_v1"
    memory_policy: str = "memory_v1"
    evaluation_policy: str = "evaluation_v1"
    task_view_policy: str = "task_view_v1"
    skill_policy: str = "skill_v1"


# scope: process-internal — pure value object (skill descriptor metadata)
@dataclass(frozen=True)
class SkillContentSpec:
    """Snapshot of skill content metadata for deterministic replay.

    Attributes:
        skill_id: Unique skill identifier.
        version: Semantic version string.
        checksum: Content hash for integrity verification.
        tags: Free-form classification tags.
        applicability_scope: Description of the context where this skill
            applies (e.g. ``"python_backend"``).
        preconditions: Conditions that must hold before the skill may
            execute.
        forbidden_conditions: Conditions under which the skill must NOT
            be selected.
        evidence_requirements: Evidence items that the skill expects to
            be present in the task view.
        side_effect_class: Categorisation of external side effects
            (``read_only``, ``local_write``, ``external_write``,
            ``irreversible_submit``).
        rollback_policy: Strategy if the skill's effects need reversal
            (``none``, ``compensate``, ``manual``).
        lifecycle_stage: Maturity stage of the skill (``candidate``,
            ``provisional``, ``certified``, ``deprecated``, ``retired``).
    """

    skill_id: str
    version: str
    checksum: str
    tags: list[str] = field(default_factory=list)
    applicability_scope: str = ""
    preconditions: list[str] = field(default_factory=list)
    forbidden_conditions: list[str] = field(default_factory=list)
    evidence_requirements: list[str] = field(default_factory=list)
    side_effect_class: str = "read_only"
    rollback_policy: str = "none"
    lifecycle_stage: str = "candidate"
