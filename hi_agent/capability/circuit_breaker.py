"""Simple circuit breaker for capability calls."""

from __future__ import annotations

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


class CircuitBreaker:
    """Failure-count based circuit breaker."""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Initialize breaker state.

        Args:
          failure_threshold: Number of consecutive failures before opening.
          cooldown_seconds: Time to wait before allowing half-open probes.
          clock: Optional monotonic clock provider in seconds.
        """
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock or monotonic
        self._states: dict[str, CircuitState] = {}

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
            return True
        return False

    def mark_success(self, capability_name: str) -> None:
        """Reset state after successful call."""
        self._states[capability_name] = CircuitState()

    def mark_failure(self, capability_name: str) -> None:
        """Record failure and open breaker when threshold reached."""
        state = self._states.get(capability_name, CircuitState())
        if state.status == "half_open":
            state.status = "open"
            state.opened_at = self.clock()
            state.failures = self.failure_threshold
            self._states[capability_name] = state
            return
        if state.status == "open":
            state.opened_at = self.clock()
            self._states[capability_name] = state
            return

        state.failures += 1
        if state.failures >= self.failure_threshold:
            state.status = "open"
            state.opened_at = self.clock()
        self._states[capability_name] = state
