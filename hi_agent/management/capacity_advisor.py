"""Capacity tuning recommendations for server operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapacityRecommendation:
    """Actionable capacity recommendation item."""

    code: str
    severity: str
    summary: str
    action: str


def recommend_server_capacity_tuning(
    health_payload: dict[str, Any],
    metrics_snapshot: dict[str, Any] | None = None,
) -> list[CapacityRecommendation]:
    """Build capacity tuning recommendations from health + metrics payloads."""
    recs: list[CapacityRecommendation] = []
    metrics = metrics_snapshot or {}

    run_manager = dict(health_payload.get("subsystems", {}).get("run_manager", {}))
    queue_util = float(run_manager.get("queue_utilization", 0.0) or 0.0)
    queue_full = int(run_manager.get("queue_full_rejections", 0) or 0)
    queue_timeouts = int(run_manager.get("queue_timeouts", 0) or 0)
    capacity = int(run_manager.get("capacity", 0) or 0)

    if queue_full > 0 or queue_timeouts > 0:
        recs.append(
            CapacityRecommendation(
                code="scale_or_throttle_immediately",
                severity="high",
                summary=(
                    f"Queue drops detected (queue_full={queue_full}, "
                    f"queue_timeouts={queue_timeouts})."
                ),
                action=(
                    "Increase server_max_concurrent_runs and/or server_queue_size; "
                    "lower client-side concurrency burst; enforce stricter rate limit."
                ),
            )
        )
    elif queue_util >= 0.8:
        recs.append(
            CapacityRecommendation(
                code="queue_pressure_high",
                severity="medium",
                summary=f"Queue utilization is high ({queue_util:.2f}).",
                action=(
                    "Raise server_max_concurrent_runs by 25-50% and verify CPU saturation; "
                    "if CPU-bound, scale out more instances before increasing queue depth."
                ),
            )
        )

    if capacity > 0 and queue_util <= 0.1:
        recs.append(
            CapacityRecommendation(
                code="capacity_overprovisioned",
                severity="low",
                summary="Queue utilization remains very low under current traffic.",
                action=(
                    "Consider reducing max concurrency or instance count to save cost, "
                    "while retaining burst headroom."
                ),
            )
        )

    queue_reject_total = _metric_total(metrics, "server_queue_full_rejections_total")
    queue_timeout_total = _metric_total(metrics, "server_queue_timeouts_total")
    if queue_reject_total > 0 or queue_timeout_total > 0:
        recs.append(
            CapacityRecommendation(
                code="verify_sustained_queue_errors",
                severity="medium",
                summary=(
                    "Metrics show cumulative queue failures "
                    f"(rejects={queue_reject_total:.0f}, timeouts={queue_timeout_total:.0f})."
                ),
                action=(
                    "Run sustained load test with --duration-seconds and monitor /metrics/json "
                    "to validate whether errors are burst-only or continuous."
                ),
            )
        )

    return recs


def recommendations_to_payload(
    recommendations: list[CapacityRecommendation],
) -> list[dict[str, str]]:
    """Convert recommendations into JSON-friendly payload rows."""
    return [
        {
            "code": rec.code,
            "severity": rec.severity,
            "summary": rec.summary,
            "action": rec.action,
        }
        for rec in recommendations
    ]


def _metric_total(metrics_snapshot: dict[str, Any], metric_name: str) -> float:
    metric = metrics_snapshot.get(metric_name)
    if not isinstance(metric, dict):
        return 0.0
    if "_total" in metric:
        return float(metric.get("_total", 0.0))
    if not metric:
        return 0.0
    first_key = next(iter(metric))
    return float(metric.get(first_key, 0.0))
