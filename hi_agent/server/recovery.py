"""Recovery state machine for lease-expired runs.

Under research/prod posture, lease-expired runs are re-enqueued by default.
Under dev posture, only a warning is emitted (warn-only).
"""
from __future__ import annotations

import dataclasses
import logging
import os
from enum import StrEnum

from hi_agent.config.posture import Posture

_logger = logging.getLogger(__name__)


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


class RecoveryAlarm:
    """Rule 7-compliant alarm for when recovery reenqueue is disabled under strict posture.

    Satisfies Rule 7 requirements:
    1. Countable — increments ``hi_agent_recovery_reenqueue_disabled_total`` on /metrics.
    2. Attributable — emits a WARNING log with run_id and tenant_id.
    3. Inspectable — caller should append the event to run's fallback_events.
    """

    @staticmethod
    def fire_if_needed(run_id: str, tenant_id: str, posture: Posture) -> None:
        """Emit Rule 7 alarm when reenqueue is disabled under research/prod posture.

        A no-op when:
        - ``HI_AGENT_RECOVERY_REENQUEUE`` is not ``"0"`` (reenqueue is enabled), or
        - ``posture`` is not strict (dev posture — warn-only is the expected default).

        Args:
            run_id: The run identifier whose reenqueue was suppressed.
            tenant_id: Tenant spine field for attribution.
            posture: Platform posture; alarm fires only under research/prod.
        """
        reenqueue_enabled = os.environ.get("HI_AGENT_RECOVERY_REENQUEUE", "1") != "0"
        if reenqueue_enabled or not posture.is_strict:
            return

        # Rule 7 (1): Countable — named Prometheus counter on /metrics.
        try:
            from hi_agent.observability.collector import get_metrics_collector

            collector = get_metrics_collector()
            if collector is not None:
                collector.increment("hi_agent_recovery_reenqueue_disabled_total")
        except Exception:  # rule7-exempt: expiry_wave="Wave 27" metrics must never crash callers
            pass

        # Rule 7 (2): Attributable — WARNING log with run_id + tenant_id + trigger reason.
        _logger.warning(
            "Recovery reenqueue disabled for run_id=%s tenant_id=%s — "
            "HI_AGENT_RECOVERY_REENQUEUE=0 suppresses re-enqueue under research/prod; "
            "set HI_AGENT_RECOVERY_REENQUEUE=1 to restore fail-safe behaviour.",
            run_id,
            tenant_id,
        )
        # Rule 7 (3): Inspectable — caller (app._rehydrate_runs) appends to fallback_events.


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
