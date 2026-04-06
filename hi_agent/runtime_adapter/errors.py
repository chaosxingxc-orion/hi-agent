"""Runtime adapter error definitions."""


class RuntimeAdapterError(Exception):
    """Base class for runtime adapter domain errors."""


class IllegalStateTransitionError(Exception):
    """Raised when strict-mode transition violates stage state machine."""


class RuntimeAdapterBackendError(RuntimeAdapterError):
    """Raised when delegated backend operation fails."""

    def __init__(self, operation: str, *, cause: Exception) -> None:
        """Create backend failure wrapper with original exception chained."""
        super().__init__(f"Backend operation failed: {operation}: {cause}")
        self.operation = operation
