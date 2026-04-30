"""ResilientKernelAdapter: unified resilience wrapper for kernel adapters.

This fills the G8 audit gap: EventBuffer, AdapterHealthMonitor, and
ConsistencyJournal were implemented as separate components but never
assembled into a single usable adapter.

Architecture
------------
``ResilientKernelAdapter`` wraps any inner adapter that satisfies the
RuntimeAdapter protocol and adds:

* **Retry with exponential backoff** — transient errors are retried up to
  ``max_retries`` times before propagating to callers.
* **Circuit breaker** — when the health monitor marks the adapter
  "unhealthy" (error rate ≥ ``unhealthy_error_rate``), calls fail fast
  without attempting the inner adapter.
* **Event buffer** — write operations that fail after all retries are
  serialised into an ``EventBuffer`` for later replay when the kernel
  recovers.
* **Consistency journal** — every write that succeeds locally but fails
  in the backend is appended to the journal for reconciliation.
* **Health monitoring** — every call's latency and outcome are recorded
  in the ``AdapterHealthMonitor`` sliding window.

Usage::

    inner = KernelFacadeAdapter(facade)
    adapter = ResilientKernelAdapter(inner, journal=InMemoryConsistencyJournal())

    # Optionally persist the consistency journal across restarts:
    journal = FileBackedConsistencyJournal(".hi_agent/consistency.jsonl")
    adapter = ResilientKernelAdapter(inner, journal=journal)

    # When the kernel recovers, replay buffered events:
    adapter.replay_buffered()
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from hi_agent.runtime_adapter.consistency import (
    ConsistencyIssue,
    InMemoryConsistencyJournal,
)
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.event_buffer import EventBuffer
from hi_agent.runtime_adapter.health import AdapterHealthMonitor

logger = logging.getLogger(__name__)

# Protocol methods that mutate state (written to event buffer on failure)
_WRITE_METHODS = frozenset(
    {
        "open_stage",
        "mark_stage_state",
        "record_task_view",
        "bind_task_view_to_decision",
        "start_run",
        "cancel_run",
        "resume_run",
        "signal_run",
        "open_branch",
        "mark_branch_state",
        "open_human_gate",
        "submit_approval",
        "spawn_child_run",
        "spawn_child_run_async",
    }
)


class ResilientKernelAdapter:
    """Resilience wrapper: retry + circuit breaker + buffer + journal + health.

    Wraps any inner adapter implementing the RuntimeAdapter protocol.  All
    public method calls are intercepted to add resiliency behaviour.  The
    wrapper is transparent — it forwards all attribute lookups to the inner
    adapter for any method not explicitly overridden.
    """

    def __init__(
        self,
        inner: Any,
        *,
        max_retries: int = 3,
        base_delay_s: float = 0.5,
        buffer_max_size: int = 1000,
        health_window_s: int = 300,
        degraded_error_rate: float = 0.1,
        unhealthy_error_rate: float = 0.5,
        journal: InMemoryConsistencyJournal | None = None,
    ) -> None:
        """Create a resilient wrapper around *inner*.

        Args:
            inner: The wrapped RuntimeAdapter implementation.
            max_retries: Number of retry attempts on transient failure (0 = no
                retries; first attempt is not counted).
            base_delay_s: Base backoff delay in seconds; doubles each retry.
            buffer_max_size: Maximum events to buffer when kernel is down.
            health_window_s: Sliding window (seconds) for health monitoring.
            degraded_error_rate: Error rate that puts adapter into degraded state.
            unhealthy_error_rate: Error rate that opens the circuit breaker.
            journal: Optional consistency journal.  Defaults to an in-memory
                journal.  Pass a ``FileBackedConsistencyJournal`` for durable
                tracking.
        """
        self._inner = inner
        self._max_retries = max_retries
        self._base_delay_s = base_delay_s
        self._buffer = EventBuffer(max_size=buffer_max_size)
        self._health = AdapterHealthMonitor(
            window_seconds=health_window_s,
            degraded_error_rate=degraded_error_rate,
            unhealthy_error_rate=unhealthy_error_rate,
        )
        if journal is None:
            raise ValueError(
                "journal is required; pass an explicit InMemoryConsistencyJournal() instance"
            )
        self._journal = journal

    # ------------------------------------------------------------------
    # Resilience core
    # ------------------------------------------------------------------

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call *method_name* on inner adapter with retry + circuit breaker.

        Raises:
        ------
        RuntimeAdapterBackendError
            When the circuit is open or all retries are exhausted.
        """
        health = self._health.get_health()
        if health["status"] == "unhealthy":
            logger.warning(
                "ResilientKernelAdapter: circuit open for %r (error_rate=%.2f)",
                method_name,
                health["error_rate"],
            )
            cause = RuntimeError(
                f"Circuit open: kernel adapter unhealthy (error_rate={health['error_rate']:.2f})"
            )
            raise RuntimeAdapterBackendError(
                method_name,
                cause=cause,
            ) from cause

        method = getattr(self._inner, method_name)
        last_exc: Exception | None = None
        attempts = self._max_retries + 1

        for attempt in range(attempts):
            t0 = time.monotonic()
            try:
                result = method(*args, **kwargs)
                latency_ms = (time.monotonic() - t0) * 1000.0
                self._health.record_call(latency_ms, success=True)
                return result
            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000.0
                self._health.record_call(latency_ms, success=False)
                last_exc = exc
                if attempt < self._max_retries:
                    delay = self._base_delay_s * (2**attempt)
                    logger.debug(
                        "ResilientKernelAdapter: %r attempt %d/%d failed (%s), retrying in %.2fs",
                        method_name,
                        attempt + 1,
                        attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)

        # All retries exhausted — buffer write ops for later replay
        if method_name in _WRITE_METHODS:
            self._buffer.append(method_name, {"args": list(args), "kwargs": kwargs})
            self._journal.append(
                ConsistencyIssue(
                    operation=method_name,
                    context={"args": list(args), "kwargs": kwargs},
                    error=str(last_exc),
                )
            )
            logger.warning(
                "ResilientKernelAdapter: %r buffered after %d retries (%s)",
                method_name,
                attempts,
                last_exc,
            )

        if last_exc is None:
            raise AssertionError(
                f"resilient adapter exhausted retries without capturing exception "
                f"(method={method_name!r}, attempts={attempts})"
            )
        cause = last_exc
        # B4: classify exception to FailureCode and emit labeled counter.
        try:
            from hi_agent.failures.taxonomy import FailureCode
            from hi_agent.observability.collector import get_metrics_collector

            _mc = get_metrics_collector()
            if _mc is not None:
                if isinstance(cause, TimeoutError):
                    _fc = FailureCode.CALLBACK_TIMEOUT
                elif isinstance(cause, RuntimeError) and "budget" in str(cause).lower():
                    _fc = FailureCode.EXECUTION_BUDGET_EXHAUSTED
                else:
                    _fc = FailureCode.INVALID_CONTEXT
                _mc.increment(
                    "hi_agent_failure_total",
                    labels={"failure_code": _fc.value},
                )
        except Exception:  # rule7-exempt: expiry_wave="Wave 27" replacement_test: wave22-tests
            pass
        raise RuntimeAdapterBackendError(method_name, cause=cause) from cause

    def replay_buffered(self) -> int:
        """Flush buffered write operations to the inner adapter.

        Call this when the kernel connection is restored.  Events are
        replayed in FIFO order.  Returns the number of events replayed.
        """

        def _dispatch(method_name: str, payload: dict) -> None:
            method = getattr(self._inner, method_name)
            method(*payload.get("args", []), **payload.get("kwargs", {}))

        replayed = self._buffer.flush(_dispatch)
        if replayed:
            logger.info("ResilientKernelAdapter: replayed %d buffered event(s)", replayed)
        return replayed

    @property
    def mode(self) -> Literal["local-fsm", "http"]:
        """The kernel execution mode — delegates to the inner adapter."""
        return getattr(self._inner, "mode", "local-fsm")

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, object]:
        """Return the current health summary from the sliding window monitor."""
        return self._health.get_health()

    def get_buffer_size(self) -> int:
        """Return the number of write events currently buffered."""
        return self._buffer.size()

    def get_journal_issues(self) -> list[ConsistencyIssue]:
        """Return all recorded consistency issues."""
        return self._journal.list_issues()

    # ------------------------------------------------------------------
    # RuntimeAdapter protocol delegation
    # ------------------------------------------------------------------

    def open_stage(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate open_stage with resilience."""
        return self._call("open_stage", *args, **kwargs)

    def mark_stage_state(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate mark_stage_state with resilience."""
        return self._call("mark_stage_state", *args, **kwargs)

    def record_task_view(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate record_task_view with resilience."""
        return self._call("record_task_view", *args, **kwargs)

    def bind_task_view_to_decision(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate bind_task_view_to_decision with resilience."""
        return self._call("bind_task_view_to_decision", *args, **kwargs)

    def start_run(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate start_run with resilience."""
        return self._call("start_run", *args, **kwargs)

    def query_run(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate query_run with resilience."""
        return self._call("query_run", *args, **kwargs)

    def cancel_run(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate cancel_run with resilience."""
        return self._call("cancel_run", *args, **kwargs)

    def resume_run(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate resume_run with resilience."""
        return self._call("resume_run", *args, **kwargs)

    def signal_run(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate signal_run with resilience."""
        return self._call("signal_run", *args, **kwargs)

    def query_trace_runtime(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate query_trace_runtime with resilience."""
        return self._call("query_trace_runtime", *args, **kwargs)

    def stream_run_events(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate stream_run_events with resilience."""
        return self._call("stream_run_events", *args, **kwargs)

    def open_branch(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate open_branch with resilience."""
        return self._call("open_branch", *args, **kwargs)

    def mark_branch_state(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate mark_branch_state with resilience."""
        return self._call("mark_branch_state", *args, **kwargs)

    def open_human_gate(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate open_human_gate with resilience."""
        return self._call("open_human_gate", *args, **kwargs)

    def submit_approval(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate submit_approval with resilience."""
        return self._call("submit_approval", *args, **kwargs)

    def get_manifest(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate get_manifest with resilience."""
        return self._call("get_manifest", *args, **kwargs)

    def query_run_postmortem(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate query_run_postmortem with resilience."""
        return self._call("query_run_postmortem", *args, **kwargs)

    def spawn_child_run(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate spawn_child_run with resilience."""
        return self._call("spawn_child_run", *args, **kwargs)

    def query_child_runs(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate query_child_runs with resilience."""
        return self._call("query_child_runs", *args, **kwargs)

    def spawn_child_run_async(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate spawn_child_run_async with resilience."""
        return self._call("spawn_child_run_async", *args, **kwargs)

    def query_child_runs_async(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate query_child_runs_async with resilience."""
        return self._call("query_child_runs_async", *args, **kwargs)

    def execute_turn(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate execute_turn with resilience."""
        return self._call("execute_turn", *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Fall through to inner adapter for any method not explicitly defined."""
        return getattr(self._inner, name)
