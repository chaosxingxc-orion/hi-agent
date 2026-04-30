"""Structured HTTP error categories for the /runs boundary.

Every non-2xx response from /runs routes uses error_response() so that
callers can parse errors programmatically without string-matching.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    SCOPE_REQUIRED = "scope_required"          # project_id / profile_id missing
    AUTH_REQUIRED = "auth_required"            # missing/empty auth header (HD-5)
    QUEUE_FULL = "queue_full"                  # run queue at capacity
    GATEWAY_UNAVAILABLE = "gateway_unavailable"  # LLM backend not reachable
    IDEMPOTENCY_PENDING = "idempotency_pending"  # same key in-flight
    INVALID_REQUEST = "invalid_request"        # bad request body
    INTERNAL_ERROR = "internal_error"          # unexpected server error


def error_response(
    category: ErrorCategory,
    message: str,
    *,
    retryable: bool,
    next_action: str = "",
) -> dict:
    """Build a structured error body with all required envelope fields.

    Args:
        category: One of the ErrorCategory enum values.
        message: Human-readable description of the error.
        retryable: Whether the caller should retry the request.
        next_action: Optional hint for what the caller should do next.

    Returns:
        Dict with keys: error_category, message, retryable, next_action.
    """
    return {
        "error_category": category,
        "message": message,
        "retryable": retryable,
        "next_action": next_action,
    }
