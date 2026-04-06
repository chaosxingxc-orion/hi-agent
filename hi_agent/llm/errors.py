"""LLM Gateway error types."""

from __future__ import annotations


class LLMError(Exception):
    """Base error for all LLM Gateway failures."""


class LLMTimeoutError(LLMError):
    """Raised when an LLM request exceeds the configured timeout."""


class LLMProviderError(LLMError):
    """Raised when the LLM provider returns an HTTP or API-level error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize provider error.

        Args:
            message: Human-readable error description.
            status_code: HTTP status code from the provider, if available.
        """
        super().__init__(message)
        self.status_code = status_code


class LLMBudgetExhaustedError(LLMError):
    """Raised when token or call budget has been exceeded."""
