"""Production-grade resilient adapter with retry, circuit breaker, and fallback.

Wraps a KernelAdapter to add resilience patterns for production use
without modifying the underlying adapter code.
"""

from __future__ import annotations

import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.event_buffer import EventBuffer
from hi_agent.runtime_adapter.health import AdapterHealthMonitor
from hi_agent.runtime_adapter.kernel_adapter import KernelAdapter
from hi_agent.runtime_adapter.kernel_backend import KernelBackend


@dataclass
class AdapterMetrics:
    """Aggregated metrics for the resilient adapter."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    retried_calls: int = 0
    circuit_breaks: int = 0
    avg_latency_ms: float = 0.0
    last_error: str | None = None

    # Internal accumulator for computing rolling average
    _total_latency_ms: float = field(default=0.0, repr=False)


# Exceptions considered transient and eligible for retry.
_TRANSIENT_EXCEPTIONS = (
    RuntimeAdapterBackendError,
    ConnectionError,
    TimeoutError,
    RuntimeError,
    OSError,
)


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and rejects calls."""

    def __init__(self, reset_at: float) -> None:
        """Initialize CircuitOpenError."""
        remaining = max(0.0, reset_at - time.monotonic())
        super().__init__(
            f"Circuit breaker is open; retry after {remaining:.1f}s"
        )
        self.reset_at = reset_at


