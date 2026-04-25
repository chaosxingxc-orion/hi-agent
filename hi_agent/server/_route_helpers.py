"""Shared route helpers: validation and ownership primitives.

Rule A: validate_run_request_or_raise must complete before any mutator call.
Rule D: get_or_404_owned enforces resource ownership on every GET by id.
"""
from __future__ import annotations

import logging
from typing import Any

from hi_agent.config.posture import Posture
from hi_agent.server.error_categories import ErrorCategory
from hi_agent.server.tenant_context import TenantContext

logger = logging.getLogger(__name__)


class ValidationError(ValueError):
    """Raised when request validation fails before any mutation."""

    def __init__(
        self,
        category: str,
        message: str,
        next_action: str = "",
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.next_action = next_action
        self.status_code = status_code


def validate_run_request_or_raise(
    body: dict,
    ctx: TenantContext,
    posture: Posture,
) -> dict:
    """Validate a run creation request and return a sanitized copy.

    Raises ValidationError (before any mutation) if required fields are absent.

    Returns:
        The body dict with any missing defaults applied (e.g. profile_id='default').
    """
    body = dict(body)  # shallow copy so we can mutate

    if not body.get("goal"):
        raise ValidationError(
            ErrorCategory.INVALID_REQUEST,
            "goal is required",
            "Add 'goal' to the request body",
        )

    if not body.get("project_id") and posture.requires_project_id:
        raise ValidationError(
            ErrorCategory.SCOPE_REQUIRED,
            "project_id is required under research/prod posture",
            "Set project_id in the request body",
        )

    if not body.get("profile_id") and posture.requires_profile_id:
        raise ValidationError(
            ErrorCategory.SCOPE_REQUIRED,
            "profile_id is required under research/prod posture",
            "Set profile_id in the request body",
        )

    # Dev-posture defaults (no error, but ensure field exists)
    if not body.get("profile_id"):
        from hi_agent.observability.fallback import record_fallback

        logger.warning(
            "POST /runs received without profile_id; defaulting to 'default'."
        )
        record_fallback(
            "route",
            reason="missing_profile_id",
            run_id="pre-create",
            extra={"default_assigned": "default"},
        )
        body["profile_id"] = "default"

    return body


def validate_resource_ownership(resource: Any, ctx: TenantContext) -> None:
    """Raise ValueError('not_found') if resource.tenant_id != ctx.tenant_id.

    Uses 'not_found' (not 'forbidden') to avoid leaking existence.
    """
    resource_tenant = getattr(resource, "tenant_id", None)
    if resource_tenant is None:
        return  # resource has no tenant_id — skip check (legacy/dev)
    if resource_tenant == "":
        return  # unscoped legacy resource — accessible but log
    if resource_tenant != ctx.tenant_id:
        raise ValueError("not_found")


def get_or_404_owned(registry: Any, resource_id: str, ctx: TenantContext) -> Any:
    """Fetch resource by id and enforce ownership.

    Returns resource or raises ValueError('not_found').
    """
    resource = registry.get(resource_id)
    if resource is None:
        raise ValueError("not_found")
    validate_resource_ownership(resource, ctx)
    return resource
