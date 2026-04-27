"""Run liveness state enum for stuck-run detection."""

from __future__ import annotations

from enum import Enum


class RunLivenessState(Enum):
    """Liveness states for a run as seen by the stuck-run detector."""

    healthy = "healthy"
    slow = "slow"
    stuck = "stuck"
    recovering = "recovering"
    dlq = "dlq"
    manual_intervention_required = "manual_intervention_required"
