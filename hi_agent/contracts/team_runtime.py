"""Team-level runtime contracts for multi-agent research teams.

These dataclasses define the platform-level identity and state for a
coordinated team of agents operating on a shared research project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True)
class AgentRole:
    """Declares the identity, capabilities, and memory scope of one agent in a team."""

    role_id: str
    role_name: str  # "pi" | "survey" | "analysis" | "writer_author" | ...
    model_tier: str = "tier_b"
    capabilities: tuple[str, ...] = ()
    memory_scope: Literal["private", "shared", "both"] = "private"
    description: str = ""


@dataclass(frozen=True)
class TeamSharedContext:
    """Shared state visible to all roles in a team run."""

    team_id: str
    project_id: str
    artifact_handoff_ids: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    phase_history: tuple[str, ...] = ()
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class TeamRun:
    """Records the structure and membership of a team run."""

    team_id: str
    pi_run_id: str
    project_id: str
    # (agent_role_id, run_id) pairs for each team member
    member_runs: tuple[tuple[str, str], ...] = ()
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
