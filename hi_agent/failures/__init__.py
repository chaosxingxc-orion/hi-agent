"""Failure taxonomy and structured error system for the TRACE framework."""

from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.exceptions import (
    BudgetExhaustedError,
    CallbackTimeoutError,
    ContradictoryEvidenceError,
    HarnessDeniedError,
    InvalidContextError,
    MissingEvidenceError,
    ModelOutputInvalidError,
    ModelRefusalError,
    NoProgressError,
    TraceFailure,
    UnsafeActionBlockedError,
)
from hi_agent.failures.taxonomy import (
    FAILURE_GATE_MAP,
    FAILURE_RECOVERY_MAP,
    FailureCode,
    FailureRecord,
)
from hi_agent.failures.watchdog import ProgressWatchdog

__all__ = [
    "FAILURE_GATE_MAP",
    "FAILURE_RECOVERY_MAP",
    "BudgetExhaustedError",
    "CallbackTimeoutError",
    "ContradictoryEvidenceError",
    "FailureCode",
    "FailureCollector",
    "FailureRecord",
    "HarnessDeniedError",
    "InvalidContextError",
    "MissingEvidenceError",
    "ModelOutputInvalidError",
    "ModelRefusalError",
    "NoProgressError",
    "ProgressWatchdog",
    "TraceFailure",
    "UnsafeActionBlockedError",
]
