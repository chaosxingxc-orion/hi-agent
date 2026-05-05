"""Skill registry contract types."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

_LOGGER = logging.getLogger("agent_server.contracts.skill")


@dataclass(frozen=True)
class SkillRegistration:
    """Request to register a skill."""

    tenant_id: str
    skill_id: str
    version: str
    handler_ref: str  # importable dotted path to handler callable
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.skill_id:
            missing.append("skill_id")
        if not self.version:
            missing.append("version")
        if not self.handler_ref:
            missing.append("handler_ref")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"SkillRegistration constructed without required spine fields "
                f"under posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "skill_registration_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class SkillVersion:
    """A pinned skill version."""

    tenant_id: str
    skill_id: str
    version: str
    pinned_at: str = ""

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.skill_id:
            missing.append("skill_id")
        if not self.version:
            missing.append("version")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"SkillVersion constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "skill_version_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class SkillResolution:
    """Result of resolving a skill by name for a tenant."""

    tenant_id: str
    skill_id: str
    version: str
    handler_ref: str
    is_pinned: bool = False

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.skill_id:
            missing.append("skill_id")
        if not self.version:
            missing.append("version")
        if not self.handler_ref:
            missing.append("handler_ref")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"SkillResolution constructed without required spine fields "
                f"under posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "skill_resolution_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )
