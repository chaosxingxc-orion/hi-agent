"""Contract error hierarchy for agent_server.

W31-N (N-13): ``http_status`` and ``error_category`` are now seeded by
``__init__`` from class-level defaults so the envelope state is set at
construction time rather than being lazy-class-attribute lookups
overridden via post-instantiation mutation.

The class-level constants ``http_status`` / ``error_category`` are
preserved verbatim for backwards-compatible class-level introspection
(e.g. ``QuotaError.http_status == 429``). The ``__init__`` now also
accepts optional ``http_status=`` / ``error_category=`` kwargs so
callers can construct an instance with the desired status in one shot,
removing the prior pattern of ``err.http_status = 400`` after
construction. Existing post-instantiation mutation continues to work
— instance assignment still binds on the instance — but new code
should pass the kwargs to the constructor instead.
"""
from __future__ import annotations


class ContractError(Exception):
    """Base class for all agent_server contract errors."""

    # Class-level defaults preserved for backwards-compatible introspection
    # (e.g. ``QuotaError.http_status == 429``). Subclasses override these.
    http_status: int = 500
    error_category: str = "internal_error"
    retryable: bool = False
    next_action: str = ""

    def __init__(
        self,
        message: str,
        *,
        tenant_id: str = "",
        detail: str = "",
        http_status: int | None = None,
        error_category: str | None = None,
        retryable: bool | None = None,
        next_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tenant_id = tenant_id
        self.detail = detail
        # Each instance binds the envelope fields explicitly — class-level
        # defaults provide the seed when no constructor kwarg is passed.
        if http_status is not None:
            self.http_status = http_status
        if error_category is not None:
            self.error_category = error_category
        if retryable is not None:
            self.retryable = retryable
        if next_action is not None:
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
