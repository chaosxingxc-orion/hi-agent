"""Contract error hierarchy for agent_server."""
from __future__ import annotations


class ContractError(Exception):
    """Base class for all agent_server contract errors."""

    http_status: int = 500
    error_category: str = "internal_error"
    retryable: bool = False
    next_action: str = ""

    def __init__(self, message: str, *, tenant_id: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.tenant_id = tenant_id
        self.detail = detail

    def to_envelope(self) -> dict[str, object]:
        """Return the unified error envelope (HD-5).

        Shape: ``{error_category, message, retryable, next_action,
        tenant_id, detail}``. The first four fields match
        :func:`hi_agent.server.error_categories.error_response` so callers
        can treat envelopes from agent_server and hi_agent uniformly.
        """
        return {
            "error_category": self.error_category,
            "message": str(self),
            "retryable": self.retryable,
            "next_action": self.next_action,
            "tenant_id": self.tenant_id,
            "detail": self.detail,
        }


class AuthError(ContractError):
    """Authentication or authorization failed."""

    http_status = 401
    error_category = "auth_required"
    retryable = False
    next_action = "supply X-Tenant-Id header"


class QuotaError(ContractError):
    """Tenant quota exceeded."""

    http_status = 429


class ConflictError(ContractError):
    """Idempotency key conflict or duplicate request."""

    http_status = 409


class NotFoundError(ContractError):
    """Requested resource not found."""

    http_status = 404


class RuntimeContractError(ContractError):
    """Runtime error during contract execution."""

    http_status = 500
