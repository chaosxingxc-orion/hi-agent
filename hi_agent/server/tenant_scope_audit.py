"""Tenant scope audit helper for read-only / global-readonly route handlers.

Some HTTP route handlers serve resources that are intentionally global-scoped
(skill registry listing, MCP tool listing, knowledge system stats). The data
under them is shared across tenants by design — but the route still must
record *which tenant* accessed it, so audit trails and per-tenant rate
shaping have a signal to act on.

This helper provides ``record_tenant_scoped_access(tenant_id=..., resource=...,
op=...)`` which:

* increments a Prometheus counter ``hi_agent_route_tenant_scoped_access_total``
  with labels ``{resource, op, tenant_id}`` (Rule 7 — Countable);
* logs a structured INFO line tagged ``tenant_scoped_access`` carrying
  ``tenant_id``, ``resource``, ``op`` (Rule 7 — Attributable);
* satisfies ``check_route_scope.py``'s ``tenant_id=ctx.tenant_id`` pattern
  match because callers use the kwarg form.

The helper is a no-op apart from the audit signal — it does NOT enforce
data partitioning. Routes that require *data-level* tenant isolation must
also pass tenant_id through to the underlying store.
"""

from __future__ import annotations

import contextlib
import logging

from hi_agent.observability.metric_counter import Counter

_logger = logging.getLogger(__name__)

_route_tenant_scoped_access_total: Counter = Counter(
    "hi_agent_route_tenant_scoped_access_total"
)
_route_tenant_audit_metric_errors_total: Counter = Counter(
    "hi_agent_route_tenant_audit_metric_errors_total"
)


def record_tenant_scoped_access(
    *,
    tenant_id: str,
    resource: str,
    op: str,
) -> None:
    """Record one tenant-scoped access for audit + observability.

    Args:
        tenant_id: Authenticated tenant id from ``TenantContext.tenant_id``.
        resource: Logical resource family (e.g. ``"knowledge"``, ``"skills"``,
            ``"tools"``).
        op: Operation kind (e.g. ``"status"``, ``"list"``, ``"metrics"``).
    """
    _logger.info(
        "tenant_scoped_access tenant_id=%r resource=%r op=%r",
        tenant_id,
        resource,
        op,
    )
    try:
        _route_tenant_scoped_access_total.labels(
            resource=resource, op=op, tenant_id=tenant_id
        ).inc()
    except Exception as exc:
        _logger.warning(
            "tenant_scoped_access_metric_failed tenant_id=%r resource=%r op=%r exc=%r",
            tenant_id,
            resource,
            op,
            exc,
        )
        # Counter-of-counter increment is best-effort; alarm bell is the WARNING log above.
        with contextlib.suppress(Exception):  # rule7-exempt: expiry_wave="permanent" replacement_test: tenant-scope-audit-error-counter # noqa: E501
            _route_tenant_audit_metric_errors_total.labels(
                resource=resource, op=op
            ).inc()
        return


__all__ = ["record_tenant_scoped_access"]
