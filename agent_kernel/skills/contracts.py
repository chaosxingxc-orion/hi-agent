"""Defines skill contracts for the agent_kernel execution layer.

The agent_kernel architecture treats skills as executor-governed
capability runtimes. They are intentionally excluded from lifecycle
authority, event authority, and recovery authority.

Strategy-layer protocols (SkillRegistry, SkillResolver, SkillRuntime,
factory protocols) have moved to hi_agent.skills. This module retains
only the DTO contracts that the kernel itself exchanges. The strategy
protocols are re-exported here for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

# Strategy protocols live in hi_agent.skills; re-exported here for backward compat.
# Import from the contracts submodule directly to avoid package __init__ cycles.
from hi_agent.skills.contracts import (
    LocalSkillRuntimeFactory,
    ManagedSkillRuntime,
    RemoteSkillGatewayFactory,
    SkillRegistry,
    SkillResolver,
    SkillRuntime,
    SkillRuntimeFactory,
    SkillRuntimeHostFactory,
)

if TYPE_CHECKING:
    from agent_kernel.kernel.contracts import (
        EffectClass,
        ExternalIdempotencyLevel,
    )

SkillFailureCode = Literal[
    "tool_error",
    "mcp_error",
    "model_error",
    "validation_error",
    "permission_denied",
    "quota_exceeded",
    "timeout",
    "unknown",
]
SkillRuntimeHost = Literal["cli_process", "in_process_python", "remote_service"]


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    """Defines one registered skill and its governance metadata.

    Attributes:
        skill_id: Unique skill identifier.
        version: Semantic version of the skill.
        skill_kind: Logical category of the skill.
        effect_class: Declared side-effect class for admission policy.
        input_schema_ref: Reference to the input JSON schema.
        output_schema_ref: Reference to the output JSON schema.
        display_name: Optional human-readable display name.
        description: Optional human-readable description.
        external_idempotency_level: Optional external idempotency guarantee.
        timeout_ms: Optional execution timeout in milliseconds.
        retryable: Optional retry eligibility flag.
        capability_scope: Ordered list of capability scope identifiers.
        tool_bindings: Ordered list of bound tool names.
        mcp_bindings: Ordered list of bound MCP server capabilities.
        metadata: Arbitrary metadata dictionary.

    """

    skill_id: str
    version: str
    skill_kind: str
    effect_class: EffectClass
    input_schema_ref: str
    output_schema_ref: str
    display_name: str | None = None
    description: str | None = None
    external_idempotency_level: ExternalIdempotencyLevel | None = None
    timeout_ms: int | None = None
    retryable: bool | None = None
    capability_scope: list[str] = field(default_factory=list)
    tool_bindings: list[str] = field(default_factory=list)
    mcp_bindings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillRequest:
    """Carries one executor-managed invocation into a skill runtime.

    Attributes:
        run_id: Kernel run identifier.
        action_id: Action identifier triggering the skill invocation.
        skill_id: Target skill identifier.
        skill_version: Optional skill version constraint.
        input_ref: Optional input reference string.
        input_json: Optional input payload dictionary.
        context_ref: Optional context binding reference.
        grant_ref: Optional admission grant reference.
        caused_by: Optional causal reference for provenance tracing.

    """

    run_id: str
    action_id: str
    skill_id: str
    skill_version: str | None = None
    input_ref: str | None = None
    input_json: dict[str, Any] | None = None
    context_ref: str | None = None
    grant_ref: str | None = None
    caused_by: str | None = None


@dataclass(frozen=True, slots=True)
class SkillObservation:
    """Carries non-authoritative local observations returned by a skill.

    Attributes:
        observation_type: Discriminator for the observation category.
        payload_ref: Optional reference to stored observation payload.
        payload_json: Optional inline observation payload dictionary.

    """

    observation_type: str
    payload_ref: str | None = None
    payload_json: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SkillResult:
    """Carries the only allowed outputs a skill may return to the executor.

    Attributes:
        skill_id: Skill that produced this result.
        action_id: Action that triggered the skill execution.
        success: Whether the skill execution succeeded.
        output_ref: Optional reference to stored output payload.
        output_json: Optional inline output payload dictionary.
        local_observations: Ordered list of non-authoritative observations.
        evidence_ref: Optional reference to execution evidence.
        failure_code: Optional failure code when ``success`` is False.
        failure_detail: Optional human-readable failure description.

    """

    skill_id: str
    action_id: str
    success: bool
    output_ref: str | None = None
    output_json: dict[str, Any] | None = None
    local_observations: list[SkillObservation] = field(default_factory=list)
    evidence_ref: str | None = None
    failure_code: SkillFailureCode | None = None
    failure_detail: str | None = None


@dataclass(frozen=True, slots=True)
class SkillExecutionInput:
    """Carries the executor-level request to run a skill-backed action.

    Attributes:
        action_id: Action identifier for the execution request.
        run_id: Kernel run identifier.
        action_type: Discriminator for the action type.
        input_ref: Optional input reference string.
        input_json: Optional input payload dictionary.
        context_ref: Optional context binding reference.
        preferred_skill_id: Optional preferred skill identifier.
        preferred_skill_version: Optional preferred skill version.
        grant_ref: Optional admission grant reference.

    """

    action_id: str
    run_id: str
    action_type: str
    input_ref: str | None = None
    input_json: dict[str, Any] | None = None
    context_ref: str | None = None
    preferred_skill_id: str | None = None
    preferred_skill_version: str | None = None
    grant_ref: str | None = None


@dataclass(frozen=True, slots=True)
class SkillExecutionResult:
    """Carries the resolved skill metadata and the runtime result.

    Attributes:
        skill: Resolved skill definition that governed execution.
        result: Skill execution result returned by the runtime.

    """

    skill: SkillDefinition
    result: SkillResult


@dataclass(frozen=True, slots=True)
class ResolvedSkillPlan:
    """Carries resolved runtime execution plan for one skill invocation."""

    skill: SkillDefinition
    host_kind: SkillRuntimeHost
    grant_ref: str | None = None
    capability_snapshot_ref: str | None = None
    capability_snapshot_hash: str | None = None
    idempotency_envelope: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SkillActionResolveInput:
    """Carries the information required to resolve a skill for one action."""

    action_type: str
    run_id: str
    policy_tags: list[str] = field(default_factory=list)
    preferred_skill_id: str | None = None
    preferred_version: str | None = None


__all__ = [
    "LocalSkillRuntimeFactory",
    "ManagedSkillRuntime",
    "RemoteSkillGatewayFactory",
    "ResolvedSkillPlan",
    "SkillActionResolveInput",
    "SkillDefinition",
    "SkillExecutionInput",
    "SkillExecutionResult",
    "SkillFailureCode",
    "SkillObservation",
    "SkillRegistry",
    "SkillRequest",
    "SkillResolver",
    "SkillResult",
    "SkillRuntime",
    "SkillRuntimeFactory",
    "SkillRuntimeHost",
    "SkillRuntimeHostFactory",
]
