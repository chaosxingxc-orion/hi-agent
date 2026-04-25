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


@dataclass(frozen=True)
class TeamRunSpec:
    """Platform-neutral contract describing how a team run should execute.

    TeamRunSpec is a pure data declaration — it carries no runtime state.
    The platform layer uses it to wire roles, phases, capabilities, and
    policies without coupling to any business-layer logic.
    """

    team_id: str
    project_id: str
    profile_id: str
    roles: tuple[AgentRole, ...] = ()
    phases: tuple[str, ...] = ()  # phase IDs in execution order
    capability_bindings: dict[str, list[str]] = field(
        default_factory=dict
    )  # phase_id → capability names
    artifact_requirements: dict[str, list[str]] = field(
        default_factory=dict
    )  # phase_id → required artifact types
    gate_hooks: tuple[str, ...] = ()  # gate type names in evaluation order
    budget_policy: dict = field(
        default_factory=dict
    )  # e.g. {"max_cost_usd": 5.0, "max_tokens": 100000}
    replan_policy: dict = field(
        default_factory=dict
    )  # e.g. {"allowed": True, "approval_required_after": 2}
