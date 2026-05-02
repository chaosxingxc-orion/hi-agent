"""Skill registry with lifecycle management and persistent storage."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from hi_agent.evolve.skill_extractor import SkillCandidate
from hi_agent.skill.validator import SkillValidator


# Embedded inside ManagedSkill.promotion_history.
# scope: process-internal — the parent ManagedSkill carries tenant_id.
@dataclass
class PromotionRecord:
    """Record of a lifecycle stage transition."""

    from_stage: str
    to_stage: str
    evidence: list[str]
    timestamp: str
    reason: str = ""


@dataclass
class ManagedSkill:
    """A skill managed through its full lifecycle.

    Lifecycle stages: candidate -> provisional -> certified -> deprecated -> retired.

    Wave 24 H1: tenant_id is part of the spine so the per-tenant registry
    overlay (W24 partition) can scope lifecycle decisions per tenant.
    """

    skill_id: str
    name: str
    description: str
    version: str = "0.1.0"
    lifecycle_stage: str = "candidate"
    applicability_scope: str = ""
    preconditions: list[str] = field(default_factory=list)
    forbidden_conditions: list[str] = field(default_factory=list)
    evidence_requirements: list[str] = field(default_factory=list)
    side_effect_class: str = "read_only"
    rollback_policy: str = "none"
    evidence_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    source_run_ids: list[str] = field(default_factory=list)
    promotion_history: list[PromotionRecord] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    tenant_id: str = ""  # scope: spine-required — enforced under strict posture

    def __post_init__(self) -> None:
        from hi_agent.config.posture import Posture

        if Posture.from_env().is_strict and not self.tenant_id:
            raise ValueError(
                "ManagedSkill.tenant_id required under research/prod posture"
            )


class SkillRegistry:
    """Manages the full skill lifecycle with persistent storage.

    Skills flow: Candidate -> Provisional -> Certified -> Deprecated -> Retired.
    Each transition requires evidence and validation.
    """

    def __init__(self, storage_dir: str = ".hi_agent/skills") -> None:
        """Initialize SkillRegistry."""
        self._skills: dict[str, ManagedSkill] = {}
        self._storage_dir = storage_dir
        self._validator = SkillValidator()

    def register_candidate(self, candidate: SkillCandidate) -> ManagedSkill:
        """Register a new skill candidate from evolve.

        If the skill_id already exists, merges evidence into the existing skill.

        Args:
            candidate: A SkillCandidate produced by the skill extractor.

        Returns:
            The registered or updated ManagedSkill.
        """
        now = datetime.now(UTC).isoformat()

        if candidate.skill_id in self._skills:
            existing = self._skills[candidate.skill_id]
            existing.evidence_count += candidate.evidence_count
            for rid in candidate.source_run_ids:
                if rid not in existing.source_run_ids:
                    existing.source_run_ids.append(rid)
            existing.updated_at = now
            return existing

        skill = ManagedSkill(
            skill_id=candidate.skill_id,
            name=candidate.name,
            description=candidate.description,
            lifecycle_stage="candidate",
            applicability_scope=candidate.applicability_scope,
            preconditions=list(candidate.preconditions),
            evidence_count=candidate.evidence_count,
            source_run_ids=list(candidate.source_run_ids),
            created_at=now,
            updated_at=now,
        )
        self._skills[candidate.skill_id] = skill
        return skill

    def promote(
        self,
        skill_id: str,
        to_stage: str,
        evidence: list[str] | None = None,
    ) -> ManagedSkill:
        """Promote skill to next lifecycle stage.

        Validates that the transition is legal and that the skill meets
        the promotion criteria.

        Args:
            skill_id: The skill to promote.
            to_stage: Target lifecycle stage.
            evidence: Supporting evidence for the promotion.

        Returns:
            The updated ManagedSkill.

        Raises:
            KeyError: If skill_id is not found.
            ValueError: If the transition is illegal or criteria are not met.
        """
        skill = self._require(skill_id)
        evidence = evidence or []

        allowed, reason = self._validator.can_promote(skill, to_stage)
        if not allowed:
            raise ValueError(
                f"Cannot promote '{skill_id}' from '{skill.lifecycle_stage}' "
                f"to '{to_stage}': {reason}"
            )

        now = datetime.now(UTC).isoformat()
        record = PromotionRecord(
            from_stage=skill.lifecycle_stage,
            to_stage=to_stage,
            evidence=evidence,
            timestamp=now,
        )
        skill.promotion_history.append(record)
        skill.lifecycle_stage = to_stage
        skill.updated_at = now
        return skill

    def deprecate(self, skill_id: str, reason: str) -> ManagedSkill:
        """Deprecate a certified skill.

        Args:
            skill_id: The skill to deprecate.
            reason: Why the skill is being deprecated.

        Returns:
            The updated ManagedSkill.

        Raises:
            KeyError: If skill_id is not found.
            ValueError: If the skill is not in a deprecable stage.
        """
        skill = self._require(skill_id)
        if skill.lifecycle_stage != "certified":
            raise ValueError(
                f"Can only deprecate certified skills, '{skill_id}' is '{skill.lifecycle_stage}'"
            )

        now = datetime.now(UTC).isoformat()
        record = PromotionRecord(
            from_stage="certified",
            to_stage="deprecated",
            evidence=[],
            timestamp=now,
            reason=reason,
        )
        skill.promotion_history.append(record)
        skill.lifecycle_stage = "deprecated"
        skill.updated_at = now
        return skill

    def retire(self, skill_id: str) -> ManagedSkill:
        """Retire a deprecated skill.

        Args:
            skill_id: The skill to retire.

        Returns:
            The updated ManagedSkill.

        Raises:
            KeyError: If skill_id is not found.
            ValueError: If the skill is not deprecated.
        """
        skill = self._require(skill_id)
        if skill.lifecycle_stage != "deprecated":
            raise ValueError(
                f"Can only retire deprecated skills, '{skill_id}' is '{skill.lifecycle_stage}'"
            )

        now = datetime.now(UTC).isoformat()
        record = PromotionRecord(
            from_stage="deprecated",
            to_stage="retired",
            evidence=[],
            timestamp=now,
        )
        skill.promotion_history.append(record)
        skill.lifecycle_stage = "retired"
        skill.updated_at = now
        return skill

    def get(self, skill_id: str, tenant_id: str | None = None) -> ManagedSkill | None:
        """Look up a skill by ID, scoped to *tenant_id* under strict posture.

        W31 (T-5'): under research/prod posture an unscoped ``get`` raises
        ``ValueError`` because it would otherwise expose any tenant's skill
        to any caller.  Under dev posture an unscoped lookup logs a WARNING
        and returns the skill regardless of its tenant_id (legacy compat).

        Args:
            skill_id: The skill identifier to look up.
            tenant_id: Owning tenant.  When ``None`` and posture is strict,
                raises ValueError.  When provided, skills owned by a different
                tenant are returned as ``None`` (object-level 404 semantics).

        Returns:
            The ManagedSkill or ``None`` if not found / cross-tenant.
        """
        self._enforce_tenant_scope("get", tenant_id)
        skill = self._skills.get(skill_id)
        if skill is None:
            return None
        if tenant_id is not None and skill.tenant_id != tenant_id:
            return None
        return skill

    def list_by_stage(
        self, stage: str, tenant_id: str | None = None
    ) -> list[ManagedSkill]:
        """List all skills at a given lifecycle stage, scoped to *tenant_id*.

        W31 (T-5'): under research/prod posture ``tenant_id`` is required.
        """
        self._enforce_tenant_scope("list_by_stage", tenant_id)
        rows = [s for s in self._skills.values() if s.lifecycle_stage == stage]
        if tenant_id is not None:
            rows = [s for s in rows if s.tenant_id == tenant_id]
        return rows

    def list_certified(self, tenant_id: str | None = None) -> list[ManagedSkill]:
        """List all certified skills, scoped to *tenant_id* (W31 T-5')."""
        return self.list_by_stage("certified", tenant_id=tenant_id)

    def list_applicable(
        self,
        task_family: str,
        stage_id: str,
        tenant_id: str | None = None,
    ) -> list[ManagedSkill]:
        """Find certified skills applicable to given context, scoped by tenant.

        A skill is applicable if its applicability_scope matches the
        task_family (exact match or wildcard ``"*"``).

        W31 (T-5'): under research/prod posture ``tenant_id`` is required so
        the matcher cannot pull a skill from another tenant's registry into
        the current run's plan.

        Args:
            task_family: The task family to match against.
            stage_id: The current stage (reserved for future filtering).
            tenant_id: Owning tenant; required under strict posture.

        Returns:
            List of applicable certified skills, sorted by evidence_count
            descending.
        """
        results: list[ManagedSkill] = []
        for skill in self.list_certified(tenant_id=tenant_id):
            scope = skill.applicability_scope
            if scope == "*" or scope == task_family:
                results.append(skill)
        results.sort(key=lambda s: s.evidence_count, reverse=True)
        return results

    def _enforce_tenant_scope(self, method: str, tenant_id: str | None) -> None:
        """Raise under strict posture when *tenant_id* is missing.

        Under dev posture an unscoped read logs a WARNING but is permitted
        (legacy callers continue to work).  Under research/prod the call must
        be tenant-scoped or the read is a defect.
        """
        if tenant_id is not None:
            return
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if posture.is_strict:
            raise ValueError(
                f"SkillRegistry.{method} requires tenant_id under "
                f"{posture.value} posture (Rule 12 / W31 T-5'); "
                "unscoped reads expose every tenant's skills."
            )
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "SkillRegistry.%s called without tenant_id under dev posture; "
            "result includes every tenant's skills (W31 T-5').",
            method,
        )

    def save(self) -> None:
        """Persist registry to disk as JSON."""
        os.makedirs(self._storage_dir, exist_ok=True)
        path = os.path.join(self._storage_dir, "registry.json")
        data: list[dict] = []  # type: ignore[type-arg]  expiry_wave: permanent
        for skill in self._skills.values():
            d = asdict(skill)
            # Convert PromotionRecord dicts are already plain dicts from asdict
            data.append(d)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self) -> None:
        """Load registry from disk."""
        path = os.path.join(self._storage_dir, "registry.json")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._skills.clear()
        for d in data:
            promo_dicts = d.pop("promotion_history", [])
            promos = [PromotionRecord(**p) for p in promo_dicts]
            skill = ManagedSkill(**d, promotion_history=promos)
            self._skills[skill.skill_id] = skill

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, skill_id: str) -> ManagedSkill:
        """Get a skill or raise KeyError."""
        skill = self._skills.get(skill_id)
        if skill is None:
            raise KeyError(f"Skill '{skill_id}' not found in registry")
        return skill
