"""Temporal connectivity health helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import time


class TemporalConnectionState(StrEnum):
    """Normalized temporal connectivity states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class TemporalConnectionHealthReport:
    """Connection health snapshot for Temporal substrate checks."""

    state: TemporalConnectionState
    healthy: bool
    latency_ms: float | None
    last_success_age_seconds: float | None
    error: str | None


class TemporalConnectionHealthCheck:
    """Classify temporal connectivity with latency and last-success heuristics."""

    def __init__(
        self,
        *,
        ping_fn: Callable[[], float],
        now_fn: Callable[[], float] | None = None,
        degraded_latency_ms: float = 500.0,
        stale_success_seconds: float = 30.0,
    ) -> None:
        """Initialize temporal connection health checker."""
        if degraded_latency_ms < 0:
            raise ValueError("degraded_latency_ms must be >= 0")
        if stale_success_seconds < 0:
            raise ValueError("stale_success_seconds must be >= 0")
        self._ping_fn = ping_fn
        self._now_fn = now_fn or time
        self._degraded_latency_ms = degraded_latency_ms
        self._stale_success_seconds = stale_success_seconds
        self._last_success_at: float | None = None

    def check(self) -> TemporalConnectionHealthReport:
        """Run ping check and classify state."""
        now_value = float(self._now_fn())

        try:
            latency_ms = float(self._ping_fn())
            if latency_ms < 0:
                raise ValueError("ping latency must be >= 0")
            self._last_success_at = now_value
            state = (
                TemporalConnectionState.HEALTHY
                if latency_ms <= self._degraded_latency_ms
                else TemporalConnectionState.DEGRADED
            )
            return TemporalConnectionHealthReport(
                state=state,
                healthy=state is TemporalConnectionState.HEALTHY,
                latency_ms=latency_ms,
                last_success_age_seconds=0.0,
                error=None,
            )
        except Exception as exc:
            last_success_age_seconds = (
                None
                if self._last_success_at is None
                else max(0.0, now_value - self._last_success_at)
            )
            is_recent_success = (
                last_success_age_seconds is not None
                and self._stale_success_seconds > 0
                and last_success_age_seconds < self._stale_success_seconds
            )
            state = (
                TemporalConnectionState.DEGRADED
                if is_recent_success
                else TemporalConnectionState.UNREACHABLE
            )
            return TemporalConnectionHealthReport(
                state=state,
                healthy=False,
                latency_ms=None,
                last_success_age_seconds=last_success_age_seconds,
                error=f"{type(exc).__name__}: {exc}",
            )


@dataclass(frozen=True)
class TemporalConnectionProbeResult:
    """Compatibility result shape used by temporal health tests."""

    connected: bool
    degraded: bool
    latency_ms: float | None
    reason: str | None


def check_temporal_connection(
    probe_fn: Callable[[], None],
    *,
    now_fn: Callable[[], float] | None = None,
    degraded_latency_ms: float = 500.0,
) -> TemporalConnectionProbeResult:
    """Run a probe and classify connection status by measured latency."""
    clock = now_fn or time
    started_at = float(clock())
    try:
        probe_fn()
        ended_at = float(clock())
        latency_ms = round(max(0.0, (ended_at - started_at) * 1000.0), 6)
        return TemporalConnectionProbeResult(
            connected=True,
            degraded=latency_ms > degraded_latency_ms,
            latency_ms=latency_ms,
            reason=None,
        )
    except Exception as exc:
        return TemporalConnectionProbeResult(
            connected=False,
            degraded=True,
            latency_ms=None,
            reason=str(exc),
        )


# ------------------------------------------------------------------
# Substrate health reporting
# ------------------------------------------------------------------


