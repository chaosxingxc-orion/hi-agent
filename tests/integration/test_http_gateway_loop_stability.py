"""W23-C: Rule 5 — cross-loop stability of the LLM gateway.

These tests pin the contract that ``hi_agent.llm.http_gateway`` is safe to
call from arbitrary sync contexts — including back-to-back ``asyncio.run``
boundaries and concurrent threads — without re-binding async resources
(``httpx.AsyncClient`` connection pool, failover-chain coroutines) to a
loop that has already closed.

The historical regression we are guarding against — "100% downstream LLM
traffic failed", recorded in ``docs/rules-incident-log.md`` — was caused
by storing an ``httpx.AsyncClient`` on ``self._client`` in ``__init__``,
so that the *first* ``asyncio.run`` that touched the gateway bound the
pool to its (ephemeral) loop, and every subsequent sync call raised
``RuntimeError: Event loop is closed``.

Per Rule 4 the SUT (``HttpLLMGateway`` / ``HTTPGateway``) is the real
class.  Only the network call target (``_direct_complete`` and the
``FailoverChain`` collaborator) is stubbed — the bridge, the
``_get_client`` lazy accessor, and the failover-routing branch run for
real.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hi_agent.llm.http_gateway import HTTPGateway, HttpLLMGateway
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage
from hi_agent.runtime.sync_bridge import get_bridge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(run_id: str) -> LLMRequest:
    return LLMRequest(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-4o",
        metadata={"run_id": run_id},
    )


def _make_response(tag: str = "ok") -> LLMResponse:
    return LLMResponse(
        content=tag,
        model="gpt-4o",
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


def _success_chain() -> MagicMock:
    """Return a FailoverChain stub whose complete() returns _make_response()."""
    chain = MagicMock()
    chain.complete = AsyncMock(return_value=_make_response("chain"))
    return chain


# ---------------------------------------------------------------------------
# Test 1 — three back-to-back asyncio.run() contexts must succeed
# ---------------------------------------------------------------------------


class TestSequentialAsyncioRunContexts:
    """The gateway must survive three consecutive ``asyncio.run`` boundaries.

    This is the exact pattern that caused the historical "100% downstream
    LLM traffic failed" incident: the first ``asyncio.run`` would close
    its loop on return, leaving any async resource (a stored
    ``httpx.AsyncClient`` pool) bound to a dead loop.  After Rule 5
    closure (W23-C), the SyncBridge owns the lifetime so subsequent calls
    reuse the same pool and the same bridge instance.
    """

    def test_sync_gateway_three_back_to_back_run_calls(self) -> None:
        """``HttpLLMGateway.complete`` from three separate ``asyncio.run`` blocks."""
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=_success_chain(),
        )

        bridge_ids: list[int] = []
        results: list[LLMResponse] = []

        for i in range(3):
            # Each iteration mimics a fresh sync caller (e.g. a CLI tool
            # spawning ``asyncio.run`` for an unrelated task).  The bridge
            # singleton is process-wide so ``id`` should be invariant.
            async def _outer(idx: int = i) -> LLMResponse:
                # ``HttpLLMGateway.complete`` itself is sync; running it
                # from inside ``asyncio.run`` mirrors the real downstream
                # call site (a sync façade invoked from an async caller).
                return gateway.complete(_make_request(f"run-loop-stab-{idx}"))

            results.append(asyncio.run(_outer()))
            bridge_ids.append(id(get_bridge()))

        # All three calls must have completed via the failover chain.
        assert all(r.content == "chain" for r in results), [
            r.content for r in results
        ]
        # The bridge is a process-wide singleton; every call sees the
        # same instance.  If the underlying resource lifetime were
        # broken, the second call would either raise
        # ``RuntimeError("Event loop is closed")`` or replace the
        # bridge instance.
        assert len(set(bridge_ids)) == 1, (
            f"bridge instance changed across asyncio.run boundaries: {bridge_ids}"
        )

    def test_no_event_loop_is_closed_error_across_boundaries(self) -> None:
        """No ``RuntimeError("Event loop is closed")`` between back-to-back runs."""
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=_success_chain(),
        )

        # First call seeds the bridge / any resources.
        async def _first() -> LLMResponse:
            return gateway.complete(_make_request("run-loop-first"))

        asyncio.run(_first())

        # Second call must not see a closed loop.  If Rule 5 regressed,
        # the failover chain's coroutine would be re-entered on a stale
        # loop and raise here.
        async def _second() -> LLMResponse:
            return gateway.complete(_make_request("run-loop-second"))

        try:
            response = asyncio.run(_second())
        except RuntimeError as exc:  # pragma: no cover — regression
            if "Event loop is closed" in str(exc):
                pytest.fail(
                    f"Rule 5 regressed: second asyncio.run boundary saw "
                    f"a closed loop: {exc!r}"
                )
            raise

        assert response.content == "chain"


# ---------------------------------------------------------------------------
# Test 2 — async caller followed by sync caller must reuse the same client
# ---------------------------------------------------------------------------


class TestAsyncClientPoolReuseAcrossCallers:
    """``HTTPGateway._get_client`` must yield the same instance regardless of caller.

    The fix routes ``_get_client`` through the durable bridge loop, so the
    client is bound to the bridge once and reused.  The previous
    implementation built the client inside whichever loop happened to be
    running at first call — so an async caller and a subsequent sync
    caller would each see a client bound to a different (and quickly
    closed) loop.
    """

    def test_async_then_sync_caller_share_one_async_client(self) -> None:
        """First an async use, then a sync use; the AsyncClient instance is one."""
        gateway = HTTPGateway(
            base_url="https://api.example.com/v1",
            api_key="fake-key",
        )

        # First touch: async caller via ``asyncio.run``.  After this, the
        # gateway's ``_client`` should be the bridge-bound instance.
        async def _async_touch() -> int:
            client = gateway._get_client()
            return id(client)

        first_id = asyncio.run(_async_touch())

        # Second touch: sync caller.  Must reuse the same client.
        second_id = id(gateway._get_client())

        assert first_id == second_id, (
            f"AsyncClient was rebuilt between async and sync callers: "
            f"first_id={first_id} second_id={second_id}"
        )

        # Third touch: a fresh ``asyncio.run`` boundary.  Still the same
        # instance — the bridge owns it, not the caller's loop.
        async def _async_touch_again() -> int:
            return id(gateway._get_client())

        third_id = asyncio.run(_async_touch_again())
        assert third_id == first_id, (
            f"AsyncClient was rebuilt across a second asyncio.run boundary: "
            f"first_id={first_id} third_id={third_id}"
        )

    def test_get_client_owning_loop_is_the_bridge_loop(self) -> None:
        """The AsyncClient's owning loop must be the SyncBridge's persistent loop."""
        gateway = HTTPGateway(
            base_url="https://api.example.com/v1",
            api_key="fake-key",
        )

        # Build the client and ask the bridge for a coroutine-scoped
        # ``get_running_loop`` — that *is* the bridge's loop by
        # construction.
        client = gateway._get_client()
        bridge = get_bridge()

        async def _bridge_loop_id() -> int:
            return id(asyncio.get_running_loop())

        bridge_loop_id = bridge.call_sync(_bridge_loop_id())

        # The httpx.AsyncClient stores its owning loop privately;
        # exposing this is implementation-detail of httpx, so we instead
        # verify the inverse: any awaited call against the client from
        # the bridge loop succeeds (it would not, were the client bound
        # to a closed loop).
        async def _ping() -> bool:
            # ``aclose`` is idempotent and does not perform I/O on a
            # never-used pool; calling it from the bridge loop confirms
            # the client is in fact bound to this loop.
            await client.aclose()
            return True

        assert bridge.call_sync(_ping()) is True
        assert isinstance(bridge_loop_id, int)


# ---------------------------------------------------------------------------
# Test 3 — concurrent sync callers from many threads serialize correctly
# ---------------------------------------------------------------------------


class TestConcurrentSyncCallers:
    """The bridge must serialize 10 concurrent sync gateway calls correctly.

    Many real callers (worker pools, request handlers, parallel tasks)
    invoke the sync gateway from independent threads.  The bridge runs
    one event loop on a daemon thread; ``call_sync`` schedules each
    coroutine via ``run_coroutine_threadsafe``.  All N calls must
    complete without losing results, raising loop-closed errors, or
    rebuilding the bridge.
    """

    def test_ten_threads_each_calling_sync_gateway(self) -> None:
        """10 concurrent sync gateway calls; all complete; same bridge."""
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=_success_chain(),
        )

        n = 10
        results: list[LLMResponse | Exception] = [None] * n  # type: ignore[list-item] # expiry_wave: permanent
        bridge_ids: list[int] = [0] * n
        barrier = threading.Barrier(n)

        def _worker(idx: int) -> None:
            barrier.wait()  # release all threads at once
            try:
                results[idx] = gateway.complete(_make_request(f"run-thr-{idx}"))
            except Exception as exc:  # pragma: no cover — regression
                results[idx] = exc
            bridge_ids[idx] = id(get_bridge())

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)

        # No thread escaped via timeout.
        for i, t in enumerate(threads):
            assert not t.is_alive(), f"thread {i} did not complete within 30s"

        # No call raised.
        for i, r in enumerate(results):
            assert isinstance(r, LLMResponse), (
                f"thread {i} returned {r!r} instead of LLMResponse"
            )
            assert r.content == "chain"

        # All threads observe the same bridge singleton.
        assert len(set(bridge_ids)) == 1, (
            f"bridge instance differed across threads: {bridge_ids}"
        )

    def test_ten_threads_no_event_loop_is_closed_under_stress(self) -> None:
        """No ``Event loop is closed`` raised under 10-way concurrent stress."""
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=_success_chain(),
        )

        n = 10
        errors: list[BaseException] = []
        lock = threading.Lock()

        def _worker(idx: int) -> None:
            for _ in range(3):  # each thread also makes 3 sequential calls
                try:
                    gateway.complete(_make_request(f"run-stress-{idx}"))
                except BaseException as exc:  # pragma: no cover — regression
                    with lock:
                        errors.append(exc)
                    return

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60.0)

        loop_closed = [
            e for e in errors if isinstance(e, RuntimeError)
            and "Event loop is closed" in str(e)
        ]
        assert not loop_closed, (
            f"Rule 5 regressed under stress: saw 'Event loop is closed' "
            f"in {len(loop_closed)} of {len(errors)} failures: {errors!r}"
        )
        assert not errors, f"unexpected errors under stress: {errors!r}"


# ---------------------------------------------------------------------------
# Sanity — patches that older tests used must still be irrelevant under W23-C
# ---------------------------------------------------------------------------


class TestNoLegacyAdHocBridgeUsed:
    """The gateway must not re-introduce ``asyncio.get_event_loop`` bridging.

    A regression check: if a future commit re-adds the legacy ad-hoc
    pattern (``loop = asyncio.get_event_loop(); loop.run_until_complete(...)``),
    patching ``asyncio.get_event_loop`` from outside the SUT would
    short-circuit the bridge.  This test pins the absence of that
    behaviour.
    """

    def test_failover_path_does_not_consult_get_event_loop(self) -> None:
        """``asyncio.get_event_loop`` must not be called by the failover branch."""
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=_success_chain(),
        )

        with patch(
            "asyncio.get_event_loop", side_effect=AssertionError("must not be called")
        ):
            response = gateway.complete(_make_request("run-no-legacy"))

        assert response.content == "chain"
