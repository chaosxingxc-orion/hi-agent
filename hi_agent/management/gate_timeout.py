"""Human-gate timeout policy helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import time


class GateTimeoutPolicy(StrEnum):
    """Fallback policy when a human gate times out."""

    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class GateTimeoutResult:
    """Resolved timeout outcome."""

    timed_out: bool
    action: str | None
    reason: str | None
    resolved_at: float | None
    escalation_target: str | None = None


def resolve_gate_timeout(
    *,
    opened_at: float,
    timeout_seconds: float,
    policy: GateTimeoutPolicy,
    now_fn: Callable[[], float] | None = None,
    escalation_target: str | None = None,
) -> GateTimeoutResult:
    """Resolve timeout result according to policy.

    Returns a non-timed-out result when the gate is still within the timeout
    budget, otherwise maps policy to a deterministic action.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")
    if opened_at < 0:
        raise ValueError("opened_at must be non-negative")

    clock = now_fn or time
    now_value = float(clock())
    if now_value < opened_at:
        raise ValueError("now must be >= opened_at")

    expired = (now_value - opened_at) >= timeout_seconds
    if not expired:
        return GateTimeoutResult(
            timed_out=False,
            action=None,
            reason=None,
            resolved_at=None,
        )

    if policy is GateTimeoutPolicy.APPROVE:
        return GateTimeoutResult(
            timed_out=True,
            action="approve",
            reason="timeout_auto_approve",
            resolved_at=now_value,
        )
    if policy is GateTimeoutPolicy.REJECT:
        return GateTimeoutResult(
            timed_out=True,
            action="reject",
            reason="timeout_auto_reject",
            resolved_at=now_value,
        )

    return GateTimeoutResult(
        timed_out=True,
        action="escalate",
        reason="timeout_escalated",
        resolved_at=now_value,
        escalation_target=escalation_target.strip() if escalation_target else None,
    )
