"""Typed exceptions for each TRACE failure code."""

from typing import Any

from hi_agent.failures.taxonomy import (
    FailureCode,
    FailureRecord,
    FAILURE_RECOVERY_MAP,
)


class TraceFailure(Exception):
    """Base exception for TRACE failures."""

    failure_code: FailureCode = FailureCode.MISSING_EVIDENCE  # overridden by subclasses

    def __init__(self, code: FailureCode, message: str, **context: Any) -> None:
        self.code = code
        self.message = message
        self.context = context
        super().__init__(f"[{code.value}] {message}")

    def to_record(self, run_id: str = "", stage_id: str = "") -> FailureRecord:
        """Convert this exception to a FailureRecord."""
        return FailureRecord(
            failure_code=self.code,
            message=self.message,
            run_id=run_id,
            stage_id=stage_id,
            context=dict(self.context),
            recovery_action=FAILURE_RECOVERY_MAP.get(self.code, ""),
        )


class MissingEvidenceError(TraceFailure):
    """Raised when required evidence is not available."""

    def __init__(self, message: str = "Required evidence not found", **context: Any) -> None:
        super().__init__(FailureCode.MISSING_EVIDENCE, message, **context)


class InvalidContextError(TraceFailure):
    """Raised when context is invalid or corrupted."""

    def __init__(self, message: str = "Invalid context", **context: Any) -> None:
        super().__init__(FailureCode.INVALID_CONTEXT, message, **context)


class HarnessDeniedError(TraceFailure):
    """Raised when a harness action is denied."""

    def __init__(self, message: str = "Harness action denied", **context: Any) -> None:
        super().__init__(FailureCode.HARNESS_DENIED, message, **context)


class ModelOutputInvalidError(TraceFailure):
    """Raised when model output fails validation."""

    def __init__(self, message: str = "Model output invalid", **context: Any) -> None:
        super().__init__(FailureCode.MODEL_OUTPUT_INVALID, message, **context)


class ModelRefusalError(TraceFailure):
    """Raised when the model refuses to produce output."""

    def __init__(self, message: str = "Model refused to respond", **context: Any) -> None:
        super().__init__(FailureCode.MODEL_REFUSAL, message, **context)


class CallbackTimeoutError(TraceFailure):
    """Raised when a callback times out."""

    def __init__(self, message: str = "Callback timed out", **context: Any) -> None:
        super().__init__(FailureCode.CALLBACK_TIMEOUT, message, **context)


class NoProgressError(TraceFailure):
    """Raised when no progress is being made."""

    def __init__(self, message: str = "No progress detected", **context: Any) -> None:
        super().__init__(FailureCode.NO_PROGRESS, message, **context)


class ContradictoryEvidenceError(TraceFailure):
    """Raised when contradictory evidence is encountered."""

    def __init__(self, message: str = "Contradictory evidence found", **context: Any) -> None:
        super().__init__(FailureCode.CONTRADICTORY_EVIDENCE, message, **context)


class UnsafeActionBlockedError(TraceFailure):
    """Raised when an unsafe action is blocked."""

    def __init__(self, message: str = "Unsafe action blocked", **context: Any) -> None:
        super().__init__(FailureCode.UNSAFE_ACTION_BLOCKED, message, **context)


class BudgetExhaustedError(TraceFailure):
    """Raised when budget is exhausted."""

    def __init__(self, message: str = "Budget exhausted", **context: Any) -> None:
        super().__init__(FailureCode.BUDGET_EXHAUSTED, message, **context)
