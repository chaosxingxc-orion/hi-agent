"""Contract error hierarchy for agent_server."""
from __future__ import annotations


class ContractError(Exception):
    """Base class for all agent_server contract errors."""

    http_status: int = 500

    def __init__(self, message: str, *, tenant_id: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.tenant_id = tenant_id
        self.detail = detail


class AuthError(ContractError):
    """Authentication or authorization failed."""

    http_status = 401


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
