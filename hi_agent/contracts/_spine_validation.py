"""Posture-aware spine field validator (Rule 12)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SPINE_EMPTY_SENTINELS = frozenset({"", "__legacy__", "__unknown__"})


def validate_spine(obj: Any, fields: frozenset[str] | None = None) -> None:
    """Validate that required spine fields are non-empty. Warns in dev, raises in research/prod."""
    from hi_agent.config.posture import Posture
    posture = Posture.from_env()
    if fields is None:
        fields = frozenset({"tenant_id"})

    violations = [
        f for f in fields
        if getattr(obj, f, None) in _SPINE_EMPTY_SENTINELS or getattr(obj, f, None) is None
    ]
    if not violations:
        return

    from hi_agent.contracts.errors import TenantScopeError
    msg = f"Spine fields missing/empty on {type(obj).__name__}: {violations}"
    if posture.is_strict:
        raise TenantScopeError(msg)
    logger.warning(msg)


def require_tenant(tenant_id: str | None) -> str:
    """Return tenant_id if valid, else warn (dev) or raise (research/prod)."""
    from hi_agent.config.posture import Posture
    from hi_agent.contracts.errors import TenantScopeError
    posture = Posture.from_env()
    if tenant_id in _SPINE_EMPTY_SENTINELS or tenant_id is None:
        msg = f"tenant_id is empty or sentinel: {tenant_id!r}"
        if posture.is_strict:
            raise TenantScopeError(msg)
        logger.warning(msg)
        return tenant_id or ""
    return tenant_id
