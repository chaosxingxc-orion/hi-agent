"""Centralized tenant context enforcement helpers.

Use these instead of inline tenant_id comparisons scattered across handler files.
"""
from __future__ import annotations

from fastapi import HTTPException


def require_tenant_context(tenant_id: str | None) -> str:
    """Assert tenant context is present. Returns tenant_id or raises 401."""
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant context required")
    return tenant_id


def require_tenant_owns(
    requesting_tenant: str,
    resource_owner: str,
    resource_type: str = "resource",
    resource_id: str = "",
) -> None:
    """Assert requesting tenant owns the resource. Raises 404 (not 403) on mismatch.

    Returns 404 (not 403) to avoid leaking resource existence to unauthorized tenants.
    """
    if requesting_tenant != resource_owner:
        raise HTTPException(
            status_code=404,
            detail=f"{resource_type} not found",
        )
