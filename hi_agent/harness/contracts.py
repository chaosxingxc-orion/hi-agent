"""Harness data contracts for dual-dimension governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

from agent_kernel.kernel.contracts import SideEffectClass


class EffectClass(StrEnum):
    """Classification of an action's effect on external state."""

    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    COMPENSATABLE_WRITE = "compensatable_write"
    IRREVERSIBLE_WRITE = "irreversible_write"
    DANGEROUS = "dangerous"


class ActionState(Enum):
    """Lifecycle state of an action."""

    PREPARED = "prepared"
    APPROVAL_PENDING = "approval_pending"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    SUCCEEDED = "succeeded"
    EFFECT_UNKNOWN = "effect_unknown"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass
class ActionSpec:
    """Specification for an action to be executed through Harness.

    Attributes:
        action_id: Unique identifier for this action instance.
        action_type: Semantic type: "read", "mutate", "publish", or "submit".
        capability_name: Name of the capability to invoke.
        payload: Arguments passed to the capability handler.
        effect_class: Recovery-dimension classification.
        side_effect_class: Operational-impact classification.
        approval_required: Whether human approval is needed before execution.
        idempotency_key: Key for deduplication of writes.
        timeout_seconds: Maximum execution time.
        max_retries: Additional attempts after first failure.
        metadata: Arbitrary metadata for tracing and auditing.
        submitter_id: Principal who submitted/initiated the action; used for SOC enforcement.
    """

    action_id: str
    action_type: str
    capability_name: str
    payload: dict[str, Any]
    effect_class: EffectClass = EffectClass.READ_ONLY
    side_effect_class: SideEffectClass = SideEffectClass.READ_ONLY
    approval_required: bool = False
    idempotency_key: str = ""
    timeout_seconds: int = 60
    max_retries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    submitter_id: str = ""
    upstream_artifact_ids: list[str] = field(default_factory=list)


@dataclass
class ActionResult:
    """Result from Harness action execution.

    Attributes:
        action_id: Identifier of the executed action.
        state: Current lifecycle state.
        output: Output data from the capability handler.
        evidence_ref: First-class evidence reference for traceability.
        callback_ref: Reserved for future async callback-based operations; not yet consumed.
        error_code: Structured error code on failure.
        error_message: Human-readable error description.
        duration_ms: Wall-clock execution time in milliseconds.
        attempt: Which attempt produced this result (1-based).
    """

    action_id: str
    state: ActionState
    output: Any = None
    evidence_ref: str | None = None
    callback_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = 0
    attempt: int = 1
    artifact_ids: list[str] = field(default_factory=list)


@dataclass
class EvidenceRecord:
    """Structured evidence from action execution.

    Attributes:
        evidence_ref: Unique reference for this evidence record.
        action_id: Action that produced this evidence.
        evidence_type: Category: "output", "side_effect", "observation", "metric".
        content: Structured evidence payload.
        timestamp: ISO-8601 timestamp of evidence creation.
    """

    evidence_ref: str
    action_id: str
    evidence_type: str
    content: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
