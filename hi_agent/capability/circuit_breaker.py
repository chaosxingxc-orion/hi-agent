"""Simple circuit breaker for capability calls."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal

CircuitStatus = Literal["closed", "open", "half_open"]


@dataclass
class CircuitState:
    """Circuit state metrics for one capability."""

    failures: int = 0
    status: CircuitStatus = "closed"
    opened_at: float | None = None

    @property
    def opened(self) -> bool:
        """Backward-compatible open flag."""
        return self.status == "open"


class CircuitBreaker:  # scope: process-internal
    """Failure-count based circuit breaker (per-capability, not a shared server resource)."""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] | None = None,
        db_path: str | None = None,
    ) -> None:
        """Initialize breaker state.

        Args:
          failure_threshold: Number of consecutive failures before opening.
          cooldown_seconds: Time to wait before allowing half-open probes.
          clock: Optional monotonic clock provider in seconds.
          db_path: Optional SQLite path for persistent state. When None,
            all state is kept in memory only (identical to previous behavior).
            Use ":memory:" for an in-process SQLite store without a file.
        """
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock or monotonic
        self._states: dict[str, CircuitState] = {}
        self._db: sqlite3.Connection | None = None
        self._db_lock: threading.Lock | None = None
        if db_path is not None:
            self._db_lock = threading.Lock()
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS circuit_breaker_state"
                " (name TEXT PRIMARY KEY, state TEXT, opened_at REAL, failures INTEGER)"
            )
            self._db.commit()
            # Load persisted "open" states so restarts respect prior trips
            cursor = self._db.execute(
                "SELECT name, state, opened_at, failures"
                " FROM circuit_breaker_state WHERE state = 'open'"
            )
            for row in cursor.fetchall():
                name, state_str, opened_at, failures = row
                self._states[name] = CircuitState(
                    failures=failures,
                    status=state_str,  # type: ignore[arg-type]  expiry_wave: Wave 26
                    opened_at=opened_at,
                )

    def _persist_state(self, name: str) -> None:
        """Write current in-memory state for *name* to SQLite (no-op when no db)."""
        if self._db is None:
            return
        state = self._states.get(name, CircuitState())
        assert self._db_lock is not None
        with self._db_lock:
            self._db.execute(
                "INSERT OR REPLACE INTO circuit_breaker_state"
                " (name, state, opened_at, failures) VALUES (?, ?, ?, ?)",
                (name, state.status, state.opened_at, state.failures),
            )
            self._db.commit()

    def close(self) -> None:
        """Close the SQLite connection if one was opened."""
        if self._db is not None:
            self._db.close()
            self._db = None

    def allow(self, capability_name: str) -> bool:
        """Return whether call is allowed."""
        state = self._states.get(capability_name, CircuitState())
        if state.status == "closed":
            return True
        if state.status == "half_open":
            return True
        if state.opened_at is None:
            return False
        if self.clock() - state.opened_at >= self.cooldown_seconds:
            state.status = "half_open"
            self._states[capability_name] = state
            self._persist_state(capability_name)
            return True
        return False

    def mark_success(self, capability_name: str) -> None:
        """Reset state after successful call."""
        self._states[capability_name] = CircuitState()
        self._persist_state(capability_name)

    def mark_failure(self, capability_name: str) -> None:
        """Record failure and open breaker when threshold reached."""
        state = self._states.get(capability_name, CircuitState())
        if state.status == "half_open":
            state.status = "open"
            state.opened_at = self.clock()
            state.failures = self.failure_threshold
            self._states[capability_name] = state
            self._persist_state(capability_name)
            return
        if state.status == "open":
            state.opened_at = self.clock()
            self._states[capability_name] = state
            self._persist_state(capability_name)
            return

        state.failures += 1
        if state.failures >= self.failure_threshold:
            state.status = "open"
            state.opened_at = self.clock()
        self._states[capability_name] = state
        self._persist_state(capability_name)
