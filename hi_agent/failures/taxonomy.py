"""Frozen failure taxonomy per TRACE architecture.

All core types are imported from agent-kernel (single source of truth):
- ``TraceFailureCode`` (StrEnum) — re-exported as ``FailureCode``
- ``FAILURE_RECOVERY_MAP`` / ``FAILURE_GATE_MAP`` — standard mappings

``FailureRecord`` is hi-agent-specific (adds run/stage/branch context).
"""

from dataclasses import dataclass, field
from typing import Any

from agent_kernel.kernel.contracts import TraceFailureCode
from agent_kernel.kernel.failure_mappings import (
    FAILURE_GATE_MAP as FAILURE_GATE_MAP,
)
from agent_kernel.kernel.failure_mappings import (
    FAILURE_RECOVERY_MAP as FAILURE_RECOVERY_MAP,
)

# Re-export as FailureCode for backward compatibility across hi-agent.
FailureCode = TraceFailureCode


def is_budget_exhausted_failure_code(code: FailureCode | str) -> bool:
    """Return True for current or legacy budget-exhaustion failure codes.

    Prefers the kernel helper when we already have a TraceFailureCode value,
    and falls back to legacy string compatibility for historical records.
    """
    if isinstance(code, TraceFailureCode):
        return TraceFailureCode.is_budget_exhausted(code)

    if code == "budget_exhausted":
        return True

    try:
        return TraceFailureCode.is_budget_exhausted(TraceFailureCode(code))
    except ValueError:
        return False


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
