"""SLO helpers for operational reporting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SLOSnapshot:
    """Minimal SLO snapshot for run success and latency targets."""

    run_success_rate: float
    latency_p95_ms: float
    success_target: float
    latency_target_ms: float
    success_target_met: bool
    latency_target_met: bool


def build_slo_snapshot(
    *,
    run_success_rate: float,
    latency_p95_ms: float | None = None,
    success_target: float = 0.99,
    latency_target_ms: float = 5000.0,
    avg_token_per_run: float | None = None,
    token_budget: float | None = None,
) -> SLOSnapshot:
    """Build SLO snapshot with target-evaluation booleans.

    Backward compatibility:
      - `avg_token_per_run` maps to `latency_p95_ms` when latency is omitted.
      - `token_budget` maps to `latency_target_ms`.
    """
    if latency_p95_ms is None:
        if avg_token_per_run is None:
            raise ValueError("latency_p95_ms is required when avg_token_per_run is not provided")
        latency_p95_ms = float(avg_token_per_run)

    if token_budget is not None:
        latency_target_ms = float(token_budget)

    if run_success_rate < 0 or run_success_rate > 1:
        raise ValueError("run_success_rate must be in [0, 1]")
    if latency_p95_ms < 0:
        raise ValueError("latency_p95_ms must be >= 0")
    if success_target < 0 or success_target > 1:
        raise ValueError("success_target must be in [0, 1]")
    if latency_target_ms <= 0:
        raise ValueError("latency_target_ms must be > 0")

    return SLOSnapshot(
        run_success_rate=float(run_success_rate),
        latency_p95_ms=float(latency_p95_ms),
        success_target=float(success_target),
        latency_target_ms=float(latency_target_ms),
        success_target_met=run_success_rate >= success_target,
        latency_target_met=latency_p95_ms <= latency_target_ms,
    )
