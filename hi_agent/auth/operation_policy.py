"""Operation-driven RBAC/SOC policy table and enforcement decorator (HI-W1-D5-001)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps

from fastapi import HTTPException
from starlette.requests import Request


@dataclass(frozen=True)
class RoutePolicy:
    operation_name: str
    required_roles: list[str]
    require_soc_separation: bool
    dev_bypass: bool = True
    audit_event: str = ""


OPERATION_POLICIES: dict[str, RoutePolicy] = {
    "skill.promote": RoutePolicy(
        "skill.promote", ["approver", "admin"], True, audit_event="skill.promote"
    ),
    "skill.evolve": RoutePolicy(
        "skill.evolve", ["approver", "admin"], True, audit_event="skill.evolve"
    ),
    "memory.consolidate": RoutePolicy(
        "memory.consolidate", ["approver", "admin"], False, audit_event="memory.consolidate"
    ),
}


def require_operation(operation_name: str) -> Callable:
    """Decorator that enforces the RoutePolicy for a mutation handler."""
    policy = OPERATION_POLICIES[operation_name]

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            from hi_agent.auth.authorization_context import AuthorizationContext
            from hi_agent.observability.audit import emit

            ctx = AuthorizationContext.from_request(request)

            # dev bypass — allowed but audited
            if policy.dev_bypass and ctx.runtime_mode != "prod-real":
                emit("audit.auth.bypass", {
                    "operation": operation_name,
                    "mode": ctx.runtime_mode,
                    "role": ctx.role,
                })
                return await func(request, *args, **kwargs)

            # role check
            if ctx.role not in policy.required_roles:
                emit("audit.auth.deny", {
                    "operation": operation_name,
                    "role": ctx.role,
                    "required_roles": policy.required_roles,
                    "reason": "missing_role",
                })
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "unauthorized",
                        "operation": operation_name,
                        "required_roles": policy.required_roles,
                        "reason": "missing_role",
                    },
                )

            # SOC separation check
            if policy.require_soc_separation and ctx.submitter == ctx.approver and ctx.submitter is not None:
                emit("audit.auth.deny", {
                    "operation": operation_name,
                    "reason": "soc_violation",
                    "submitter": ctx.submitter,
                })
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "unauthorized",
                        "operation": operation_name,
                        "required_roles": policy.required_roles,
                        "reason": "soc_violation",
                    },
                )

            # success audit
            if policy.audit_event:
                emit(policy.audit_event, {
                    "operation": operation_name,
                    "role": ctx.role,
                })

            return await func(request, *args, **kwargs)

        return wrapper
    return decorator