class SubstrateNetworkState(StrEnum):
    """Three-state network partition detection model."""

    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class SubstrateHealthReport:
    """Health snapshot for any kernel substrate (Temporal or LocalFSM).

    Attributes:
        substrate_type: Identifier such as ``"temporal"`` or ``"local_fsm"``.
        network_state: Three-state partition detection result.
        healthy: True when substrate is fully operational.
        latency_ms: Round-trip latency when available.
        worker_running: True when the substrate worker task is alive.
        error: Error description when unhealthy.
    """

    substrate_type: str
    network_state: SubstrateNetworkState
    healthy: bool
    latency_ms: float | None = None
    worker_running: bool = True
    error: str | None = None


class SubstrateHealthChecker:
    """Unified health checker for Temporal and LocalFSM substrates.

    Wraps a ``health_fn`` that returns a dict with at minimum a
    ``"status"`` key (``"ok"`` / ``"degraded"`` / ``"unhealthy"``).

    For LocalFSM substrates, the health check always returns
    ``connected`` since there is no network dependency.
    """

    def __init__(
        self,
        *,
        substrate_type: str = "local_fsm",
        health_fn: Callable[[], dict[str, object]] | None = None,
        ping_fn: Callable[[], float] | None = None,
        degraded_latency_ms: float = 500.0,
    ) -> None:
        """Initialize substrate health checker.

        Args:
            substrate_type: Substrate identifier for reporting.
            health_fn: Optional callable returning ``{"status": ...}``.
                Used for facade-level health checks (e.g.
                ``KernelFacade.get_health()``).
            ping_fn: Optional callable returning latency in ms.
                Used for network-level probing (Temporal clusters).
            degraded_latency_ms: Latency threshold for degraded state.
        """
        self._substrate_type = substrate_type
        self._health_fn = health_fn
        self._ping_fn = ping_fn
        self._degraded_latency_ms = degraded_latency_ms

    def check(self) -> SubstrateHealthReport:
        """Probe substrate and return a health report."""
        if self._substrate_type == "local_fsm":
            return self._check_local()
        return self._check_remote()

    def _check_local(self) -> SubstrateHealthReport:
        """LocalFSM is always connected (in-process)."""
        error: str | None = None
        healthy = True
        if self._health_fn is not None:
            try:
                result = self._health_fn()
                status = result.get("status", "ok")
                if status == "unhealthy":
                    healthy = False
                    error = str(result.get("reason", "unhealthy"))
            except Exception as exc:
                healthy = False
                error = f"{type(exc).__name__}: {exc}"
        return SubstrateHealthReport(
            substrate_type=self._substrate_type,
            network_state=SubstrateNetworkState.CONNECTED,
            healthy=healthy,
            latency_ms=0.0,
            worker_running=True,
            error=error,
        )

    def _check_remote(self) -> SubstrateHealthReport:
        """Probe remote substrate via ping and health functions."""
        network_state = SubstrateNetworkState.CONNECTED
        healthy = True
        latency_ms: float | None = None
        error: str | None = None
        worker_running = True

        # Network-level ping
        if self._ping_fn is not None:
            try:
                latency_ms = float(self._ping_fn())
                if latency_ms > self._degraded_latency_ms:
                    network_state = SubstrateNetworkState.DEGRADED
            except Exception as exc:
                network_state = SubstrateNetworkState.DISCONNECTED
                healthy = False
                error = f"{type(exc).__name__}: {exc}"

        # Facade-level health
        if self._health_fn is not None and healthy:
            try:
                result = self._health_fn()
                status = result.get("status", "ok")
                if status == "unhealthy":
                    healthy = False
                    error = str(result.get("reason", "unhealthy"))
                elif status == "degraded":
                    network_state = SubstrateNetworkState.DEGRADED
                worker_running = result.get("worker_running", True) is True
            except Exception as exc:
                healthy = False
                error = f"{type(exc).__name__}: {exc}"

        return SubstrateHealthReport(
            substrate_type=self._substrate_type,
            network_state=network_state,
            healthy=healthy,
            latency_ms=latency_ms,
            worker_running=worker_running,
            error=error,
        )
