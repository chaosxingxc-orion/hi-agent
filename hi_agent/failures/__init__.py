"""Failure taxonomy and structured error system for the TRACE framework."""

from hi_agent.failures.taxonomy import (
    FailureCode,
    FailureRecord,
    FAILURE_RECOVERY_MAP,
    FAILURE_GATE_MAP,
)
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.failures.exceptions import (
    TraceFailure,
    MissingEvidenceError,
    InvalidContextError,
    HarnessDeniedError,
    ModelOutputInvalidError,
    ModelRefusalError,
    CallbackTimeoutError,
    NoProgressError,
    ContradictoryEvidenceError,
    UnsafeActionBlockedError,
    BudgetExhaustedError,
)

__all__ = [
    "FailureCode",
    "FailureRecord",
    "FAILURE_RECOVERY_MAP",
    "FAILURE_GATE_MAP",
    "FailureCollector",
    "ProgressWatchdog",
    "TraceFailure",
    "MissingEvidenceError",
    "InvalidContextError",
    "HarnessDeniedError",
    "ModelOutputInvalidError",
    "ModelRefusalError",
    "CallbackTimeoutError",
    "NoProgressError",
    "ContradictoryEvidenceError",
    "UnsafeActionBlockedError",
    "BudgetExhaustedError",
]
