"""No-progress detection watchdog for run execution."""

from collections import deque

from hi_agent.failures.taxonomy import FailureCode, FailureRecord


class ProgressWatchdog:
    """Detects no-progress conditions during run execution.

    Tracks action success rate over a sliding window.
    Triggers NO_PROGRESS failure when threshold exceeded.
    """

    def __init__(
        self,
        window_size: int = 10,
        min_success_rate: float = 0.2,
        max_consecutive_failures: int = 5,
    ) -> None:
        self._window_size = window_size
        self._min_success_rate = min_success_rate
        self._max_consecutive_failures = max_consecutive_failures
        self._window: deque[bool] = deque(maxlen=window_size)
        self._consecutive_failures: int = 0

    def record_action(self, success: bool) -> None:
        """Record the outcome of an action."""
        self._window.append(success)
        if success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

    def check(self) -> FailureRecord | None:
        """Returns NO_PROGRESS FailureRecord if watchdog triggered, else None."""
        # Check consecutive failures first
        if self._consecutive_failures >= self._max_consecutive_failures:
            return FailureRecord(
                failure_code=FailureCode.NO_PROGRESS,
                message=(
                    f"Consecutive failures ({self._consecutive_failures}) "
                    f"exceeded threshold ({self._max_consecutive_failures})"
                ),
                context={
                    "trigger": "consecutive_failures",
                    "consecutive_failures": self._consecutive_failures,
                    "threshold": self._max_consecutive_failures,
                },
            )

        # Check success rate over the window (only if window is full)
        if len(self._window) >= self._window_size:
            rate = self.success_rate
            if rate < self._min_success_rate:
                return FailureRecord(
                    failure_code=FailureCode.NO_PROGRESS,
                    message=(
                        f"Success rate ({rate:.2f}) below minimum "
                        f"({self._min_success_rate}) over last {self._window_size} actions"
                    ),
                    context={
                        "trigger": "low_success_rate",
                        "success_rate": rate,
                        "min_success_rate": self._min_success_rate,
                        "window_size": self._window_size,
                    },
                )

        return None

    @property
    def consecutive_failures(self) -> int:
        """Return the current count of consecutive failures."""
        return self._consecutive_failures

    @property
    def success_rate(self) -> float:
        """Return the success rate over the current window."""
        if not self._window:
            return 1.0
        return sum(1 for s in self._window if s) / len(self._window)

    def reset(self) -> None:
        """Reset the watchdog state."""
        self._window.clear()
        self._consecutive_failures = 0
