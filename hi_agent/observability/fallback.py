"""Fallback taxonomy and structured recording for degradation paths.

All fallback events in the TRACE pipeline should be recorded via
``record_fallback()`` so that degradation is observable and quantifiable.
"""

from __future__ import annotations

import logging
from enum import StrEnum


class FallbackTaxonomy(StrEnum):
    """Structured taxonomy of fallback kinds."""

    EXPECTED_DEGRADATION = "expected_degradation"
    UNEXPECTED_EXCEPTION = "unexpected_exception"
    SECURITY_DENIED = "security_denied"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    HEURISTIC_FALLBACK = "heuristic_fallback"
    POLICY_BYPASS_DEV = "policy_bypass_dev"


def record_fallback(
    kind: FallbackTaxonomy,
    component: str,
    detail: str = "",
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Record a fallback event.  Logs and increments metrics counter.

    This function must never raise or block execution — all errors are swallowed.

    Args:
        kind: The fallback taxonomy value describing the degradation category.
        component: The subsystem component where the fallback occurred.
        detail: Optional free-text detail for debugging (e.g. exception class name).
        logger: Optional logger to use; defaults to this module's logger.
    """
    try:
        _logger = logger or logging.getLogger(__name__)
        _logger.info(
            "fallback",
            extra={
                "fallback_kind": str(kind),
                "fallback_component": component,
                "fallback_detail": detail,
            },
        )
    except Exception:
        pass  # Logging must never block the critical path.

    # Best-effort metrics increment.  MetricsCollector silently ignores
    # metric names not in its catalogue, so this call is always safe.
    try:
        from hi_agent.observability.collector import MetricsCollector  # noqa: PLC0415

        # Access the process-level singleton if one has been set.
        _mc: MetricsCollector | None = getattr(
            MetricsCollector, "_singleton", None
        )
        if _mc is not None:
            _mc.increment(
                f"fallback.{kind}",
                labels={"component": component},
            )
    except Exception:
        pass  # Metrics must never block the critical path.
