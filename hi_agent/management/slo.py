"""SLO helpers for operational reporting and continuous monitoring."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.observability.collector import MetricsCollector

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class SLOViolation:
    """A single SLO violation event emitted by :class:`SLOMonitor`."""

    timestamp: float
    dimension: str          # "success_rate" or "latency_p95_ms"
    current_value: float
    target_value: float
    snapshot: SLOSnapshot


class SLOMonitor:
    """Continuous SLO monitor that evaluates snapshots on a fixed interval.

    This fills the G3 audit gap: :func:`build_slo_snapshot` was only a
    point-in-time evaluator; :class:`SLOMonitor` wraps it in an asyncio
    background loop that fires ``on_violation`` callbacks automatically.

    Usage::

        monitor = SLOMonitor(metrics_collector, on_violation=handle_violation)
        await monitor.start()
        ...
        await monitor.stop()
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        *,
        interval_s: float = 60.0,
        success_target: float = 0.99,
        latency_target_ms: float = 5000.0,
        on_violation: Callable[[SLOViolation], None] | None = None,
    ) -> None:
        """Initialize SLOMonitor.

        Args:
            metrics: The shared :class:`MetricsCollector` to read from.
            interval_s: Seconds between evaluation cycles.
            success_target: Minimum acceptable run success rate (0-1).
            latency_target_ms: Maximum acceptable p95 stage latency in ms.
            on_violation: Optional callback invoked for each violated dimension.
        """
        self._metrics = metrics
        self._interval_s = interval_s
        self._success_target = success_target
        self._latency_target_ms = latency_target_ms
        self._on_violation = on_violation
        self._task: asyncio.Task | None = None
        self._last_snapshot: SLOSnapshot | None = None
        self._violations: list[SLOViolation] = []

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="slo-monitor")

    async def stop(self) -> None:
        """Stop the background monitoring loop gracefully."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    def check_now(self) -> SLOSnapshot | None:
        """Evaluate SLOs immediately and return the snapshot.

        Also fires ``on_violation`` for any violated dimension.
        Returns ``None`` when there is not yet enough metric data.
        """
        snapshot = self._build_snapshot()
        if snapshot is None:
            return None
        self._last_snapshot = snapshot
        self._emit_violations(snapshot)
        return snapshot

    @property
    def last_snapshot(self) -> SLOSnapshot | None:
        """Most recent snapshot evaluated by the monitor."""
        return self._last_snapshot

    def get_violations(self) -> list[SLOViolation]:
        """Return all violations recorded since the monitor was created."""
        return list(self._violations)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Evaluate SLOs on *interval_s* cadence until cancelled."""
        while True:
            try:
                self.check_now()
            except Exception:
                logger.exception("SLOMonitor: error during evaluation")
            await asyncio.sleep(self._interval_s)

    def _build_snapshot(self) -> SLOSnapshot | None:
        """Read current metrics and build an SLO snapshot.

        Returns ``None`` when there is no run data yet.
        """
        snap = self._metrics.snapshot()
        runs = snap.get("runs_total", {})

        completed = 0.0
        failed = 0.0
        for label_key, val in runs.items():
            if 'status="completed"' in label_key or "status=completed" in label_key:
                completed += val
            elif 'status="failed"' in label_key or "status=failed" in label_key:
                failed += val

        total = completed + failed
        if total == 0:
            return None  # not enough data to evaluate

        success_rate = completed / total

        # p95 stage latency: stage_duration_seconds histogram → ms
        stage_hist = snap.get("stage_duration_seconds", {})
        latency_p95_ms = 0.0
        for entry in stage_hist.values():
            if isinstance(entry, dict) and "p95" in entry:
                latency_p95_ms = max(latency_p95_ms, entry["p95"] * 1000.0)

        try:
            return build_slo_snapshot(
                run_success_rate=success_rate,
                latency_p95_ms=latency_p95_ms if latency_p95_ms > 0 else 1.0,
                success_target=self._success_target,
                latency_target_ms=self._latency_target_ms,
            )
        except ValueError:  # rule7-exempt: expiry_wave="Wave 22" replacement_test: wave22-tests
            return None

    def _emit_violations(self, snapshot: SLOSnapshot) -> None:
        now = time()
        if not snapshot.success_target_met:
            v = SLOViolation(
                timestamp=now,
                dimension="success_rate",
                current_value=snapshot.run_success_rate,
                target_value=snapshot.success_target,
                snapshot=snapshot,
            )
            self._violations.append(v)
            if self._on_violation is not None:
                try:
                    self._on_violation(v)
                except Exception:
                    logger.exception("SLOMonitor: on_violation callback error")
        if not snapshot.latency_target_met:
            v = SLOViolation(
                timestamp=now,
                dimension="latency_p95_ms",
                current_value=snapshot.latency_p95_ms,
                target_value=snapshot.latency_target_ms,
                snapshot=snapshot,
            )
            self._violations.append(v)
            if self._on_violation is not None:
                try:
                    self._on_violation(v)
                except Exception:
                    logger.exception("SLOMonitor: on_violation callback error")
