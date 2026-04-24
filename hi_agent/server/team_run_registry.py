"""In-memory registry of active team runs."""
from __future__ import annotations

import threading

from hi_agent.contracts.team_runtime import TeamRun


class TeamRunRegistry:
    """In-memory registry of active team runs.

    Provides O(1) lookup of team membership by team_id and thread-safe
    registration. Backed by a plain dict protected by a threading.Lock.
    """

    def __init__(self) -> None:
        self._teams: dict[str, TeamRun] = {}
        self._lock = threading.Lock()

    def register(self, team_run: TeamRun) -> None:
        """Register or replace a TeamRun in the registry.

        Args:
            team_run: TeamRun to register. Replaces any existing entry for
                the same team_id.
        """
        with self._lock:
            self._teams[team_run.team_id] = team_run

    def get(self, team_id: str) -> TeamRun | None:
        """Return the TeamRun for team_id, or None if not registered.

        Args:
            team_id: Team identifier.
        """
        return self._teams.get(team_id)

    def list_members(self, team_id: str) -> list[tuple[str, str]]:
        """Return the (role_id, run_id) member pairs for a team.

        Args:
            team_id: Team identifier.

        Returns:
            List of (role_id, run_id) tuples, or empty list if not found.
        """
        run = self._teams.get(team_id)
        return list(run.member_runs) if run else []

    def unregister(self, team_id: str) -> None:
        """Remove a team from the registry.

        Args:
            team_id: Team identifier. No-op if not present.
        """
        with self._lock:
            self._teams.pop(team_id, None)
