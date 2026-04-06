"""Harness data contracts for dual-dimension governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EffectClass(Enum):
    """Recovery-dimension classification of actions.

    Determines retry and compensation semantics:
    - READ_ONLY: safe to retry freely
    - IDEMPOTENT_WRITE: safe to retry (same result)
    - COMPENSATABLE_WRITE: can be undone via compensation handler
    - IRREVERSIBLE_WRITE: cannot be undone, requires approval
    """

    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    COMPENSATABLE_WRITE = "compensatable_write"
    IRREVERSIBLE_WRITE = "irreversible_write"


class SideEffectClass(Enum):
    """Operational-impact classification of actions.

    Determines governance strictness:
    - READ_ONLY: no side effects
    - LOCAL_WRITE: writes confined to local system
    - EXTERNAL_WRITE: writes to external systems (requires idempotency_key)
    - IRREVERSIBLE_SUBMIT: permanent external submission (requires approval)
    """

    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXTERNAL_WRITE = "external_write"
    IRREVERSIBLE_SUBMIT = "irreversible_submit"


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


@dataclass
class ActionResult:
    """Result from Harness action execution.

    Attributes:
        action_id: Identifier of the executed action.
        state: Current lifecycle state.
        output: Output data from the capability handler.
        evidence_ref: First-class evidence reference for traceability.
        callback_ref: Reference for async callback-based operations.
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
