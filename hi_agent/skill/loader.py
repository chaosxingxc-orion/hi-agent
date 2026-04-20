"""Skill loader with multi-source discovery and token budget optimization.

Discovery sources (in precedence order, higher overrides lower):

1. Built-in skills (bundled with hi-agent)
2. User skills (``~/.hi_agent/skills/``)
3. Project skills (``.hi_agent/skills/``)
4. Generated skills (from evolve / instinct system)

Loading modes (OpenClaw pattern):

- **Full**: Complete prompt content injected into context
- **Compact**: Name + description + path only (model reads file when needed)
- **Auto**: Full if within budget, compact if over budget

Token budget management:

- Default budget: 10 000 tokens for all skills combined
- Binary search to find largest set of full-format skills that fits
- Remaining skills in compact format
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from hi_agent.skill.definition import SkillDefinition, _estimate_tokens

# ---------------------------------------------------------------------------
# SkillPrompt — token-optimised prompt ready for LLM injection
# ---------------------------------------------------------------------------


@dataclass
class SkillPrompt:
    """Token-optimized skill prompt ready for LLM injection."""

    full_skills: list[str] = field(default_factory=list)
    compact_skills: list[str] = field(default_factory=list)
    total_tokens: int = 0
    budget_tokens: int = 0
    full_count: int = 0
    compact_count: int = 0
    truncated_count: int = 0  # Skills that didn't fit at all

    def to_prompt_string(self) -> str:
        """Format as a single string for system prompt injection."""
        sections: list[str] = []

        if self.full_skills:
            sections.append("# Available Skills (full)\n")
            sections.append("\n\n".join(self.full_skills))

        if self.compact_skills:
            if sections:
                sections.append("")
            sections.append("# Additional Skills (use file path to read details)\n")
            sections.append("\n".join(self.compact_skills))

        if self.truncated_count > 0:
            sections.append(f"\n({self.truncated_count} more skill(s) omitted due to token budget)")

        return "\n".join(sections)


# ---------------------------------------------------------------------------
# SkillLoader — multi-source discovery + budget-aware loading
# ---------------------------------------------------------------------------

_SKILL_FILENAME = "SKILL.md"


class SkillLoader:
    """Discovers and loads skills from multiple sources."""

    def __init__(
        self,
        search_dirs: list[str] | None = None,
        max_skills_in_prompt: int = 50,
        max_prompt_tokens: int = 10_000,
    ) -> None:
        """Initialize SkillLoader."""
        self._search_dirs = search_dirs or []
        self._skills: dict[str, SkillDefinition] = {}
        self._max_skills = max_skills_in_prompt
        self._max_tokens = max_prompt_tokens
        self._snapshot_version: int = 0

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> int:
        """Scan all search_dirs for SKILL.md files.

        Higher-index dirs override lower-index (precedence).

        Returns:
            Count of skills discovered.
        """
        for dir_path in self._search_dirs:
            if os.path.isdir(dir_path):
                self.load_dir(dir_path, source="file")
        return len(self._skills)

    def load_dir(self, dir_path: str, source: str = "file") -> list[SkillDefinition]:
        """Load all skills from *dir_path* (scan subdirs for SKILL.md).

        Each immediate subdirectory containing a ``SKILL.md`` file is treated
        as a skill.  A ``SKILL.md`` directly in *dir_path* is also loaded.

        Returns:
            List of loaded :class:`SkillDefinition` objects.
        """
        loaded: list[SkillDefinition] = []

        # Check for SKILL.md directly in dir_path
        direct = os.path.join(dir_path, _SKILL_FILENAME)
        if os.path.isfile(direct):
            skill = self._load_file(direct, source)
            if skill is not None:
                loaded.append(skill)

        # Check immediate subdirectories
        try:
            entries = os.listdir(dir_path)
        except OSError:
            return loaded

        for entry in sorted(entries):
            sub = os.path.join(dir_path, entry)
            if not os.path.isdir(sub):
                continue
            skill_file = os.path.join(sub, _SKILL_FILENAME)
            if os.path.isfile(skill_file):
                skill = self._load_file(skill_file, source)
                if skill is not None:
                    loaded.append(skill)

        return loaded

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_skill(self, skill_id: str, version: str = "champion") -> SkillDefinition | None:
        """Look up a skill by ID, optionally resolving a specific version.

        Args:
            skill_id: The base skill identifier.
            version: One of:
                - ``"champion"`` (default) — returns the plain *skill_id* entry,
                  which is the current production (champion) version.
                - ``"challenger"`` — looks up ``{skill_id}@challenger`` first;
                  falls back to plain *skill_id* if absent.
                - ``"v{N}"`` (e.g. ``"v2"``) — looks up ``{skill_id}@v{N}``
                  first; falls back to plain *skill_id* if absent.

        Returns:
            The matching :class:`SkillDefinition`, or ``None`` if not found.
        """
        if version == "champion":
            return self._skills.get(skill_id)
        # Version-qualified key convention: "{skill_id}@{version}"
        qualified = f"{skill_id}@{version}"
        result = self._skills.get(qualified)
        if result is not None:
            return result
        # Fallback to plain skill_id
        return self._skills.get(skill_id)

    def list_skills(self, eligible_only: bool = True) -> list[SkillDefinition]:
        """Return all discovered skills, optionally filtered by eligibility."""
        skills = list(self._skills.values())
        if eligible_only:
            skills = [s for s in skills if s.check_eligibility()[0]]
        return skills

    def list_by_tag(self, tag: str) -> list[SkillDefinition]:
        """Return skills that carry *tag*."""
        return [s for s in self._skills.values() if tag in s.tags]

    def list_by_stage(self, lifecycle_stage: str) -> list[SkillDefinition]:
        """Return skills at the given lifecycle stage."""
        return [s for s in self._skills.values() if s.lifecycle_stage == lifecycle_stage]

    # ------------------------------------------------------------------
    # Prompt building (token-optimised, OpenClaw binary-search pattern)
    # ------------------------------------------------------------------

    def build_prompt(self, budget_tokens: int | None = None) -> SkillPrompt:
        """Build token-optimized prompt for all eligible skills.

        Strategy (OpenClaw binary search pattern):

        1. Sort skills by confidence (highest first).
        2. Try full format for all — check budget.
        3. If over budget, binary search for max full-format count.
        4. Remaining skills in compact format.
        5. If still over budget, truncate compact list.
        """
        budget = budget_tokens if budget_tokens is not None else self._max_tokens

        eligible = [s for s in self._skills.values() if s.check_eligibility()[0]]
        # Exclude retired and deprecated skills — they must not execute in production.
        # candidate and provisional are allowed (provisional for A/B; candidate for
        # controlled testing only).
        eligible = [s for s in eligible if s.lifecycle_stage not in ("deprecated", "retired")]
        # Sort by confidence descending, then by name for stability
        eligible.sort(key=lambda s: (-s.confidence, s.name))

        # Cap to max_skills_in_prompt
        eligible = eligible[: self._max_skills]

        if not eligible:
            return SkillPrompt(budget_tokens=budget)

        # Pre-compute full and compact representations
        full_texts = [s.to_full_prompt() for s in eligible]
        compact_texts = [s.to_compact_entry() for s in eligible]
        full_token_costs = [_estimate_tokens(t) for t in full_texts]
        compact_token_costs = [_estimate_tokens(t) for t in compact_texts]

        # Try all-full first
        total_full = sum(full_token_costs)
        if total_full <= budget:
            return SkillPrompt(
                full_skills=full_texts,
                compact_skills=[],
                total_tokens=total_full,
                budget_tokens=budget,
                full_count=len(eligible),
                compact_count=0,
                truncated_count=0,
            )

        # Binary search for max number of full-format skills that fit
        # alongside the remaining compact skills.
        lo, hi = 0, len(eligible)
        best_k = 0

        while lo <= hi:
            mid = (lo + hi) // 2
            cost = sum(full_token_costs[:mid]) + sum(compact_token_costs[mid:])
            if cost <= budget:
                best_k = mid
                lo = mid + 1
            else:
                hi = mid - 1

        full_count = best_k
        # Now determine how many compact skills fit
        used = sum(full_token_costs[:full_count])
        remaining_budget = budget - used
        compact_count = 0
        for i in range(full_count, len(eligible)):
            if remaining_budget >= compact_token_costs[i]:
                remaining_budget -= compact_token_costs[i]
                compact_count += 1
            else:
                break

        total_shown = full_count + compact_count
        truncated = len(eligible) - total_shown

        total_tokens = sum(full_token_costs[:full_count]) + sum(
            compact_token_costs[full_count : full_count + compact_count]
        )

        return SkillPrompt(
            full_skills=full_texts[:full_count],
            compact_skills=compact_texts[full_count : full_count + compact_count],
            total_tokens=total_tokens,
            budget_tokens=budget,
            full_count=full_count,
            compact_count=compact_count,
            truncated_count=truncated,
        )

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    def bump_version(self) -> int:
        """Increment snapshot version (for cache invalidation)."""
        self._snapshot_version += 1
        return self._snapshot_version

    @property
    def snapshot_version(self) -> int:
        """Current snapshot version."""
        return self._snapshot_version

    @property
    def skill_count(self) -> int:
        """Number of discovered skills."""
        return len(self._skills)

    def sync_to_registry(self, registry: Any) -> int:
        """Sync file-discovered skills into a SkillRegistry as ManagedSkills.

        Bridges the file-based SkillLoader and the lifecycle-managed
        SkillRegistry so discovered SKILL.md skills are queryable through
        both subsystems.

        Args:
            registry: A SkillRegistry instance.

        Returns:
            Number of skills synced.
        """
        from datetime import UTC, datetime

        from hi_agent.skill.registry import ManagedSkill

        synced = 0
        now = datetime.now(UTC).isoformat()
        for skill in self._skills.values():
            if registry.get(skill.name) is not None:
                continue  # already present, skip
            managed = ManagedSkill(
                skill_id=skill.name,
                name=skill.name,
                description=skill.description,
                version=skill.version,
                lifecycle_stage=getattr(skill, "lifecycle_stage", "certified"),
                created_at=now,
                updated_at=now,
            )
            registry._skills[managed.skill_id] = managed
            synced += 1
        import logging as _logging

        _logging.getLogger(__name__).info(
            "SkillLoader.sync_to_registry: synced %d skill(s).", synced
        )
        return synced

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_file(self, path: str, source: str) -> SkillDefinition | None:
        """Read and parse a single SKILL.md file."""
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            logger.warning("SkillLoader._load_file: failed to read %r: %s", path, exc)
            return None

        skill = SkillDefinition.from_markdown(content, source_path=path)
        skill.source = source
        # Register (higher-precedence dir overwrites earlier)
        self._skills[skill.skill_id] = skill
        return skill
