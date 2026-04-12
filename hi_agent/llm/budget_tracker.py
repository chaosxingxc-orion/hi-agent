"""LLM call and token budget tracker."""

from __future__ import annotations

import threading

from hi_agent.llm.errors import LLMBudgetExhaustedError
from hi_agent.llm.protocol import TokenUsage


class LLMBudgetTracker:
    """Tracks token and call usage against configurable budget limits.

    Args:
        max_calls: Maximum number of LLM calls allowed.
        max_tokens: Maximum total tokens (prompt + completion) allowed.
    """

    def __init__(self, max_calls: int = 100, max_tokens: int = 500_000) -> None:
        """Initialize LLMBudgetTracker."""
        self._max_calls = max_calls
        self._max_tokens = max_tokens
        self._total_calls = 0
        self._total_tokens = 0
        self._lock = threading.Lock()

    def record(self, usage: TokenUsage) -> None:
        """Record token consumption from one LLM call.

        Args:
            usage: The token usage returned by the gateway.
        """
        with self._lock:
            self._total_calls += 1
            self._total_tokens += usage.total_tokens

    def check(self) -> None:
        """Raise if budget is exhausted.

        Raises:
            LLMBudgetExhaustedError: If call or token budget is exceeded.
        """
        with self._lock:
            total_calls = self._total_calls
            total_tokens = self._total_tokens
        if total_calls >= self._max_calls:
            raise LLMBudgetExhaustedError(
                f"Call budget exhausted: {total_calls}/{self._max_calls}"
            )
        if total_tokens >= self._max_tokens:
            raise LLMBudgetExhaustedError(
                f"Token budget exhausted: {total_tokens}/{self._max_tokens}"
            )

    @property
    def total_calls(self) -> int:
        """Number of LLM calls recorded so far."""
        with self._lock:
            return self._total_calls

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed so far."""
        with self._lock:
            return self._total_tokens

    @property
    def remaining_calls(self) -> int:
        """Remaining call budget."""
        with self._lock:
            return max(0, self._max_calls - self._total_calls)
