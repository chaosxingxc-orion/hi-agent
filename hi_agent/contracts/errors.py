"""Typed error hierarchy for hi-agent domain failures."""

from __future__ import annotations


class HiAgentError(Exception):
    """Base class for typed hi-agent errors."""


class TransientError(HiAgentError):
    """Retryable failure category."""


class PermanentError(HiAgentError):
    """Non-retryable failure category."""


class LLMTimeoutError(TransientError):
    """Raised when an LLM request exceeds its deadline."""


class LLMRateLimitError(TransientError):
    """Raised when an LLM provider rate limits a request."""


class RunQueueFullError(TransientError):
    """Raised when the run queue cannot accept additional work."""


class TenantScopeError(PermanentError):
    """Raised when tenant-scoped data is accessed outside its tenant."""


class IdempotencyConflictError(PermanentError):
    """Raised when an idempotency key maps to a different payload."""


class LeaseLostError(TransientError):
    """Raised when a lease renewal or ownership check fails."""


class EventBufferOverflowError(TransientError):
    """Raised when buffered events exceed their capacity guarantees."""


class ProfileScopeError(PermanentError):
    """Raised when profile-scoped data is accessed outside its profile."""


__all__ = [
    "EventBufferOverflowError",
    "HiAgentError",
    "IdempotencyConflictError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LeaseLostError",
    "PermanentError",
    "ProfileScopeError",
    "RunQueueFullError",
    "TenantScopeError",
    "TransientError",
]

