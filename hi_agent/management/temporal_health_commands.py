"""Command-style wrappers for temporal health checks."""

from __future__ import annotations

from collections.abc import Callable

from hi_agent.runtime_adapter.temporal_health import (
    TemporalConnectionHealthCheck,
    TemporalConnectionHealthReport,
    check_temporal_connection,
)


def cmd_temporal_health_check(
    *,
    ping_fn: Callable[[], float],
    degraded_latency_ms: float = 500.0,
    stale_success_seconds: float = 30.0,
    now_fn: Callable[[], float] | None = None,
) -> dict[str, object]:
    """Run temporal health check and return normalized payload."""
    checker = TemporalConnectionHealthCheck(
        ping_fn=ping_fn,
        degraded_latency_ms=degraded_latency_ms,
        stale_success_seconds=stale_success_seconds,
        now_fn=now_fn,
    )
    report = checker.check()
    return _health_report_payload(report)


def cmd_temporal_probe_check(
    *,
    probe_fn: Callable[[], None],
    degraded_latency_ms: float = 500.0,
    now_fn: Callable[[], float] | None = None,
) -> dict[str, object]:
    """Run probe-style check and return compatibility payload."""
    probe_result = check_temporal_connection(
        probe_fn,
        degraded_latency_ms=degraded_latency_ms,
        now_fn=now_fn,
    )
    return {
        "command": "temporal_probe_check",
        "connected": probe_result.connected,
        "degraded": probe_result.degraded,
        "latency_ms": probe_result.latency_ms,
        "reason": probe_result.reason,
    }


def _health_report_payload(report: TemporalConnectionHealthReport) -> dict[str, object]:
    """Convert health report to command payload."""
    return {
        "command": "temporal_health_check",
        "state": report.state.value,
        "healthy": report.healthy,
        "latency_ms": report.latency_ms,
        "last_success_age_seconds": report.last_success_age_seconds,
        "error": report.error,
    }
