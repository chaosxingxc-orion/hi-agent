"""Recovery state machine for lease-expired runs (Wave 10.5 W5-C).

Under research/prod posture, lease-expired runs are re-enqueued by default.
Under dev posture, only a warning is emitted (warn-only).
"""
from __future__ import annotations

import dataclasses
from enum import StrEnum

from hi_agent.config.posture import Posture


class RecoveryState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    LEASE_EXPIRED = "lease_expired"
    REQUEUED = "requeued"
    ADOPTED = "adopted"
    FAILED_TERMINAL = "failed_terminal"


@dataclasses.dataclass(frozen=True)
class RecoveryDecision:
    run_id: str
    tenant_id: str
    from_state: RecoveryState
    to_state: RecoveryState
    should_requeue: bool
    reason: str


def decide_recovery_action(
    run_id: str,
    tenant_id: str,
    current_state: RecoveryState,
    posture: Posture,
) -> RecoveryDecision:
    """Determine what recovery action to take for a lease-expired run.

    Under research/prod: LEASE_EXPIRED → REQUEUED (fail-safe default).
    Under dev: LEASE_EXPIRED → no-op + warning.

    Args:
        run_id: The run identifier.
        tenant_id: Tenant spine field.
        current_state: Current recovery state of the run.
        posture: Platform posture (dev/research/prod).

    Returns:
        A RecoveryDecision describing what action to take.
    """
    if current_state != RecoveryState.LEASE_EXPIRED:
        return RecoveryDecision(
            run_id=run_id,
            tenant_id=tenant_id,
            from_state=current_state,
            to_state=current_state,
            should_requeue=False,
            reason=f"state {current_state} does not require recovery",
        )

    if posture.is_strict:  # research or prod
        return RecoveryDecision(
            run_id=run_id,
            tenant_id=tenant_id,
            from_state=RecoveryState.LEASE_EXPIRED,
            to_state=RecoveryState.REQUEUED,
            should_requeue=True,
            reason="research/prod default: re-enqueue lease-expired run",
        )
    else:  # dev
        return RecoveryDecision(
            run_id=run_id,
            tenant_id=tenant_id,
            from_state=RecoveryState.LEASE_EXPIRED,
            to_state=RecoveryState.LEASE_EXPIRED,
            should_requeue=False,
            reason="dev posture: warn-only, no re-enqueue",
        )
