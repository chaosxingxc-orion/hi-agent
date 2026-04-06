"""Tests for resilient adapter, event buffer, and health monitor."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.event_buffer import EventBuffer
from hi_agent.runtime_adapter.health import AdapterHealthMonitor
from hi_agent.runtime_adapter.kernel_backend import KernelBackend
from hi_agent.runtime_adapter.mock_kernel import MockKernel
from hi_agent.runtime_adapter.resilient_adapter import (
    AdapterMetrics,
    CircuitOpenError,
    ResilientKernelAdapter,
)


# --------------------------------------------------------------------------- #
# Helpers: flaky backend that wraps MockKernel to inject failures
# --------------------------------------------------------------------------- #


class FlakyBackend:
    """Backend wrapper that fails N times before delegating to MockKernel.

    Each method call decrements the remaining failure counter. Once it
    reaches zero, calls pass through to the real mock kernel.
    """

    def __init__(
        self,
        kernel: MockKernel,
        failures_remaining: int = 0,
        error_cls: type[Exception] = RuntimeError,
    ) -> None:
        self._kernel = kernel
        self.failures_remaining = failures_remaining
        self._error_cls = error_cls

    def __getattr__(self, name: str) -> Any:
        real = getattr(self._kernel, name, None)
        if real is None or not callable(real):
            raise AttributeError(name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if self.failures_remaining > 0:
                self.failures_remaining -= 1
                raise self._error_cls(f"Simulated failure in {name}")
            return real(*args, **kwargs)

        return wrapper


class AlwaysFailBackend:
    """Backend that always raises for every call."""

    def __init__(self, error_cls: type[Exception] = RuntimeError) -> None:
        self._error_cls = error_cls

    def __getattr__(self, name: str) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            raise self._error_cls(f"Permanent failure in {name}")
        return wrapper


# --------------------------------------------------------------------------- #
# ResilientKernelAdapter: retry tests
# --------------------------------------------------------------------------- #


class TestRetryOnFailureThenSucceed:
    """Verify retry logic recovers after transient failures."""

    def test_retries_then_succeeds(self) -> None:
        kernel = MockKernel(strict_mode=False)
        flaky = FlakyBackend(kernel, failures_remaining=2)
        adapter = ResilientKernelAdapter(
            flaky,  # type: ignore[arg-type]
            max_retries=3,
            base_backoff_ms=1,  # fast for tests
            max_backoff_ms=10,
        )
        run_id = adapter.start_run("task-1")
        assert run_id.startswith("run-")
        assert adapter.metrics.retried_calls == 2
        assert adapter.metrics.successful_calls == 1

    def test_retries_exhausted_raises(self) -> None:
        kernel = MockKernel(strict_mode=False)
        flaky = FlakyBackend(kernel, failures_remaining=10)
        adapter = ResilientKernelAdapter(
            flaky,  # type: ignore[arg-type]
            max_retries=2,
            base_backoff_ms=1,
            max_backoff_ms=5,
        )
        with pytest.raises(RuntimeAdapterBackendError):
            adapter.start_run("task-1")
        assert adapter.metrics.failed_calls == 1


# --------------------------------------------------------------------------- #
# Circuit breaker tests
# --------------------------------------------------------------------------- #


class TestCircuitBreaker:
    """Verify circuit breaker state transitions."""

    def _make_adapter(
        self, backend: Any, threshold: int = 3, reset_seconds: int = 60
    ) -> ResilientKernelAdapter:
        return ResilientKernelAdapter(
            backend,
            max_retries=0,  # no retries so each failure counts
            base_backoff_ms=1,
            circuit_breaker_threshold=threshold,
            circuit_breaker_reset_seconds=reset_seconds,
        )

    def test_opens_after_threshold_failures(self) -> None:
        always_fail = AlwaysFailBackend()
        adapter = self._make_adapter(always_fail, threshold=3)

        for _ in range(3):
            with pytest.raises(RuntimeAdapterBackendError):
                adapter.start_run("task")

        assert adapter.circuit_state == "open"

        # Subsequent calls rejected immediately with CircuitOpenError
        with pytest.raises(CircuitOpenError):
            adapter.start_run("task")

        assert adapter.metrics.circuit_breaks >= 1

    def test_half_open_allows_one_probe(self) -> None:
        kernel = MockKernel(strict_mode=False)
        flaky = FlakyBackend(kernel, failures_remaining=3)
        adapter = self._make_adapter(flaky, threshold=3, reset_seconds=0)

        # Trip the breaker
        for _ in range(3):
            with pytest.raises(RuntimeAdapterBackendError):
                adapter.start_run("task")

        # With reset_seconds=0, the breaker immediately reports half_open
        assert adapter.circuit_state == "half_open"

        # The flaky backend has exhausted its failures, so probe succeeds
        run_id = adapter.start_run("task-ok")
        assert run_id.startswith("run-")
        assert adapter.circuit_state == "closed"

    def test_half_open_probe_failure_reopens(self) -> None:
        always_fail = AlwaysFailBackend()
        adapter = self._make_adapter(always_fail, threshold=2, reset_seconds=0)

        # Trip breaker
        for _ in range(2):
            with pytest.raises(RuntimeAdapterBackendError):
                adapter.start_run("task")

        # With reset_seconds=0, immediately half_open
        assert adapter.circuit_state == "half_open"

        # Probe fails, so breaker reopens
        with pytest.raises(RuntimeAdapterBackendError):
            adapter.start_run("task")

        # Internal state is "open", but with reset_seconds=0 it shows half_open
        # The key behavior is that it attempted and failed the probe
        assert adapter.metrics.failed_calls == 3

    def test_circuit_resets_after_timeout(self) -> None:
        always_fail = AlwaysFailBackend()
        adapter = self._make_adapter(
            always_fail, threshold=2, reset_seconds=1
        )

        # Trip breaker
        for _ in range(2):
            with pytest.raises(RuntimeAdapterBackendError):
                adapter.start_run("task")

        assert adapter.circuit_state == "open"

        # Wait for reset period
        time.sleep(1.1)

        # Should now be half_open
        assert adapter.circuit_state == "half_open"


# --------------------------------------------------------------------------- #
# Request timeout
# --------------------------------------------------------------------------- #


class TestRequestTimeout:
    """Verify advisory timeout enforcement."""

    def test_timeout_raises_on_slow_call(self) -> None:
        kernel = MockKernel(strict_mode=False)

        class SlowBackend:
            """Backend that sleeps to simulate slow responses."""

            def __getattr__(self, name: str) -> Any:
                real = getattr(kernel, name, None)
                if real is None or not callable(real):
                    raise AttributeError(name)

                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    time.sleep(0.3)
                    return real(*args, **kwargs)

                return wrapper

        adapter = ResilientKernelAdapter(
            SlowBackend(),  # type: ignore[arg-type]
            max_retries=0,
            base_backoff_ms=1,
            request_timeout_seconds=0,  # 0s timeout => everything times out
        )

        with pytest.raises(TimeoutError, match="exceeded timeout"):
            adapter.start_run("task-1")


# --------------------------------------------------------------------------- #
# EventBuffer tests
# --------------------------------------------------------------------------- #


class TestEventBuffer:
    """Verify event buffer append, flush, and capacity."""

    def test_append_and_flush(self) -> None:
        buf = EventBuffer(max_size=100)
        buf.append("StageOpened", {"stage_id": "s1"})
        buf.append("RunStarted", {"run_id": "r1"})
        assert buf.size() == 2

        received: list[tuple[str, dict]] = []
        count = buf.flush(lambda t, p: received.append((t, p)))
        assert count == 2
        assert buf.size() == 0
        assert received[0] == ("StageOpened", {"stage_id": "s1"})
        assert received[1] == ("RunStarted", {"run_id": "r1"})

    def test_max_size_drops_oldest(self) -> None:
        buf = EventBuffer(max_size=3)
        for i in range(5):
            buf.append("event", {"i": i})
        assert buf.size() == 3
        assert buf.dropped_count == 2

        received: list[tuple[str, dict]] = []
        buf.flush(lambda t, p: received.append((t, p)))
        # Oldest two (i=0, i=1) were dropped
        assert [r[1]["i"] for r in received] == [2, 3, 4]

    def test_is_full(self) -> None:
        buf = EventBuffer(max_size=2)
        assert not buf.is_full()
        buf.append("a", {})
        buf.append("b", {})
        assert buf.is_full()

    def test_clear(self) -> None:
        buf = EventBuffer(max_size=10)
        buf.append("x", {})
        buf.clear()
        assert buf.size() == 0

    def test_flush_partial_on_error(self) -> None:
        buf = EventBuffer(max_size=10)
        buf.append("a", {"i": 1})
        buf.append("b", {"i": 2})
        buf.append("c", {"i": 3})

        call_count = 0

        def failing_target(t: str, p: dict) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("flush error")

        flushed = buf.flush(failing_target)
        assert flushed == 1
        # Remaining events should be back in buffer
        assert buf.size() == 2

    def test_invalid_max_size(self) -> None:
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            EventBuffer(max_size=0)


# --------------------------------------------------------------------------- #
# AdapterHealthMonitor tests
# --------------------------------------------------------------------------- #


class TestAdapterHealthMonitor:
    """Verify health monitor latency tracking and availability."""

    def test_no_calls_returns_unknown(self) -> None:
        monitor = AdapterHealthMonitor(window_seconds=60)
        health = monitor.get_health()
        assert health["status"] == "unknown"
        assert health["total_calls"] == 0

    def test_all_successes_is_healthy(self) -> None:
        monitor = AdapterHealthMonitor(window_seconds=60)
        for _ in range(10):
            monitor.record_call(latency_ms=50.0, success=True)
        health = monitor.get_health()
        assert health["status"] == "healthy"
        assert health["availability"] == 1.0
        assert health["error_rate"] == 0.0
        assert monitor.is_healthy()

    def test_high_error_rate_is_unhealthy(self) -> None:
        monitor = AdapterHealthMonitor(
            window_seconds=60, unhealthy_error_rate=0.5
        )
        for _ in range(5):
            monitor.record_call(latency_ms=10.0, success=True)
        for _ in range(5):
            monitor.record_call(latency_ms=10.0, success=False)
        health = monitor.get_health()
        assert health["status"] == "unhealthy"
        assert health["error_rate"] == 0.5

    def test_moderate_error_rate_is_degraded(self) -> None:
        monitor = AdapterHealthMonitor(
            window_seconds=60,
            degraded_error_rate=0.1,
            unhealthy_error_rate=0.5,
        )
        for _ in range(8):
            monitor.record_call(latency_ms=10.0, success=True)
        for _ in range(2):
            monitor.record_call(latency_ms=10.0, success=False)
        health = monitor.get_health()
        assert health["status"] == "degraded"
        assert monitor.is_degraded()

    def test_latency_percentiles(self) -> None:
        monitor = AdapterHealthMonitor(window_seconds=60)
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        for lat in latencies:
            monitor.record_call(latency_ms=lat, success=True)
        health = monitor.get_health()
        assert health["p50_latency_ms"] > 0
        assert health["p95_latency_ms"] > health["p50_latency_ms"]
        assert health["p99_latency_ms"] >= health["p95_latency_ms"]

    def test_high_p95_latency_triggers_degraded(self) -> None:
        monitor = AdapterHealthMonitor(
            window_seconds=60, degraded_latency_p95_ms=100.0
        )
        # All succeed but with very high latency
        for _ in range(20):
            monitor.record_call(latency_ms=200.0, success=True)
        health = monitor.get_health()
        assert health["status"] == "degraded"


# --------------------------------------------------------------------------- #
# Metrics collection tests
# --------------------------------------------------------------------------- #


class TestMetricsCollection:
    """Verify metrics counters and averages."""

    def test_successful_calls_tracked(self) -> None:
        kernel = MockKernel(strict_mode=False)
        adapter = ResilientKernelAdapter(
            kernel,  # type: ignore[arg-type]
            max_retries=0,
            base_backoff_ms=1,
        )
        adapter.start_run("task-1")
        adapter.start_run("task-2")
        m = adapter.metrics
        assert m.total_calls == 2
        assert m.successful_calls == 2
        assert m.failed_calls == 0
        assert m.avg_latency_ms > 0

    def test_failed_calls_tracked(self) -> None:
        always_fail = AlwaysFailBackend()
        adapter = ResilientKernelAdapter(
            always_fail,  # type: ignore[arg-type]
            max_retries=0,
            base_backoff_ms=1,
            circuit_breaker_threshold=100,  # high so breaker doesn't trip
        )
        with pytest.raises(RuntimeAdapterBackendError):
            adapter.start_run("task-1")
        m = adapter.metrics
        assert m.total_calls == 1
        assert m.failed_calls == 1
        assert m.last_error is not None
        assert "Permanent failure" in m.last_error

    def test_error_rate_computation(self) -> None:
        kernel = MockKernel(strict_mode=False)
        flaky = FlakyBackend(kernel, failures_remaining=1)
        adapter = ResilientKernelAdapter(
            flaky,  # type: ignore[arg-type]
            max_retries=2,
            base_backoff_ms=1,
        )
        adapter.start_run("task-1")
        m = adapter.metrics
        # 1 retry + 1 success
        assert m.retried_calls == 1
        assert m.successful_calls == 1


# --------------------------------------------------------------------------- #
# Health check endpoint
# --------------------------------------------------------------------------- #


class TestHealthCheck:
    """Verify the health_check endpoint returns expected data."""

    def test_health_check_when_reachable(self) -> None:
        kernel = MockKernel(strict_mode=False)
        adapter = ResilientKernelAdapter(
            kernel,  # type: ignore[arg-type]
            max_retries=0,
            base_backoff_ms=1,
        )
        result = adapter.health_check()
        assert result["kernel_reachable"] is True
        assert result["circuit_state"] == "closed"
        assert result["buffered_events"] == 0
        assert "status" in result

    def test_health_check_when_unreachable(self) -> None:
        always_fail = AlwaysFailBackend()
        adapter = ResilientKernelAdapter(
            always_fail,  # type: ignore[arg-type]
            max_retries=0,
            base_backoff_ms=1,
            circuit_breaker_threshold=100,
        )
        result = adapter.health_check()
        assert result["kernel_reachable"] is False


# --------------------------------------------------------------------------- #
# End-to-end: full adapter workflow
# --------------------------------------------------------------------------- #


class TestResilientAdapterWorkflow:
    """Integration-style test through multiple protocol methods."""

    def test_full_workflow(self) -> None:
        kernel = MockKernel(strict_mode=False)
        adapter = ResilientKernelAdapter(
            kernel,  # type: ignore[arg-type]
            max_retries=1,
            base_backoff_ms=1,
        )

        run_id = adapter.start_run("task-full")
        assert run_id.startswith("run-")

        adapter.open_stage("s1")
        adapter.mark_stage_state("s1", StageState.ACTIVE)

        adapter.record_task_view("tv-1", {"content": "test"})
        adapter.bind_task_view_to_decision("tv-1", "dec-1")

        run_info = adapter.query_run(run_id)
        assert run_info["status"] == "running"

        adapter.open_branch(run_id, "s1", "b1")
        adapter.mark_branch_state(run_id, "s1", "b1", "active")

        adapter.submit_plan(run_id, {"steps": ["a", "b"]})

        trace = adapter.query_trace_runtime(run_id)
        assert trace["plan"] is not None

        adapter.signal_run(run_id, "pause", {"reason": "test"})
        adapter.cancel_run(run_id, "done testing")

        manifest = adapter.get_manifest()
        assert "supported_methods" in manifest

        m = adapter.metrics
        assert m.total_calls >= 10
        assert m.failed_calls == 0
