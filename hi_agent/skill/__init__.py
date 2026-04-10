"""Skill lifecycle management system.

Provides registry, matching, validation, usage recording, observation,
versioning, and evolution for the full skill lifecycle:
Candidate -> Provisional -> Certified -> Deprecated -> Retired.
"""

from __future__ import annotations

from hi_agent.skill.definition import SkillDefinition
from hi_agent.skill.evolver import (
    EvolutionReport,
    SkillAnalysis,
    SkillEvolver,
    SkillPattern,
)
from hi_agent.skill.loader import SkillLoader, SkillPrompt
from hi_agent.skill.matcher import SkillMatcher
from hi_agent.skill.observer import SkillMetrics, SkillObservation, SkillObserver
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import ManagedSkill, PromotionRecord, SkillRegistry
from hi_agent.skill.validator import SkillValidator
from hi_agent.skill.version import SkillVersionManager, SkillVersionRecord

__all__ = [
    "EvolutionReport",
    "ManagedSkill",
    "PromotionRecord",
    "SkillAnalysis",
    "SkillDefinition",
    "SkillEvolver",
    "SkillLoader",
    "SkillMatcher",
    "SkillMetrics",
    "SkillObservation",
    "SkillObserver",
    "SkillPattern",
    "SkillPrompt",
    "SkillRegistry",
    "SkillUsageRecorder",
    "SkillValidator",
    "SkillVersionManager",
    "SkillVersionRecord",
]
