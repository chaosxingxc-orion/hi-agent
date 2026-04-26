"""Posture-enforcement guard helpers.

Call these at spine-accepting call sites instead of branching on Posture.is_strict manually.
"""
from __future__ import annotations

import logging

from hi_agent.config.posture import Posture

_logger = logging.getLogger(__name__)


def require_tenant(
    tenant_id: str | None,
    *,
    where: str,
    posture: Posture | None = None,
) -> str:
    """Validate tenant_id against current posture.

    dev: allow empty (warn + counter); return "".
    research/prod: raise ValueError if empty.
    """
    p = posture if posture is not None else Posture.from_env()
    if tenant_id:
        return str(tenant_id)
    if p.is_strict:
        raise ValueError(
            f"empty tenant_id at {where!r} is forbidden under {p} posture"
        )
    _logger.warning(
        "hi_agent.posture_guards: empty tenant_id admitted at %r (dev posture)", where
    )
    try:
        from hi_agent.observability.collector import get_metrics_collector

        collector = get_metrics_collector()
        if collector is not None:
            collector.increment(
                "hi_agent_empty_tenant_admit_total",
                labels={"site": where, "posture": str(p)},
            )
    except Exception:
        pass
    return ""


def require_spine(
    *,
    tenant_id: str | None,
    project_id: str | None,
    where: str,
    posture: Posture | None = None,
) -> tuple[str, str]:
    """Validate both tenant_id and project_id. Returns (tenant_id, project_id)."""
    p = posture if posture is not None else Posture.from_env()
    return (
        require_tenant(tenant_id, where=where, posture=p),
        require_tenant(project_id, where=f"{where}:project_id", posture=p),
    )
