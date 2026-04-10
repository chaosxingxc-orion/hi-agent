"""Adapter health monitoring with sliding window metrics."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class _CallRecord:
    """Single call observation."""

    timestamp: float
    latency_ms: float
    success: bool


class AdapterHealthMonitor:
    """Monitors kernel adapter health over a sliding time window.

    Tracks: latency percentiles, error rate, availability,
    and overall health status. Thread-safe.
    """

    def __init__(
        self,
        window_seconds: int = 300,
        *,
        degraded_error_rate: float = 0.1,
        unhealthy_error_rate: float = 0.5,
        degraded_latency_p95_ms: float = 5000.0,
    ) -> None:
        """Initialize health monitor.

        Args:
            window_seconds: Sliding window duration in seconds.
            degraded_error_rate: Error rate threshold for degraded status.
            unhealthy_error_rate: Error rate threshold for unhealthy status.
            degraded_latency_p95_ms: p95 latency threshold for degraded status.
        """
        self._window_seconds = window_seconds
        self._degraded_error_rate = degraded_error_rate
        self._unhealthy_error_rate = unhealthy_error_rate
        self._degraded_latency_p95_ms = degraded_latency_p95_ms
        self._records: deque[_CallRecord] = deque()
        self._lock = threading.Lock()

    def record_call(self, latency_ms: float, success: bool) -> None:
        """Record a call observation.

        Args:
            latency_ms: Call latency in milliseconds.
            success: Whether the call succeeded.
        """
        record = _CallRecord(
            timestamp=time.monotonic(),
            latency_ms=latency_ms,
            success=success,
        )
        with self._lock:
            self._records.append(record)
            self._evict_old()

    def get_health(self) -> dict[str, object]:
        """Return health summary.

        Returns:
            Dictionary with keys: status, availability, error_rate,
            total_calls, p50_latency_ms, p95_latency_ms, p99_latency_ms,
            window_seconds.
        """
        with self._lock:
            self._evict_old()
            records = list(self._records)

        total = len(records)
        if total == 0:
            return {
                "status": "unknown",
                "availability": 1.0,
                "error_rate": 0.0,
                "total_calls": 0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "window_seconds": self._window_seconds,
            }

        successes = sum(1 for r in records if r.success)
        availability = successes / total
        error_rate = 1.0 - availability

        latencies = sorted(r.latency_ms for r in records)
        p50 = self._percentile(latencies, 50)
        p95 = self._percentile(latencies, 95)
        p99 = self._percentile(latencies, 99)

        if error_rate >= self._unhealthy_error_rate:
            status = "unhealthy"
        elif error_rate >= self._degraded_error_rate or p95 >= self._degraded_latency_p95_ms:
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "availability": round(availability, 4),
            "error_rate": round(error_rate, 4),
            "total_calls": total,
            "p50_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "p99_latency_ms": round(p99, 2),
            "window_seconds": self._window_seconds,
        }

    def is_healthy(self) -> bool:
        """Return True if adapter is in healthy state."""
        return self.get_health()["status"] == "healthy"

    def is_degraded(self) -> bool:
        """Return True if adapter is in degraded state."""
        return self.get_health()["status"] == "degraded"

    def _evict_old(self) -> None:
        """Remove records outside the sliding window. Must hold lock."""
        cutoff = time.monotonic() - self._window_seconds
        while self._records and self._records[0].timestamp < cutoff:
            self._records.popleft()

    @staticmethod
    def _percentile(sorted_values: list[float], pct: int) -> float:
        """Compute percentile from pre-sorted values."""
        if not sorted_values:
            return 0.0
        n = len(sorted_values)
        idx = (pct / 100.0) * (n - 1)
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        frac = idx - lower
        return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])
