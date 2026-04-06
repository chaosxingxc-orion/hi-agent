"""Unit tests for reconcile daemon background ticking behavior."""

from __future__ import annotations

import threading

from hi_agent.management.reconcile_daemon import ReconcileDaemon


class _TickStub:
    """Simple tick source with deterministic success/failure sequence."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.lock = threading.Lock()

    def tick(self) -> object:
        """Return or raise the next configured outcome."""
        with self.lock:
            self.calls += 1
            index = min(self.calls - 1, len(self._outcomes) - 1)
            outcome = self._outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_run_once_tick_updates_counters_and_last_error() -> None:
    """Daemon should record failures and recover with subsequent successful ticks."""
    runtime = _TickStub(outcomes=[RuntimeError("boom"), {"ok": True}])
    daemon = ReconcileDaemon(
        runtime,
        interval_seconds=1.0,
        sleeper=lambda _: None,
        clock=lambda: 42.0,
    )

    first = daemon.run_once_tick()
    second = daemon.run_once_tick()

    assert first is None
    assert second == {"ok": True}
    assert daemon.tick_attempt_count == 2
    assert daemon.tick_success_count == 1
    assert daemon.tick_failure_count == 1
    assert daemon.last_error is None


def test_start_runs_background_loop_without_real_sleep_and_stop_halts_it() -> None:
    """Daemon should tick in a background thread and stop cleanly on request."""
    ticked_three_times = threading.Event()

    class _BackgroundTickStub:
        def __init__(self) -> None:
            self.calls = 0
            self.lock = threading.Lock()

        def tick(self) -> dict[str, int]:
            with self.lock:
                self.calls += 1
                if self.calls >= 3:
                    ticked_three_times.set()
                return {"calls": self.calls}

    runtime = _BackgroundTickStub()
    sleeper_calls: list[float] = []

    def fake_sleeper(seconds: float) -> None:
        sleeper_calls.append(seconds)

    daemon = ReconcileDaemon(
        runtime,
        interval_seconds=0.5,
        sleeper=fake_sleeper,
        clock=lambda: 100.0,
    )

    assert daemon.start() is True
    assert ticked_three_times.wait(timeout=1.0)

    assert daemon.stop() is True
    assert daemon.is_running is False
    assert daemon.tick_attempt_count >= 3
    assert daemon.tick_success_count >= 3
    assert daemon.tick_failure_count == 0
    assert sleeper_calls
    assert all(value == 0.5 for value in sleeper_calls)


def test_start_and_stop_are_idempotent() -> None:
    """Repeated start/stop calls should be safe and report no state transitions."""
    runtime = _TickStub(outcomes=[{"ok": True}])
    daemon = ReconcileDaemon(
        runtime,
        interval_seconds=1.0,
        sleeper=lambda _: None,
        clock=lambda: 1.0,
    )

    assert daemon.start() is True
    assert daemon.start() is False
    assert daemon.stop() is True
    assert daemon.stop() is False


def test_run_once_tick_is_safe_under_parallel_calls() -> None:
    """Concurrent manual ticks should update counters safely."""
    runtime = _TickStub(outcomes=[{"ok": True}])
    daemon = ReconcileDaemon(
        runtime,
        interval_seconds=1.0,
        sleeper=lambda _: None,
        clock=lambda: 10.0,
    )

    threads = [threading.Thread(target=daemon.run_once_tick) for _ in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert daemon.tick_attempt_count == 25
    assert daemon.tick_success_count == 25
    assert daemon.tick_failure_count == 0
    assert daemon.last_error is None
