"""Frozen failure taxonomy per TRACE architecture.

The 10 failure codes defined here are first-class concepts in the TRACE framework.
They must be used consistently across all subsystems.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class FailureCode(Enum):
    """Frozen failure taxonomy per TRACE architecture."""
    MISSING_EVIDENCE = "missing_evidence"
    INVALID_CONTEXT = "invalid_context"
    HARNESS_DENIED = "harness_denied"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    MODEL_REFUSAL = "model_refusal"
    CALLBACK_TIMEOUT = "callback_timeout"
    NO_PROGRESS = "no_progress"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    UNSAFE_ACTION_BLOCKED = "unsafe_action_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


# Mapping: failure code -> recommended recovery action
FAILURE_RECOVERY_MAP: dict[FailureCode, str] = {
    FailureCode.MISSING_EVIDENCE: "task_view_degradation",
    FailureCode.INVALID_CONTEXT: "pre_call_abort",
    FailureCode.HARNESS_DENIED: "approval_escalation",
    FailureCode.MODEL_OUTPUT_INVALID: "retry_or_downgrade_model",
    FailureCode.MODEL_REFUSAL: "alternate_model_or_human",
    FailureCode.CALLBACK_TIMEOUT: "recovery_path",
    FailureCode.NO_PROGRESS: "watchdog_handling",
    FailureCode.CONTRADICTORY_EVIDENCE: "human_gate_c",
    FailureCode.UNSAFE_ACTION_BLOCKED: "human_gate_approval",
    FailureCode.BUDGET_EXHAUSTED: "cts_termination_or_gate_b",
}

# Mapping: failure code -> Human Gate type (None = no gate)
FAILURE_GATE_MAP: dict[FailureCode, str | None] = {
    FailureCode.MISSING_EVIDENCE: None,
    FailureCode.INVALID_CONTEXT: None,
    FailureCode.HARNESS_DENIED: "gate_d",
    FailureCode.MODEL_OUTPUT_INVALID: None,
    FailureCode.MODEL_REFUSAL: None,
    FailureCode.CALLBACK_TIMEOUT: None,
    FailureCode.NO_PROGRESS: "gate_b",
    FailureCode.CONTRADICTORY_EVIDENCE: "gate_a",
    FailureCode.UNSAFE_ACTION_BLOCKED: "gate_d",
    FailureCode.BUDGET_EXHAUSTED: "gate_b",
}


@dataclass
class FailureRecord:
    """Structured failure record for audit and evolve feedback."""
    failure_code: FailureCode
    message: str
    run_id: str = ""
    stage_id: str = ""
    branch_id: str = ""
    action_id: str = ""
    timestamp: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    recovery_action: str = ""
    resolved: bool = False