class ResilientKernelAdapter:
    """Production wrapper around KernelAdapter with resilience patterns.

    Features:
    - Automatic retry with exponential backoff for transient failures
    - Circuit breaker to prevent cascade failures
    - Request timeout enforcement (advisory — uses wall-clock measurement)
    - Health check with degraded mode
    - Event buffering when kernel is unreachable
    - Metrics collection (call count, latency, error rate)
    """

    def __init__(
        self,
        backend: KernelBackend,
        *,
        max_retries: int = 3,
        base_backoff_ms: int = 500,
        max_backoff_ms: int = 10000,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_seconds: int = 60,
        request_timeout_seconds: int = 30,
        event_buffer_size: int = 1000,
        health_window_seconds: int = 300,
    ) -> None:
        """Initialize resilient adapter.

        Args:
            backend: The kernel backend to delegate to.
            max_retries: Maximum retry attempts for transient failures.
            base_backoff_ms: Base delay for exponential backoff.
            max_backoff_ms: Maximum backoff delay cap.
            circuit_breaker_threshold: Consecutive failures to trip breaker.
            circuit_breaker_reset_seconds: Seconds before half-open probe.
            request_timeout_seconds: Advisory timeout per request.
            event_buffer_size: Max events to buffer when kernel unreachable.
            health_window_seconds: Sliding window for health metrics.
        """
        self._adapter = KernelAdapter(backend=backend, strict_mode=True)
        self._backend = backend
        self._max_retries = max_retries
        self._base_backoff_ms = base_backoff_ms
        self._max_backoff_ms = max_backoff_ms
        self._request_timeout_seconds = request_timeout_seconds

        # Circuit breaker state
        self._cb_threshold = circuit_breaker_threshold
        self._cb_reset_seconds = circuit_breaker_reset_seconds
        self._cb_failure_count = 0
        self._cb_state = "closed"  # "closed" | "open" | "half_open"
        self._cb_open_since: float | None = None
        self._cb_lock = threading.Lock()

        # Event buffer for fire-and-forget operations during outages
        self._event_buffer = EventBuffer(max_size=event_buffer_size)

        # Health monitoring
        self._health_monitor = AdapterHealthMonitor(
            window_seconds=health_window_seconds
        )

        # Metrics
        self._metrics = AdapterMetrics()
        self._metrics_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # RuntimeAdapter protocol methods
    # ------------------------------------------------------------------ #

    def start_run(self, task_id: str) -> str:
        """Start a run with resilience wrapping."""
        return self._call_with_resilience("start_run", task_id)

    def open_stage(self, stage_id: str) -> None:
        """Open stage with resilience wrapping."""
        self._call_with_resilience("open_stage", stage_id)

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Update stage state with resilience wrapping."""
        self._call_with_resilience("mark_stage_state", stage_id, target)

    def record_task_view(
        self, task_view_id: str, content: dict[str, Any]
    ) -> str:
        """Record task view with resilience wrapping."""
        return self._call_with_resilience(
            "record_task_view", task_view_id, content
        )

    def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        """Bind task view to decision with resilience wrapping."""
        self._call_with_resilience(
            "bind_task_view_to_decision", task_view_id, decision_ref
        )

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Query run with resilience wrapping."""
        return self._call_with_resilience("query_run", run_id)

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel run with resilience wrapping."""
        self._call_with_resilience("cancel_run", run_id, reason)

    def resume_run(self, run_id: str) -> None:
        """Resume run with resilience wrapping."""
        self._call_with_resilience("resume_run", run_id)

    def signal_run(
        self,
        run_id: str,
        signal: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Signal run with resilience wrapping."""
        self._call_with_resilience("signal_run", run_id, signal, payload)

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Query trace runtime with resilience wrapping."""
        return self._call_with_resilience("query_trace_runtime", run_id)

    def stream_run_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Stream run events — delegated without retry (async iterator)."""
        return self._adapter.stream_run_events(run_id)  # type: ignore[return-value]

    def open_branch(
        self, run_id: str, stage_id: str, branch_id: str
    ) -> None:
        """Open branch with resilience wrapping."""
        self._call_with_resilience(
            "open_branch", run_id, stage_id, branch_id
        )

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Update branch state with resilience wrapping."""
        self._call_with_resilience(
            "mark_branch_state",
            run_id,
            stage_id,
            branch_id,
            state,
            failure_code,
        )

    def open_human_gate(self, request: HumanGateRequest) -> None:
        """Open human gate with resilience wrapping."""
        self._call_with_resilience("open_human_gate", request)

    def submit_approval(self, request: ApprovalRequest) -> None:
        """Submit approval with resilience wrapping."""
        self._call_with_resilience("submit_approval", request)

    def get_manifest(self) -> dict[str, Any]:
        """Return runtime manifest with resilience wrapping."""
        return self._call_with_resilience("get_manifest")

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        """Submit plan with resilience wrapping."""
        self._call_with_resilience("submit_plan", run_id, plan)

    # ------------------------------------------------------------------ #
    # Health & diagnostics
    # ------------------------------------------------------------------ #

    def health_check(self) -> dict[str, Any]:
        """Check kernel connectivity and return health status.

        Performs a lightweight manifest call to verify the backend
        is reachable, then combines with health monitor data.
        """
        try:
            start = time.monotonic()
            self._adapter.get_manifest()
            latency_ms = (time.monotonic() - start) * 1000
            self._health_monitor.record_call(latency_ms, success=True)
            kernel_reachable = True
        except Exception:
            kernel_reachable = False

        health = self._health_monitor.get_health()
        return {
            "kernel_reachable": kernel_reachable,
            "circuit_state": self.circuit_state,
            "buffered_events": self._event_buffer.size(),
            **health,
        }

    @property
    def metrics(self) -> AdapterMetrics:
        """Return current adapter metrics snapshot."""
        with self._metrics_lock:
            # Return a copy to prevent external mutation
            m = self._metrics
            return AdapterMetrics(
                total_calls=m.total_calls,
                successful_calls=m.successful_calls,
                failed_calls=m.failed_calls,
                retried_calls=m.retried_calls,
                circuit_breaks=m.circuit_breaks,
                avg_latency_ms=m.avg_latency_ms,
                last_error=m.last_error,
            )

    @property
    def circuit_state(self) -> str:
        """Return circuit breaker state: 'closed', 'open', or 'half_open'."""
        with self._cb_lock:
            if (
                self._cb_state == "open"
                and self._cb_open_since is not None
                and time.monotonic() - self._cb_open_since
                >= self._cb_reset_seconds
            ):
                return "half_open"
            return self._cb_state

    @property
    def event_buffer(self) -> EventBuffer:
        """Access the internal event buffer."""
        return self._event_buffer

    @property
    def inner_adapter(self) -> KernelAdapter:
        """Access the underlying KernelAdapter (for testing/diagnostics)."""
        return self._adapter

    # ------------------------------------------------------------------ #
    # Internal resilience logic
    # ------------------------------------------------------------------ #

    def _call_with_resilience(self, method: str, *args: Any) -> Any:
        """Execute adapter method with retry, circuit breaker, and metrics."""
        self._check_circuit_breaker()

        last_error: Exception | None = None
        retries_used = 0

        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                result = self._invoke(method, *args)
                latency_ms = (time.monotonic() - start) * 1000

                # Check advisory timeout
                if latency_ms > self._request_timeout_seconds * 1000:
                    raise TimeoutError(
                        f"{method} exceeded timeout of "
                        f"{self._request_timeout_seconds}s "
                        f"(took {latency_ms:.0f}ms)"
                    )

                self._on_success(latency_ms, retries_used)
                return result

            except Exception as exc:
                latency_ms = (time.monotonic() - start) * 1000
                last_error = exc

                if not self._is_transient(exc):
                    self._on_failure(latency_ms, retries_used, exc)
                    raise

                if attempt < self._max_retries:
                    retries_used += 1
                    backoff_ms = min(
                        self._base_backoff_ms * (2 ** attempt),
                        self._max_backoff_ms,
                    )
                    time.sleep(backoff_ms / 1000.0)
                else:
                    self._on_failure(latency_ms, retries_used, exc)
                    raise

        # Should not be reached, but satisfy type checker
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Unexpected state in resilient call to {method}")

    def _invoke(self, method: str, *args: Any) -> Any:
        """Call the method on the underlying adapter."""
        handler = getattr(self._adapter, method, None)
        if handler is None or not callable(handler):
            raise AttributeError(
                f"KernelAdapter does not have method '{method}'"
            )
        return handler(*args)

    def _is_transient(self, exc: Exception) -> bool:
        """Determine if an exception is transient and retryable.

        RuntimeAdapterBackendError wraps the original exception from the
        kernel backend. We check both the wrapper and its cause.
        """
        if isinstance(exc, _TRANSIENT_EXCEPTIONS):
            return True
        if isinstance(exc, RuntimeAdapterBackendError):
            cause = exc.__cause__
            if cause is not None and isinstance(cause, _TRANSIENT_EXCEPTIONS):
                return True
            # Backend errors are generally transient (network, timeout, etc.)
            return True
        return False

    def _check_circuit_breaker(self) -> None:
        """Enforce circuit breaker policy before allowing a call."""
        with self._cb_lock:
            if self._cb_state == "closed":
                return

            if self._cb_state == "open":
                if (
                    self._cb_open_since is not None
                    and time.monotonic() - self._cb_open_since
                    >= self._cb_reset_seconds
                ):
                    # Transition to half-open: allow one probe request
                    self._cb_state = "half_open"
                    return
                with self._metrics_lock:
                    self._metrics.circuit_breaks += 1
                raise CircuitOpenError(
                    (self._cb_open_since or 0.0) + self._cb_reset_seconds
                )

            # half_open — allow the probe through
            return

    def _on_success(self, latency_ms: float, retries_used: int) -> None:
        """Update state after a successful call."""
        self._health_monitor.record_call(latency_ms, success=True)
        with self._cb_lock:
            self._cb_failure_count = 0
            if self._cb_state == "half_open":
                self._cb_state = "closed"
                self._cb_open_since = None

        with self._metrics_lock:
            m = self._metrics
            m.total_calls += 1
            m.successful_calls += 1
            m.retried_calls += retries_used
            m._total_latency_ms += latency_ms
            m.avg_latency_ms = m._total_latency_ms / m.total_calls

        # Attempt to flush buffered events on success
        self._try_flush_buffer()

    def _on_failure(
        self, latency_ms: float, retries_used: int, exc: Exception
    ) -> None:
        """Update state after a failed call (all retries exhausted)."""
        self._health_monitor.record_call(latency_ms, success=False)

        with self._cb_lock:
            self._cb_failure_count += 1
            if self._cb_state == "half_open":
                # Probe failed — reopen
                self._cb_state = "open"
                self._cb_open_since = time.monotonic()
            elif self._cb_failure_count >= self._cb_threshold:
                self._cb_state = "open"
                self._cb_open_since = time.monotonic()

        with self._metrics_lock:
            m = self._metrics
            m.total_calls += 1
            m.failed_calls += 1
            m.retried_calls += retries_used
            m._total_latency_ms += latency_ms
            m.avg_latency_ms = m._total_latency_ms / m.total_calls
            m.last_error = f"{type(exc).__name__}: {exc}"

    def _try_flush_buffer(self) -> None:
        """Attempt to flush buffered events; failures are silently ignored."""
        if self._event_buffer.size() == 0:
            return
        try:
            def _deliver(event_type: str, payload: dict[str, Any]) -> None:
                handler = getattr(self._adapter, "_record", None)
                if handler and callable(handler):
                    handler(event_type, **payload)

            self._event_buffer.flush(_deliver)
        except Exception:
            pass  # Best-effort flush
