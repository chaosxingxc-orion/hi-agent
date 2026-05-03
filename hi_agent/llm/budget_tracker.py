"""LLM call and token budget tracker.

W32 Track B Gap 7: the tracker now accepts an optional ``tenant_id`` on
``record`` and ``check`` and maintains per-tenant counters in addition to
the global aggregate. When ``tenant_id`` is omitted (back-compat caller),
the global counters are still updated so existing single-tenant /
process-shared-budget configurations continue to work. Per-tenant counters
expose a tenant-scoped budget when callers plumb ``tenant_id`` through
``LLMRequest.metadata``.
"""

from __future__ import annotations

import threading

from hi_agent.llm.errors import LLMBudgetExhaustedError
from hi_agent.llm.protocol import TokenUsage


class LLMBudgetTracker:
    """Tracks token and call usage against configurable budget limits.

    Args:
        max_calls: Maximum number of LLM calls allowed (per-tenant when
            tenant_id is supplied; global cap when not).
        max_tokens: Maximum total tokens (prompt + completion) allowed (per
            tenant when tenant_id is supplied; global cap when not).

    W32 Track B Gap 7: the tracker maintains a global aggregate counter
    AND per-tenant counters. Counters are addressed by ``tenant_id``;
    callers that omit tenant_id update only the global counter. Both
    layers obey ``max_calls`` / ``max_tokens``.
    """

    def __init__(self, max_calls: int = 100, max_tokens: int = 500_000) -> None:
        """Initialize LLMBudgetTracker."""
        self._max_calls = max_calls
        self._max_tokens = max_tokens
        self._total_calls = 0
        self._total_tokens = 0
        # W32 Track B Gap 7: per-tenant counters (additive; back-compat preserved).
        self._per_tenant_calls: dict[str, int] = {}
        self._per_tenant_tokens: dict[str, int] = {}
        self._lock = threading.Lock()

    def record(self, usage: TokenUsage, *, tenant_id: str | None = None) -> None:
        """Record token consumption from one LLM call.

        Args:
            usage: The token usage returned by the gateway.
            tenant_id: Tenant identifier for per-tenant attribution
                (W32 Track B Gap 7). When omitted, only the global counter is
                updated (back-compat).
        """
        with self._lock:
            self._total_calls += 1
            self._total_tokens += usage.total_tokens
            if tenant_id and tenant_id.strip():
                tid = tenant_id.strip()
                self._per_tenant_calls[tid] = self._per_tenant_calls.get(tid, 0) + 1
                self._per_tenant_tokens[tid] = (
                    self._per_tenant_tokens.get(tid, 0) + usage.total_tokens
                )

    def check(self, *, tenant_id: str | None = None) -> None:
        """Raise if budget is exhausted (global, plus per-tenant when supplied).

        Args:
            tenant_id: Tenant identifier. When supplied, the per-tenant
                budget is also checked alongside the global one. When
                omitted, only the global budget is checked.

        Raises:
            LLMBudgetExhaustedError: If the call or token budget is exceeded
                at either the global or the per-tenant scope.
        """
        with self._lock:
            total_calls = self._total_calls
            total_tokens = self._total_tokens
            tid = tenant_id.strip() if (tenant_id and tenant_id.strip()) else ""
            tenant_calls = self._per_tenant_calls.get(tid, 0) if tid else 0
            tenant_tokens = self._per_tenant_tokens.get(tid, 0) if tid else 0
        if total_calls >= self._max_calls:
            raise LLMBudgetExhaustedError(f"Call budget exhausted: {total_calls}/{self._max_calls}")
        if total_tokens >= self._max_tokens:
            raise LLMBudgetExhaustedError(
                f"Token budget exhausted: {total_tokens}/{self._max_tokens}"
            )
        if tid and tenant_calls >= self._max_calls:
            raise LLMBudgetExhaustedError(
                f"Call budget exhausted for tenant {tid!r}: "
                f"{tenant_calls}/{self._max_calls}"
            )
        if tid and tenant_tokens >= self._max_tokens:
            raise LLMBudgetExhaustedError(
                f"Token budget exhausted for tenant {tid!r}: "
                f"{tenant_tokens}/{self._max_tokens}"
            )

    @property
    def total_calls(self) -> int:
        """Number of LLM calls recorded so far (global aggregate)."""
        with self._lock:
            return self._total_calls

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed so far (global aggregate)."""
        with self._lock:
            return self._total_tokens

    @property
    def remaining_calls(self) -> int:
        """Remaining call budget (global aggregate)."""
        with self._lock:
            return max(0, self._max_calls - self._total_calls)

    def snapshot(self, *, tenant_id: str | None = None) -> dict:
        """Return a consistent snapshot of current and limit values.

        Args:
            tenant_id: When supplied, the snapshot reports the per-tenant
                counters. When omitted, the snapshot reports the global
                aggregate (back-compat).
        """
        with self._lock:
            if tenant_id and tenant_id.strip():
                tid = tenant_id.strip()
                t_calls = self._per_tenant_calls.get(tid, 0)
                t_tokens = self._per_tenant_tokens.get(tid, 0)
                return {
                    "max_calls": self._max_calls,
                    "max_tokens": self._max_tokens,
                    "total_calls": t_calls,
                    "total_tokens": t_tokens,
                    "remaining_calls": max(0, self._max_calls - t_calls),
                    "remaining_tokens": max(0, self._max_tokens - t_tokens),
                    "tenant_id": tid,
                }
            return {
                "max_calls": self._max_calls,
                "max_tokens": self._max_tokens,
                "total_calls": self._total_calls,
                "total_tokens": self._total_tokens,
                "remaining_calls": max(0, self._max_calls - self._total_calls),
                "remaining_tokens": max(0, self._max_tokens - self._total_tokens),
            }
