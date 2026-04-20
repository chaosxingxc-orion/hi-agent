"""Skill versioning with champion/challenger A/B testing.

Each skill can have multiple versions. The "champion" is the current
production version. A "challenger" can be deployed alongside for
traffic splitting and comparison.

Inspired by hi-agent's existing ChampionChallenger + agent-core's checkpointing.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from hi_agent.skill.observer import SkillMetrics


@dataclass
class SkillVersionRecord:
    """A versioned snapshot of a skill's prompt and parameters."""

    skill_id: str
    version: str
    prompt_content: str
    parameters: dict[str, Any] = field(default_factory=dict)
    metrics: SkillMetrics | None = None
    is_champion: bool = False
    is_challenger: bool = False
    created_at: str = ""


class SkillVersionManager:
    """Manages skill versions and A/B traffic splitting."""

    def __init__(self, storage_dir: str = ".hi_agent/skill_versions") -> None:
        """Initialize SkillVersionManager."""
        self._storage_dir = storage_dir
        # skill_id -> list of SkillVersionRecord
        self._versions: dict[str, list[SkillVersionRecord]] = {}

    def create_version(
        self,
        skill_id: str,
        prompt_content: str,
        parameters: dict | None = None,
    ) -> SkillVersionRecord:
        """Create a new version of a skill. Auto-increments version."""
        existing = self._versions.get(skill_id, [])
        next_num = len(existing) + 1
        version = f"v{next_num}"
        now = datetime.now(UTC).isoformat()

        record = SkillVersionRecord(
            skill_id=skill_id,
            version=version,
            prompt_content=prompt_content,
            parameters=parameters or {},
            is_champion=next_num == 1,  # first version is auto-champion
            is_challenger=False,
            created_at=now,
        )

        if skill_id not in self._versions:
            self._versions[skill_id] = []
        self._versions[skill_id].append(record)
        return record

    def get_champion(self, skill_id: str) -> SkillVersionRecord | None:
        """Get current champion version."""
        for rec in self._versions.get(skill_id, []):
            if rec.is_champion:
                return rec
        return None

    def get_challenger(self, skill_id: str) -> SkillVersionRecord | None:
        """Get current challenger version (if A/B active)."""
        for rec in self._versions.get(skill_id, []):
            if rec.is_challenger:
                return rec
        return None

    def set_champion(self, skill_id: str, version: str) -> None:
        """Set a specific version as champion, clearing previous champion."""
        versions = self._versions.get(skill_id, [])
        found = False
        for rec in versions:
            if rec.version == version:
                rec.is_champion = True
                found = True
            else:
                rec.is_champion = False
        if not found:
            raise KeyError(f"Version '{version}' not found for skill '{skill_id}'")

    def set_challenger(self, skill_id: str, version: str) -> None:
        """Set a specific version as challenger, clearing previous challenger."""
        versions = self._versions.get(skill_id, [])
        found = False
        for rec in versions:
            if rec.version == version:
                rec.is_challenger = True
                found = True
            else:
                rec.is_challenger = False
        if not found:
            raise KeyError(f"Version '{version}' not found for skill '{skill_id}'")

    def promote_challenger(self, skill_id: str) -> bool:
        """Promote challenger to champion (if metrics are better).

        Returns True if promotion occurred, False otherwise.
        """
        champion = self.get_champion(skill_id)
        challenger = self.get_challenger(skill_id)
        if challenger is None:
            return False

        # If no champion, always promote
        if champion is None:
            challenger.is_champion = True
            challenger.is_challenger = False
            return True

        # Compare metrics if available
        champ_rate = 0.0
        chall_rate = 0.0
        if champion.metrics is not None:
            champ_rate = champion.metrics.success_rate
        if challenger.metrics is not None:
            chall_rate = challenger.metrics.success_rate

        if chall_rate >= champ_rate:
            champion.is_champion = False
            challenger.is_champion = True
            challenger.is_challenger = False
            return True

        return False

    def select_version(self, skill_id: str, traffic_split: float = 0.1) -> SkillVersionRecord:
        """Select version for execution: champion or challenger.

        Traffic split is the fraction going to challenger.

        Raises:
            KeyError: If no versions exist for the skill.
        """
        champion = self.get_champion(skill_id)
        challenger = self.get_challenger(skill_id)

        if champion is None:
            versions = self._versions.get(skill_id, [])
            if not versions:
                raise KeyError(f"No versions found for skill '{skill_id}'")
            return versions[-1]

        if challenger is not None and random.random() < traffic_split:
            return challenger

        return champion

    def rollback(self, skill_id: str) -> bool:
        """Rollback to previous champion version.

        Returns True if rollback occurred, False otherwise.
        """
        versions = self._versions.get(skill_id, [])
        if len(versions) < 2:
            return False

        # Find current champion index
        current_idx = -1
        for i, rec in enumerate(versions):
            if rec.is_champion:
                current_idx = i
                break

        if current_idx < 0:
            return False

        # Find the version before the current champion
        prev_idx = current_idx - 1
        if prev_idx < 0:
            return False

        # Demote current, promote previous
        versions[current_idx].is_champion = False
        versions[current_idx].is_challenger = False
        versions[prev_idx].is_champion = True
        versions[prev_idx].is_challenger = False
        return True

    def list_versions(self, skill_id: str) -> list[SkillVersionRecord]:
        """List all versions for a skill."""
        return list(self._versions.get(skill_id, []))

    def compare(self, skill_id: str) -> dict[str, Any]:
        """Compare champion vs challenger metrics."""
        champion = self.get_champion(skill_id)
        challenger = self.get_challenger(skill_id)

        result: dict[str, Any] = {
            "skill_id": skill_id,
            "champion_version": None,
            "challenger_version": None,
            "champion_metrics": None,
            "challenger_metrics": None,
            "recommendation": "no_data",
        }

        if champion is not None:
            result["champion_version"] = champion.version
            if champion.metrics is not None:
                result["champion_metrics"] = {
                    "success_rate": champion.metrics.success_rate,
                    "avg_quality": champion.metrics.avg_quality,
                    "avg_latency_ms": champion.metrics.avg_latency_ms,
                }

        if challenger is not None:
            result["challenger_version"] = challenger.version
            if challenger.metrics is not None:
                result["challenger_metrics"] = {
                    "success_rate": challenger.metrics.success_rate,
                    "avg_quality": challenger.metrics.avg_quality,
                    "avg_latency_ms": challenger.metrics.avg_latency_ms,
                }

        # Determine recommendation
        if champion and challenger and champion.metrics and challenger.metrics:
            if challenger.metrics.success_rate > champion.metrics.success_rate:
                result["recommendation"] = "promote_challenger"
            elif challenger.metrics.success_rate < champion.metrics.success_rate:
                result["recommendation"] = "keep_champion"
            else:
                result["recommendation"] = "no_difference"

        return result

    # --- Persistence ---

    def save(self) -> None:
        """Persist all versions to disk."""
        os.makedirs(self._storage_dir, exist_ok=True)
        path = os.path.join(self._storage_dir, "versions.json")
        data: dict[str, list[dict]] = {}
        for skill_id, versions in self._versions.items():
            data[skill_id] = []
            for rec in versions:
                d = asdict(rec)
                # SkillMetrics is a dataclass, asdict handles it,
                # but None needs to stay None
                if rec.metrics is None:
                    d["metrics"] = None
                data[skill_id].append(d)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self) -> None:
        """Load versions from disk."""
        path = os.path.join(self._storage_dir, "versions.json")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._versions.clear()
        for skill_id, version_list in data.items():
            self._versions[skill_id] = []
            for d in version_list:
                metrics_data = d.pop("metrics", None)
                metrics = None
                if metrics_data is not None:
                    metrics = SkillMetrics(**metrics_data)
                rec = SkillVersionRecord(**d, metrics=metrics)
                self._versions[skill_id].append(rec)
