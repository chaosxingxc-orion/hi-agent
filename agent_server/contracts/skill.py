"""Skill registry contract types."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillRegistration:
    """Request to register a skill."""

    tenant_id: str
    skill_id: str
    version: str
    handler_ref: str  # importable dotted path to handler callable
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkillVersion:
    """A pinned skill version."""

    tenant_id: str
    skill_id: str
    version: str
    pinned_at: str = ""


@dataclass(frozen=True)
class SkillResolution:
    """Result of resolving a skill by name for a tenant."""

    tenant_id: str
    skill_id: str
    version: str
    handler_ref: str
    is_pinned: bool = False
