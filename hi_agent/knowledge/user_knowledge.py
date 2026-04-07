"""User knowledge: preferences, expertise, interaction patterns.

Tracks what the user knows, prefers, and how they work.
Updated from session interactions and explicit user statements.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class UserProfile:
    """User knowledge profile."""

    user_id: str = "default"
    role: str = ""  # "data scientist", "engineer"
    expertise: list[str] = field(default_factory=list)  # domain knowledge areas
    preferences: dict[str, str] = field(default_factory=dict)  # key-value prefs
    interaction_patterns: list[str] = field(default_factory=list)  # observed patterns
    feedback_history: list[str] = field(default_factory=list)  # corrections/confirmations
    updated_at: str = ""


class UserKnowledgeStore:
    """Manages user knowledge with file persistence."""

    def __init__(self, storage_dir: str = ".hi_agent/knowledge/user") -> None:
        self._storage_dir = Path(storage_dir)
        self._profiles: dict[str, UserProfile] = {}

    def get_profile(self, user_id: str = "default") -> UserProfile:
        """Get or create a user profile."""
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    def update_profile(self, user_id: str, **kwargs: str | list[str] | dict[str, str]) -> None:
        """Update profile fields directly."""
        profile = self.get_profile(user_id)
        for key, value in kwargs.items():
            if hasattr(profile, key) and key != "user_id":
                setattr(profile, key, value)
        profile.updated_at = datetime.now(UTC).isoformat()

    def add_preference(self, key: str, value: str, user_id: str = "default") -> None:
        """Add or update a user preference."""
        profile = self.get_profile(user_id)
        profile.preferences[key] = value
        profile.updated_at = datetime.now(UTC).isoformat()

    def add_expertise(self, domain: str, user_id: str = "default") -> None:
        """Add a domain expertise area."""
        profile = self.get_profile(user_id)
        if domain not in profile.expertise:
            profile.expertise.append(domain)
        profile.updated_at = datetime.now(UTC).isoformat()

    def add_feedback(self, feedback: str, user_id: str = "default") -> None:
        """Record user feedback (correction or confirmation)."""
        profile = self.get_profile(user_id)
        profile.feedback_history.append(feedback)
        profile.updated_at = datetime.now(UTC).isoformat()

    def record_interaction_pattern(self, pattern: str, user_id: str = "default") -> None:
        """Record an observed interaction pattern."""
        profile = self.get_profile(user_id)
        if pattern not in profile.interaction_patterns:
            profile.interaction_patterns.append(pattern)
        profile.updated_at = datetime.now(UTC).isoformat()

    def to_context_string(self, user_id: str = "default", max_tokens: int = 300) -> str:
        """Format user profile for LLM context injection."""
        profile = self.get_profile(user_id)
        parts: list[str] = []
        if profile.role:
            parts.append(f"Role: {profile.role}")
        if profile.expertise:
            parts.append(f"Expertise: {', '.join(profile.expertise)}")
        if profile.preferences:
            prefs = "; ".join(f"{k}={v}" for k, v in profile.preferences.items())
            parts.append(f"Preferences: {prefs}")
        if profile.interaction_patterns:
            parts.append(f"Patterns: {', '.join(profile.interaction_patterns)}")
        if profile.feedback_history:
            recent = profile.feedback_history[-3:]  # last 3
            parts.append(f"Recent feedback: {'; '.join(recent)}")

        result = "\n".join(parts)
        budget = max_tokens * 4
        if len(result) > budget:
            result = result[:budget]
        return result

    # ------------------------------------------------------------------ Persistence

    def save(self) -> None:
        """Persist all profiles to disk."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        for user_id, profile in self._profiles.items():
            path = self._storage_dir / f"{user_id}.json"
            path.write_text(
                json.dumps(asdict(profile), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def load(self) -> None:
        """Load profiles from disk."""
        if not self._storage_dir.exists():
            return
        self._profiles.clear()
        for profile_file in sorted(self._storage_dir.glob("*.json")):
            data = json.loads(profile_file.read_text(encoding="utf-8"))
            profile = UserProfile(
                user_id=data.get("user_id", "default"),
                role=data.get("role", ""),
                expertise=data.get("expertise", []),
                preferences=data.get("preferences", {}),
                interaction_patterns=data.get("interaction_patterns", []),
                feedback_history=data.get("feedback_history", []),
                updated_at=data.get("updated_at", ""),
            )
            self._profiles[profile.user_id] = profile
