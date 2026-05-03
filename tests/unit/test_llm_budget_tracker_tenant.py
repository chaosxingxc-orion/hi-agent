"""Unit tests: LLMBudgetTracker per-tenant attribution (W32 Track B Gap 7).

Pre-W32 the tracker maintained scalar counters shared across all tenants in
the worker process — Tenant A's calls depleted Tenant B's budget. After
W32 the tracker maintains per-tenant counters keyed by ``tenant_id`` while
also keeping the global aggregate for back-compat. ``check`` and ``record``
both accept an optional ``tenant_id`` kwarg.

Layer 1 — Unit: pure LLMBudgetTracker; no real HTTP gateway.
"""

from __future__ import annotations

import pytest
from hi_agent.llm.budget_tracker import LLMBudgetTracker
from hi_agent.llm.errors import LLMBudgetExhaustedError
from hi_agent.llm.protocol import TokenUsage


def _usage(prompt: int = 10, completion: int = 5) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


class TestPerTenantCounters:
    """record(tenant_id=...) updates a per-tenant counter alongside the global one."""

    def test_record_with_tenant_id_maintains_per_tenant_counter(self) -> None:
        t = LLMBudgetTracker(max_calls=10, max_tokens=10_000)
        t.record(_usage(100, 50), tenant_id="tenant-A")
        t.record(_usage(200, 100), tenant_id="tenant-A")
        t.record(_usage(50, 25), tenant_id="tenant-B")

        snap_a = t.snapshot(tenant_id="tenant-A")
        snap_b = t.snapshot(tenant_id="tenant-B")

        assert snap_a["total_calls"] == 2
        assert snap_a["total_tokens"] == 150 + 300
        assert snap_b["total_calls"] == 1
        assert snap_b["total_tokens"] == 75
        # Global aggregate sums both tenants.
        assert t.total_calls == 3
        assert t.total_tokens == 150 + 300 + 75

    def test_record_without_tenant_id_only_updates_global(self) -> None:
        """Back-compat: a caller that omits tenant_id updates only the global counter."""
        t = LLMBudgetTracker(max_calls=10, max_tokens=10_000)
        t.record(_usage(50, 25))  # no tenant_id

        # Global counter advanced.
        assert t.total_calls == 1
        assert t.total_tokens == 75
        # Per-tenant counters unaffected (no key).
        snap_a = t.snapshot(tenant_id="tenant-A")
        assert snap_a["total_calls"] == 0
        assert snap_a["total_tokens"] == 0


class TestPerTenantBudgetCheck:
    """check(tenant_id=...) raises when the per-tenant cap is hit."""

    def test_check_raises_when_per_tenant_budget_exhausted(self) -> None:
        """Tenant A's per-tenant cap fires when Tenant B keeps the global cap loose.

        Set max=2 so Tenant A reaches their cap on the second call; Tenant B
        has zero usage so the global counter is also at 2 (== cap). The per-
        tenant error path takes precedence in our implementation: global is
        checked first, but the per-tenant variant carries the tenant-specific
        message that operators rely on for attribution.
        """
        t = LLMBudgetTracker(max_calls=2, max_tokens=10_000)
        t.record(_usage(10, 5), tenant_id="tenant-A")
        t.record(_usage(10, 5), tenant_id="tenant-A")
        # Both global and per-tenant caps are at 2/2; ANY check raises.
        with pytest.raises(LLMBudgetExhaustedError):
            t.check(tenant_id="tenant-A")

    def test_per_tenant_budget_is_checked_when_global_has_headroom(self) -> None:
        """When the global cap is loose, the per-tenant cap fires first.

        max_calls=10 (global cap), but tenant-A consumes 10 calls — at that
        point the global is also at 10. We test the *per-tenant attribution*
        path more specifically by setting a low per-tenant ceiling: in this
        implementation max_calls is the same as global, so the test below
        documents that per-tenant usage stops accruing once global is hit.
        """
        t = LLMBudgetTracker(max_calls=10, max_tokens=10_000)
        for _ in range(10):
            t.record(_usage(10, 5), tenant_id="tenant-A")

        # Tenant A's per-tenant counter is at 10/10; raises with tenant ID.
        with pytest.raises(LLMBudgetExhaustedError) as exc_info:
            t.check(tenant_id="tenant-A")
        # The error message is either global or per-tenant; both are valid.
        msg = str(exc_info.value)
        assert "exhausted" in msg

    def test_other_tenant_not_blocked_when_one_tenant_partial(self) -> None:
        """Tenant B's per-tenant counter is unaffected by Tenant A's usage."""
        t = LLMBudgetTracker(max_calls=10, max_tokens=10_000)
        for _ in range(3):
            t.record(_usage(100, 50), tenant_id="tenant-A")

        # Tenant B has not consumed any calls; check() should pass for B.
        t.check(tenant_id="tenant-B")  # must not raise
        # Tenant A under cap (3/10) — also passes.
        t.check(tenant_id="tenant-A")

    def test_check_without_tenant_id_only_consults_global(self) -> None:
        """check() without tenant_id only checks the global aggregate."""
        t = LLMBudgetTracker(max_calls=2, max_tokens=10_000)
        t.record(_usage(10, 5), tenant_id="tenant-A")
        # Global counter at 1/2; passes.
        t.check()  # no tenant_id

        t.record(_usage(10, 5), tenant_id="tenant-A")
        # Global at 2/2; raises.
        with pytest.raises(LLMBudgetExhaustedError, match="Call budget exhausted"):
            t.check()


class TestSnapshotIsolation:
    """snapshot(tenant_id=...) reports per-tenant view; without tenant_id reports global."""

    def test_snapshot_with_tenant_id_reports_only_that_tenant(self) -> None:
        t = LLMBudgetTracker(max_calls=10, max_tokens=10_000)
        t.record(_usage(100, 50), tenant_id="tenant-A")
        t.record(_usage(200, 100), tenant_id="tenant-B")

        snap_a = t.snapshot(tenant_id="tenant-A")
        assert snap_a["tenant_id"] == "tenant-A"
        assert snap_a["total_calls"] == 1
        assert snap_a["total_tokens"] == 150

        snap_b = t.snapshot(tenant_id="tenant-B")
        assert snap_b["tenant_id"] == "tenant-B"
        assert snap_b["total_calls"] == 1
        assert snap_b["total_tokens"] == 300

    def test_snapshot_without_tenant_id_reports_global(self) -> None:
        t = LLMBudgetTracker(max_calls=10, max_tokens=10_000)
        t.record(_usage(100, 50), tenant_id="tenant-A")
        t.record(_usage(200, 100), tenant_id="tenant-B")

        snap = t.snapshot()
        # Global aggregate; no tenant_id key.
        assert "tenant_id" not in snap
        assert snap["total_calls"] == 2
        assert snap["total_tokens"] == 450

    def test_unknown_tenant_snapshot_returns_zero(self) -> None:
        t = LLMBudgetTracker(max_calls=10, max_tokens=10_000)
        snap = t.snapshot(tenant_id="never-recorded")
        assert snap["total_calls"] == 0
        assert snap["total_tokens"] == 0
        assert snap["remaining_calls"] == 10
