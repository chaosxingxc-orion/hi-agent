"""Profile directory isolation under HI_AGENT_HOME."""

from __future__ import annotations

import os
from pathlib import Path


class ProfileDirectoryManager:
    """Resolves profile-scoped file paths under HI_AGENT_HOME.

    Priority order:
    1. Explicit constructor path
    2. HI_AGENT_HOME env var
    3. Default: ~/.hi_agent
    """

    def __init__(self, home_dir: str | None = None) -> None:
        if home_dir is not None:
            self._home = Path(home_dir).expanduser().resolve()
        else:
            env_home = os.environ.get("HI_AGENT_HOME")
            if env_home:
                self._home = Path(env_home).expanduser().resolve()
            else:
                self._home = Path.home() / ".hi_agent"

    @property
    def home(self) -> Path:
        """Return the resolved home directory path."""
        return self._home

    def profile_dir(self, profile_id: str) -> Path:
        """Return <home>/profiles/<profile_id>/ (created if absent)."""
        path = self._home / "profiles" / profile_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def episodic_dir(self, profile_id: str = "") -> Path:
        """Return <home>/episodes/<profile_id>/ or <home>/episodes/."""
        if profile_id:
            path = self._home / "episodes" / profile_id
        else:
            path = self._home / "episodes"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def checkpoint_dir(self) -> Path:
        """Return <home>/checkpoints/."""
        path = self._home / "checkpoints"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def audit_dir(self) -> Path:
        """Return <home>/audit/ (for audit events JSONL)."""
        path = self._home / "audit"
        path.mkdir(parents=True, exist_ok=True)
        return path
