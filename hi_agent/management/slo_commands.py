"""Command-style wrappers for SLO evaluation helpers."""

from __future__ import annotations

from typing import Any

from hi_agent.management.slo import build_slo_snapshot


def cmd_slo_evaluate(metrics: dict[str, Any], *, objective: dict[str, Any]) -> dict[str, Any]:
    """Evaluate SLO targets against metrics and return command payload."""
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a dict")
    if not isinstance(objective, dict):
        raise ValueError("objective must be a dict")

    run_success_rate = metrics.get("run_success_rate", metrics.get("success_rate"))
    latency_p95_ms = metrics.get("latency_p95_ms", metrics.get("p95_latency_ms", 0.0))
    success_target = objective.get("success_target", objective.get("target", 0.99))
    latency_target_ms = objective.get(
        "latency_target_ms",
        objective.get("target_latency_ms", 5000.0),
    )

    if run_success_rate is None:
        raise ValueError("metrics must include run_success_rate or success_rate")

    snapshot = build_slo_snapshot(
        run_success_rate=float(run_success_rate),
        latency_p95_ms=float(latency_p95_ms),
        success_target=float(success_target),
        latency_target_ms=float(latency_target_ms),
    )
    return {
        "command": "slo_evaluate",
        "run_success_rate": snapshot.run_success_rate,
        "latency_p95_ms": snapshot.latency_p95_ms,
        "success_target": snapshot.success_target,
        "latency_target_ms": snapshot.latency_target_ms,
        "success_target_met": snapshot.success_target_met,
        "latency_target_met": snapshot.latency_target_met,
        "passed": snapshot.success_target_met and snapshot.latency_target_met,
    }


def cmd_slo_burn_rate(error_budget_remaining: float, window_hours: float) -> dict[str, Any]:
    """Calculate simple linearized SLO burn-rate signal."""
    remaining = float(error_budget_remaining)
    window = float(window_hours)
    if remaining < 0.0 or remaining > 1.0:
        raise ValueError("error_budget_remaining must be in [0, 1]")
    if window <= 0.0:
        raise ValueError("window_hours must be > 0")

    consumed = 1.0 - remaining
    burn_rate = consumed / window
    return {
        "command": "slo_burn_rate",
        "error_budget_remaining": remaining,
        "window_hours": window,
        "burn_rate_per_hour": burn_rate,
    }
