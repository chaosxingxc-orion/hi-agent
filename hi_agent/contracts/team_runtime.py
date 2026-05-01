"""Team-level runtime contracts for multi-agent coordination.

These dataclasses define the platform-level identity and state for a
coordinated team of agents operating on a shared project.
"""
from __future__ import annotations

import dataclasses
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


# scope: process-internal — role descriptor; tenant scope flows through TeamSharedContext/TeamRun
@dataclass(frozen=True)
class AgentRole:
    """Declares the identity, capabilities, and memory scope of one agent in a team."""

    role_id: str
    role_name: str  # "lead" | "worker" | "reviewer" | "summarizer" | ...
    # Examples are illustrative; role_name is an opaque string the platform does not interpret.
    model_tier: str = "tier_b"
    capabilities: tuple[str, ...] = ()
    memory_scope: Literal["private", "shared", "both"] = "private"
    description: str = ""


@dataclass(frozen=True)
class TeamSharedContext:
    """Shared state visible to all roles in a team run."""

    team_id: str
    project_id: str
    tenant_id: str  # Rule 12 spine — required; no default
    artifact_handoff_ids: tuple[str, ...] = ()
    # Canonical generic fields (Wave 11+)
    working_set: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()
    # Deprecated aliases — use working_set / assertions instead.
    # Will be removed in Wave 28.
    hypotheses: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    phase_history: tuple[str, ...] = ()
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if self.hypotheses and not self.working_set:
            warnings.warn(
                "TeamSharedContext.hypotheses is deprecated; use working_set instead. "
                "hypotheses will be removed in Wave 28.",
                DeprecationWarning,
                stacklevel=2,
            )
            object.__setattr__(self, "working_set", self.hypotheses)
        if self.claims and not self.assertions:
            warnings.warn(
                "TeamSharedContext.claims is deprecated; use assertions instead. "
                "claims will be removed in Wave 28.",
                DeprecationWarning,
                stacklevel=2,
            )
            object.__setattr__(self, "assertions", self.claims)


@dataclass(frozen=True)
class TeamRun:
    """Records the structure and membership of a team run."""

    team_id: str
    project_id: str
    # (agent_role_id, run_id) pairs for each team member
    tenant_id: str = ""  # Rule 12 spine — validated in TeamRunRegistry.register()
    member_runs: tuple[tuple[str, str], ...] = ()
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Contract spine (Rule 12): persistent records must answer "which tenant".
    user_id: str = ""
    session_id: str = ""
    # Deprecated: use lead_run_id instead. Will be removed in Wave 28.
    pi_run_id: str = ""
    # Canonical field (Wave 11+). Prefer lead_run_id for all new callers.
    lead_run_id: str = dataclasses.field(default="")


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
    tenant_id: str = ""  # scope: spine-required — validated under research/prod posture

    def __post_init__(self) -> None:
        if self.tenant_id:
            return
        from hi_agent.config.posture import Posture

        if Posture.from_env().is_strict:
            raise ValueError(
                "TeamRunSpec.tenant_id required under research/prod posture (got empty string)"
            )
        warnings.warn(
            "TeamRunSpec constructed with empty tenant_id; rejected under research/prod posture.",
            DeprecationWarning,
            stacklevel=2,
        )
