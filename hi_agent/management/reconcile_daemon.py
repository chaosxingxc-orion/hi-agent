"""Lightweight daemon for periodic reconcile background ticking."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

from hi_agent.management.reconcile_runtime import ReconcileRuntimeController
from hi_agent.management.reconcile_supervisor import ReconcileSupervisor


class _TickSource(Protocol):
    """Minimal runtime contract required by the reconcile daemon."""

    def tick(self) -> object:
        """Execute one reconcile tick cycle."""


class ReconcileDaemon:
    """Run periodic reconcile ticks in a lightweight background thread."""

    def __init__(
        self,
        runtime: ReconcileRuntimeController | ReconcileSupervisor | _TickSource,
        *,
        interval_seconds: float,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize daemon dependencies and timing controls.

        Args:
          runtime: Runtime controller or supervisor that exposes ``tick()``.
          interval_seconds: Delay between periodic background ticks.
          sleeper: Injectable sleep function for deterministic tests.
          clock: Injectable monotonic clock for deterministic tests.

        Raises:
          ValueError: If ``interval_seconds`` is not positive.
        """
        if interval_seconds <= 0:
            msg = "interval_seconds must be > 0"
            raise ValueError(msg)

        self._runtime = runtime
        self._interval_seconds = interval_seconds
        self._sleeper = sleeper
        self._clock = clock

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._is_running = False

        self._tick_attempt_count = 0
        self._tick_success_count = 0
        self._tick_failure_count = 0
        self._last_error: Exception | None = None
        self._last_tick_seconds: float | None = None

    @property
    def is_running(self) -> bool:
        """Whether the background reconcile loop is currently active."""
        with self._lock:
            return self._is_running

    @property
    def tick_attempt_count(self) -> int:
        """Total number of tick attempts made by this daemon."""
        with self._lock:
            return self._tick_attempt_count

    @property
    def tick_success_count(self) -> int:
        """Total number of successful tick executions."""
        with self._lock:
            return self._tick_success_count

    @property
    def tick_failure_count(self) -> int:
        """Total number of failed tick executions."""
        with self._lock:
            return self._tick_failure_count

    @property
    def last_error(self) -> Exception | None:
        """Most recent tick error, cleared on the next successful tick."""
        with self._lock:
            return self._last_error

    @property
    def last_tick_seconds(self) -> float | None:
        """Clock timestamp captured after the most recent tick attempt."""
        with self._lock:
            return self._last_tick_seconds

    def start(self) -> bool:
        """Start the background ticking loop.

        Returns:
          True if the daemon transitioned to running state; otherwise False.
        """
        with self._lock:
            if self._is_running:
                return False
            self._stop_event.clear()
            thread = threading.Thread(target=self._run_loop, name="reconcile-daemon", daemon=True)
            self._thread = thread
            self._is_running = True

        thread.start()
        return True

    def stop(self) -> bool:
        """Stop the background ticking loop and join the worker thread.

        Returns:
          True if the daemon transitioned to stopped state; otherwise False.
        """
        with self._lock:
            if not self._is_running:
                return False
            self._stop_event.set()
            thread = self._thread

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

        with self._lock:
            self._is_running = False
            self._thread = None
        return True

    def run_once_tick(self) -> object | None:
        """Execute one tick cycle and update counters/error state safely.

        Returns:
          Tick report object when successful; otherwise ``None`` on failure.
        """
        with self._lock:
            self._tick_attempt_count += 1

        try:
            report = self._runtime.tick()
        except Exception as error:
            with self._lock:
                self._tick_failure_count += 1
                self._last_error = error
                self._last_tick_seconds = self._clock()
            return None

        with self._lock:
            self._tick_success_count += 1
            self._last_error = None
            self._last_tick_seconds = self._clock()
        return report

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once_tick()
            self._sleeper(self._interval_seconds)
