"""Health/readiness checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HealthReport:
    """Service health report."""

    healthy: bool
    details: dict[str, str]


@dataclass(frozen=True)
class ReadinessReport:
    """Service readiness report."""

    ready: bool
    dependencies: dict[str, bool]
    recent_error_count: int


@dataclass(frozen=True)
class OperationalReadinessReport:
    """Operational readiness report with reconcile signal coverage."""

    ready: bool
    dependencies: dict[str, bool]
    recent_error_count: int
    reconcile_backlog: int
    recent_reconcile_failures: int
    reconcile_backlog_threshold: int
    pending_gate_count: int = 0
    has_stale_gates: bool = False
    stale_gate_threshold_seconds: float = 0.0
    oldest_pending_gate_age_seconds: float | None = None


class SupervisorOperationalMetrics(Protocol):
    """Minimal supervisor-like metrics shape for readiness helpers."""

    dependencies: dict[str, bool]
    recent_error_count: int
    reconcile_backlog: int
    recent_reconcile_failures: int
    reconcile_backlog_threshold: int
    pending_gate_count: int
    stale_gate_threshold_seconds: float
    oldest_pending_gate_age_seconds: float | None


def basic_health_check(component_states: dict[str, bool]) -> HealthReport:
    """Compute health report from component status map."""
    unhealthy = [name for name, ok in component_states.items() if not ok]
    if unhealthy:
        return HealthReport(
            healthy=False,
            details={"unhealthy": ",".join(sorted(unhealthy))},
        )
    return HealthReport(healthy=True, details={"status": "ok"})


def readiness_check(
    dependencies: dict[str, bool],
    recent_error_count: int,
) -> ReadinessReport:
    """Compute readiness from dependency state and recent error count."""
    if recent_error_count < 0:
        msg = "recent_error_count must be >= 0"
        raise ValueError(msg)
    return ReadinessReport(
        ready=all(dependencies.values()) and recent_error_count == 0,
        dependencies=dependencies.copy(),
        recent_error_count=recent_error_count,
    )


def operational_readiness_check(
    dependencies: dict[str, bool],
    recent_error_count: int,
    reconcile_backlog: int,
    recent_reconcile_failures: int,
    reconcile_backlog_threshold: int,
    pending_gate_count: int = 0,
    stale_gate_threshold_seconds: float = 0.0,
    oldest_pending_gate_age_seconds: float | None = None,
) -> OperationalReadinessReport:
    """Compute operational readiness from dependency state and reconcile signals."""
    if recent_error_count < 0:
        msg = "recent_error_count must be >= 0"
        raise ValueError(msg)
    if reconcile_backlog < 0:
        msg = "reconcile_backlog must be >= 0"
        raise ValueError(msg)
    if recent_reconcile_failures < 0:
        msg = "recent_reconcile_failures must be >= 0"
        raise ValueError(msg)
    if reconcile_backlog_threshold < 0:
        msg = "reconcile_backlog_threshold must be >= 0"
        raise ValueError(msg)
    if pending_gate_count < 0:
        msg = "pending_gate_count must be >= 0"
        raise ValueError(msg)
    if stale_gate_threshold_seconds < 0:
        msg = "stale_gate_threshold_seconds must be >= 0"
        raise ValueError(msg)
    if oldest_pending_gate_age_seconds is not None and oldest_pending_gate_age_seconds < 0:
        msg = "oldest_pending_gate_age_seconds must be >= 0 when provided"
        raise ValueError(msg)

    has_stale_gates = (
        pending_gate_count > 0
        and stale_gate_threshold_seconds > 0
        and oldest_pending_gate_age_seconds is not None
        and oldest_pending_gate_age_seconds >= stale_gate_threshold_seconds
    )

    return OperationalReadinessReport(
        ready=(
            all(dependencies.values())
            and recent_error_count == 0
            and recent_reconcile_failures == 0
            and reconcile_backlog < reconcile_backlog_threshold
            and not has_stale_gates
        ),
        dependencies=dependencies.copy(),
        recent_error_count=recent_error_count,
        reconcile_backlog=reconcile_backlog,
        recent_reconcile_failures=recent_reconcile_failures,
        reconcile_backlog_threshold=reconcile_backlog_threshold,
        pending_gate_count=pending_gate_count,
        has_stale_gates=has_stale_gates,
        stale_gate_threshold_seconds=stale_gate_threshold_seconds,
        oldest_pending_gate_age_seconds=oldest_pending_gate_age_seconds,
    )


def build_operational_readiness_report(
    metrics: SupervisorOperationalMetrics | None = None,
    *,
    dependencies: dict[str, bool] | None = None,
    recent_error_count: int | None = None,
    reconcile_backlog: int | None = None,
    recent_reconcile_failures: int | None = None,
    reconcile_backlog_threshold: int | None = None,
    pending_gate_count: int | None = None,
    stale_gate_threshold_seconds: float | None = None,
    oldest_pending_gate_age_seconds: float | None = None,
) -> OperationalReadinessReport:
    """Build operational readiness from metrics object and/or explicit values."""

    def _resolve(name: str, value: object | None) -> object:
        if value is not None:
            return value
        if metrics is not None and hasattr(metrics, name):
            return getattr(metrics, name)
        msg = (
            f"{name} must be provided explicitly or via metrics."
            if metrics is not None
            else f"{name} must be provided."
        )
        raise ValueError(msg)

    resolved_dependencies = _resolve("dependencies", dependencies)
    resolved_recent_error_count = _resolve("recent_error_count", recent_error_count)
    resolved_reconcile_backlog = _resolve("reconcile_backlog", reconcile_backlog)
    resolved_recent_reconcile_failures = _resolve(
        "recent_reconcile_failures",
        recent_reconcile_failures,
    )
    resolved_reconcile_backlog_threshold = _resolve(
        "reconcile_backlog_threshold",
        reconcile_backlog_threshold,
    )
    resolved_pending_gate_count = (
        pending_gate_count
        if pending_gate_count is not None
        else (getattr(metrics, "pending_gate_count", 0) if metrics is not None else 0)
    )
    resolved_stale_gate_threshold_seconds = (
        stale_gate_threshold_seconds
        if stale_gate_threshold_seconds is not None
        else (getattr(metrics, "stale_gate_threshold_seconds", 0.0) if metrics is not None else 0.0)
    )
    resolved_oldest_pending_gate_age_seconds = (
        oldest_pending_gate_age_seconds
        if oldest_pending_gate_age_seconds is not None
        else (
            getattr(metrics, "oldest_pending_gate_age_seconds", None)
            if metrics is not None
            else None
        )
    )

    return operational_readiness_check(
        dependencies=dict(resolved_dependencies),
        recent_error_count=int(resolved_recent_error_count),
        reconcile_backlog=int(resolved_reconcile_backlog),
        recent_reconcile_failures=int(resolved_recent_reconcile_failures),
        reconcile_backlog_threshold=int(resolved_reconcile_backlog_threshold),
        pending_gate_count=int(resolved_pending_gate_count),
        stale_gate_threshold_seconds=float(resolved_stale_gate_threshold_seconds),
        oldest_pending_gate_age_seconds=(
            None
            if resolved_oldest_pending_gate_age_seconds is None
            else float(resolved_oldest_pending_gate_age_seconds)
        ),
    )


def build_operational_readiness_from_signals(
    *,
    dependencies: dict[str, bool],
    recent_error_count: int,
    signals: dict[str, object],
) -> OperationalReadinessReport:
    """Build readiness report from aggregated operational signals payload."""
    required_keys = (
        "reconcile_backlog",
        "reconcile_backlog_threshold",
        "recent_reconcile_failures",
        "pending_gate_count",
        "has_stale_gates",
        "has_reconcile_pressure",
        "has_gate_pressure",
        "has_temporal_risk",
    )
    for key in required_keys:
        if key not in signals:
            raise ValueError(f"signals missing required key: {key}")

    report = operational_readiness_check(
        dependencies=dependencies,
        recent_error_count=recent_error_count,
        reconcile_backlog=int(signals["reconcile_backlog"]),
        recent_reconcile_failures=int(signals["recent_reconcile_failures"]),
        reconcile_backlog_threshold=int(signals["reconcile_backlog_threshold"]),
        pending_gate_count=int(signals["pending_gate_count"]),
        stale_gate_threshold_seconds=float(signals.get("stale_gate_threshold_seconds", 0.0)),
        oldest_pending_gate_age_seconds=(
            None
            if signals.get("oldest_pending_gate_age_seconds") is None
            else float(signals["oldest_pending_gate_age_seconds"])
        ),
    )

    has_pressure = bool(signals["has_reconcile_pressure"]) or bool(signals["has_gate_pressure"])
    has_temporal_risk = bool(signals["has_temporal_risk"])
    if has_pressure or has_temporal_risk:
        return OperationalReadinessReport(
            ready=False,
            dependencies=report.dependencies,
            recent_error_count=report.recent_error_count,
            reconcile_backlog=report.reconcile_backlog,
            recent_reconcile_failures=report.recent_reconcile_failures,
            reconcile_backlog_threshold=report.reconcile_backlog_threshold,
            pending_gate_count=report.pending_gate_count,
            has_stale_gates=report.has_stale_gates,
            stale_gate_threshold_seconds=report.stale_gate_threshold_seconds,
            oldest_pending_gate_age_seconds=report.oldest_pending_gate_age_seconds,
        )
    return report
