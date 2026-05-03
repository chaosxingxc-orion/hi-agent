"""Unit tests for CredentialPool round-robin rotation.

Track D C-2 (Wave 32 audit BLOCKER): the previous ``next_eligible``
implementation always returned the first eligible credential, pinning
every retry to the head of the pool and producing a thundering herd
against one provider key. The fix introduces an atomic round-robin
counter so successive calls rotate through the pool.

Layer 1 — Unit: tests touch only ``CredentialPool`` and ``RetryPolicy``;
no network, no asyncio, no LLM gateway construction.
"""
from __future__ import annotations

import pytest
from hi_agent.llm.failover import CredentialEntry, CredentialPool, RetryPolicy

pytestmark = [pytest.mark.unit]


def _make_pool(*keys: str, provider: str = "p") -> CredentialPool:
    return CredentialPool([CredentialEntry(api_key=k, provider=provider) for k in keys])


class TestRoundRobinRotation:
    """The pool rotates through every healthy entry on successive calls."""

    def test_four_calls_rotate_through_three_keys(self):
        # 4 successive calls on a 3-entry pool must visit each key at
        # least once. Track D C-2: previously they all returned key-0.
        pool = _make_pool("k0", "k1", "k2")
        seen: list[str] = []
        for _ in range(4):
            entry = pool.next_eligible()
            assert entry is not None
            seen.append(entry.api_key)
        # Every key appeared at least once across the 4 calls.
        assert set(seen) == {"k0", "k1", "k2"}, seen

    def test_two_calls_with_two_keys_yield_distinct_keys(self):
        pool = _make_pool("k0", "k1")
        first = pool.next_eligible()
        second = pool.next_eligible()
        assert first is not None and second is not None
        assert first.api_key != second.api_key

    def test_single_entry_pool_returns_same_entry(self):
        # Edge case: 1-entry pool can only return the one key.
        pool = _make_pool("only")
        for _ in range(5):
            entry = pool.next_eligible()
            assert entry is not None
            assert entry.api_key == "only"

    def test_skips_cooling_down_entries(self):
        # If the next-up entry is in cooldown, we advance to the next
        # eligible one without pinning to it forever.
        pool = _make_pool("k0", "k1", "k2")
        pool.mark_failed("k1", cooldown_seconds=300.0)
        seen: list[str] = []
        for _ in range(6):
            entry = pool.next_eligible()
            assert entry is not None
            seen.append(entry.api_key)
        # k1 must NOT appear; both k0 and k2 must appear.
        assert "k1" not in seen
        assert "k0" in seen
        assert "k2" in seen

    def test_returns_none_when_all_cooling_down(self):
        pool = _make_pool("k0", "k1")
        pool.mark_failed("k0", cooldown_seconds=300.0)
        pool.mark_failed("k1", cooldown_seconds=300.0)
        assert pool.next_eligible() is None

    def test_concurrent_calls_do_not_pin_to_head(self):
        # Smoke: concurrent threads each get a turn around the pool.
        # Strict round-robin under concurrency is not guaranteed by the
        # interleave but each key should be observed at least once.
        import threading

        pool = _make_pool("k0", "k1", "k2", "k3")
        seen: list[str] = []
        seen_lock = threading.Lock()

        def _worker():
            for _ in range(8):
                entry = pool.next_eligible()
                assert entry is not None
                with seen_lock:
                    seen.append(entry.api_key)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every key should appear at least once; no thundering-herd pin.
        assert set(seen) == {"k0", "k1", "k2", "k3"}, seen


class TestRetryPolicyMultiplicativeJitter:
    """RetryPolicy.delay_for emits multiplicative jitter in [0.5x, 1.5x)."""

    def test_jitter_yields_distinct_delays_across_calls(self):
        policy = RetryPolicy(max_retries=3, base_delay_ms=1000, max_delay_ms=30_000, jitter=True)
        # Sample many times; with multiplicative jitter spanning 1x the
        # base delay we should get a wide spread, not a constant value.
        samples = {round(policy.delay_for(0), 4) for _ in range(50)}
        assert len(samples) > 5, f"expected jitter spread, got {samples}"

    def test_jitter_stays_within_half_to_one_and_half_window(self):
        policy = RetryPolicy(max_retries=3, base_delay_ms=1000, max_delay_ms=30_000, jitter=True)
        for _ in range(200):
            d = policy.delay_for(0)
            # base_delay 1000 ms x [0.5, 1.5) = [0.5s, 1.5s).
            assert 0.5 <= d < 1.5, f"delay {d} outside multiplicative window"

    def test_jitter_disabled_yields_deterministic_delay(self):
        policy = RetryPolicy(max_retries=3, base_delay_ms=1000, max_delay_ms=30_000, jitter=False)
        d0 = policy.delay_for(0)
        d1 = policy.delay_for(0)
        assert d0 == d1 == 1.0
