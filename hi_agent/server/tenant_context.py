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
_tenant_context_var: ContextVar[TenantContext | None] = ContextVar(
    "tenant_context", default=None
)


def get_tenant_context() -> TenantContext | None:
    """Return the current TenantContext, or None if not set."""
    return _tenant_context_var.get()


def set_tenant_context(ctx: TenantContext) -> Token:
    """Set the TenantContext for the current task.

    Returns the reset token so callers can restore the previous value.
    """
    return _tenant_context_var.set(ctx)


def reset_tenant_context(token: Token) -> None:  # type: ignore[type-arg]
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
