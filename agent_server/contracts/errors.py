"""Contract error hierarchy for agent_server.

W31-N (N-13): ``http_status`` and ``error_category`` moved from
class-attribute defaults into instance state set in ``__init__``. The
prior class-level attributes acted as mutable defaults that callers
overrode with ``err.http_status = 400`` post-instantiation, which made
the envelope state implicit and surprising on subclasses. The
``__init__`` now accepts both as optional keyword arguments and each
subclass overrides the default by passing its own kwargs through
``super().__init__``. Existing call sites that mutated ``err.http_status``
post-instantiation continue to work — instance assignment still binds
on the instance — but new code should pass ``http_status=...`` to the
constructor instead.
"""
from __future__ import annotations


class ContractError(Exception):
    """Base class for all agent_server contract errors."""

    # W31-N (N-13): the class-level constants below remain ONLY as
    # documented defaults that subclasses can override via __init__
    # kwargs. They are no longer the canonical state — see __init__.
    DEFAULT_HTTP_STATUS: int = 500
    DEFAULT_ERROR_CATEGORY: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        tenant_id: str = "",
        detail: str = "",
        http_status: int | None = None,
        error_category: str | None = None,
        retryable: bool = False,
        next_action: str = "",
    ) -> None:
        super().__init__(message)
        self.tenant_id = tenant_id
        self.detail = detail
        self.http_status = (
            http_status if http_status is not None else self.DEFAULT_HTTP_STATUS
        )
        self.error_category = (
            error_category
            if error_category is not None
            else self.DEFAULT_ERROR_CATEGORY
        )
        self.retryable = retryable
        self.next_action = next_action

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

    DEFAULT_HTTP_STATUS = 401
    DEFAULT_ERROR_CATEGORY = "auth_required"

    def __init__(self, message: str, *, tenant_id: str = "", detail: str = "") -> None:
        super().__init__(
            message,
            tenant_id=tenant_id,
            detail=detail,
            retryable=False,
            next_action="supply X-Tenant-Id header",
        )


class QuotaError(ContractError):
    """Tenant quota exceeded."""

    DEFAULT_HTTP_STATUS = 429


class ConflictError(ContractError):
    """Idempotency key conflict or duplicate request."""

    DEFAULT_HTTP_STATUS = 409


class NotFoundError(ContractError):
    """Requested resource not found."""

    DEFAULT_HTTP_STATUS = 404


class RuntimeContractError(ContractError):
    """Runtime error during contract execution."""

    DEFAULT_HTTP_STATUS = 500
