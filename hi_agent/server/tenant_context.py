"""TenantContext — per-request tenant identity propagated via ContextVar.

Stores authenticated tenant/user identity after auth middleware resolves it.
Downstream handlers read it via ``get_tenant_context()`` or
``require_tenant_context()``.

Thread/task isolation: each asyncio task inherits a copy of the context at
creation time (standard contextvars semantics), so concurrent requests are
fully isolated.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass
class TenantContext:
    """Resolved identity for one HTTP request."""

    tenant_id: str
    team_id: str = ""
    user_id: str = ""
    roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    # "api_key" | "jwt" | "none"
    auth_method: str = "none"
    request_id: str = ""
    session_id: str = ""

    def __post_init__(self) -> None:
        """W35-T1: posture-aware spine validation.

        Under research/prod posture ``tenant_id`` MUST be non-empty —
        every authenticated HTTP request must carry a tenant identity.
        ``user_id`` and ``session_id`` are intentionally optional because
        some flows (anonymous health checks, admin tooling) legitimately
        run without them. Under dev posture missing tenant_id is logged.
        """
        from hi_agent.config.posture import Posture
        from hi_agent.contracts.reasoning import SpineCompletenessError

        posture = Posture.from_env()
        if self.tenant_id:
            return
        if posture.is_strict:
            raise SpineCompletenessError(
                "TenantContext constructed without required spine fields "
                f"under posture={posture.value}: missing=['tenant_id']. "
                "Populate at the construction site (Rule 12)."
            )
        import logging
        logging.getLogger("hi_agent.server.tenant_context").warning(
            "tenant_context_spine_incomplete: missing=['tenant_id'] posture=%s; "
            "would fail-closed under research/prod. (W35-T1)",
            posture.value,
        )

    def workspace_key(self):
        """Return a WorkspaceKey for this context."""
        from hi_agent.server.workspace_path import WorkspaceKey

        if not self.session_id:
            raise ValueError(
                "session_id is required to build a WorkspaceKey. "
                "Ensure SessionMiddleware is configured for workspace-scoped routes."
            )
        return WorkspaceKey(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            session_id=self.session_id,
            team_id=self.team_id,
        )


# ContextVar — one slot per async task / thread context.
_tenant_context_var: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def get_tenant_context() -> TenantContext | None:
    """Return the current TenantContext, or None if not set."""
    return _tenant_context_var.get()


def set_tenant_context(ctx: TenantContext) -> Token:
    """Set the TenantContext for the current task.

    Returns the reset token so callers can restore the previous value.
    """
    return _tenant_context_var.set(ctx)


def reset_tenant_context(token: Token) -> None:  # type: ignore[type-arg]  expiry_wave: permanent
    """Restore the context variable to the state before the matching set()."""
    _tenant_context_var.reset(token)


def require_tenant_context() -> TenantContext:
    """Return the current TenantContext, raising if none is set.

    Raises:
        RuntimeError: when no TenantContext has been set for this request.
    """
    ctx = get_tenant_context()
    if ctx is None:
        raise RuntimeError("No TenantContext set for this request")
    return ctx
