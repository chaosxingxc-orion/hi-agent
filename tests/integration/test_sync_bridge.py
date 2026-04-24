"""Tests for :mod:`hi_agent.runtime.sync_bridge`.

The second test (``test_shared_async_client_survives_100_calls``) is the
04-22 regression: proves that a single ``httpx.AsyncClient`` built on the
bridge loop survives 100 sequential ``call_sync`` invocations without
``RuntimeError: Event loop is closed``.  Before the durable bridge existed,
each sync-side LLM call created its own ``asyncio.run`` loop and the shared
``httpx.AsyncClient`` pool became invalid on the 2nd call.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time

import httpx
import pytest
from hi_agent.runtime.sync_bridge import (
    SyncBridge,
    SyncBridgeShutdownError,
    get_bridge,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fresh_bridge() -> SyncBridge:
    """Return an isolated SyncBridge for tests that mutate lifecycle state.

    The process-wide singleton from :func:`get_bridge` is shared with the
    rest of the suite, so tests that call :meth:`SyncBridge.shutdown` or
    assert on lazy-start use a private instance instead.
    """
    return SyncBridge()


# ---------------------------------------------------------------------------
# 1. basic happy path
# ---------------------------------------------------------------------------


def test_basic_call_sync_returns_result() -> None:
    bridge = get_bridge()
    result = bridge.call_sync(asyncio.sleep(0, result=42))
    assert result == 42


# ---------------------------------------------------------------------------
# 2. THE 04-22 REGRESSION TEST
# ---------------------------------------------------------------------------


def test_shared_async_client_survives_100_calls() -> None:
    """A single httpx.AsyncClient must survive 100 sync-facing calls.

    Historical defect: ``AsyncHttpLLMGateway.complete()`` called
    ``asyncio.run(self._inner.complete(...))`` every request.  The first
    call built ``httpx.AsyncClient`` on a loop that then closed; the 2nd
    call tried to reuse its connection pool under a fresh loop and failed
    with ``RuntimeError: Event loop is closed``.

    With :class:`SyncBridge`, every ``call_sync`` runs on the *same* loop,
    so the client's connection pool stays valid.
    """
    bridge = get_bridge()

    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"ok": True, "n": call_count})

    transport = httpx.MockTransport(_handler)

    async def _build_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, timeout=5.0)

    client = bridge.call_sync(_build_client())

    async def _get(c: httpx.AsyncClient, url: str) -> httpx.Response:
        return await c.get(url)

    try:
        for i in range(100):
            resp = bridge.call_sync(_get(client, "http://test.invalid/ok"))
            assert resp.status_code == 200, f"call {i} got {resp.status_code}"
            assert resp.json()["n"] == i + 1, f"call {i} count mismatch"
    finally:
        bridge.call_sync(client.aclose())

    assert call_count == 100


# ---------------------------------------------------------------------------
# 3. timeout propagates as concurrent.futures.TimeoutError
# ---------------------------------------------------------------------------


def test_timeout_propagates() -> None:
    bridge = get_bridge()
    with pytest.raises(concurrent.futures.TimeoutError):
        bridge.call_sync(asyncio.sleep(10), timeout=0.1)


# ---------------------------------------------------------------------------
# 4. shutdown-then-call raises SyncBridgeShutdownError
# ---------------------------------------------------------------------------


def test_shutdown_then_call_raises() -> None:
    bridge = _fresh_bridge()
    # run one call to ensure thread started
    assert bridge.call_sync(asyncio.sleep(0, result="ok")) == "ok"
    bridge.shutdown()
    # construct & close the coro so it isn't flagged as "never awaited"
    never_coro = asyncio.sleep(0, result="never")
    try:
        with pytest.raises(SyncBridgeShutdownError):
            bridge.call_sync(never_coro)
    finally:
        never_coro.close()


def test_shutdown_is_idempotent() -> None:
    bridge = _fresh_bridge()
    bridge.call_sync(asyncio.sleep(0, result=1))
    bridge.shutdown()
    # second call must not raise
    bridge.shutdown()


# ---------------------------------------------------------------------------
# 5. lazy start — no thread until first call_sync
# ---------------------------------------------------------------------------


def test_lazy_start() -> None:
    bridge = _fresh_bridge()
    assert bridge._thread is None
    assert bridge._started is False
    # first call spawns the thread
    bridge.call_sync(asyncio.sleep(0, result=1))
    assert bridge._thread is not None
    assert bridge._thread.is_alive()
    assert bridge._started is True
    bridge.shutdown()


# ---------------------------------------------------------------------------
# 6. many threads can call concurrently without corruption
# ---------------------------------------------------------------------------


def test_concurrent_calls_from_many_threads() -> None:
    bridge = get_bridge()
    results: dict[int, int] = {}
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    async def _work(value: int) -> int:
        # small async hop so the loop actually context-switches
        await asyncio.sleep(0.01)
        return value * 2

    def _caller(i: int) -> None:
        try:
            got = bridge.call_sync(_work(i))
            with results_lock:
                results[i] = got
        except BaseException as exc:
            with results_lock:
                errors.append(exc)

    threads = [threading.Thread(target=_caller, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), "worker thread hung"

    assert errors == [], f"concurrent call_sync surfaced errors: {errors}"
    assert results == {i: i * 2 for i in range(20)}


# ---------------------------------------------------------------------------
# bonus: exceptions inside the coroutine are re-raised verbatim
# ---------------------------------------------------------------------------


def test_exception_in_coroutine_propagates() -> None:
    bridge = get_bridge()

    async def _boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        bridge.call_sync(_boom())


# ---------------------------------------------------------------------------
# bonus: same loop is reused across calls — the whole point of the bridge
# ---------------------------------------------------------------------------


def test_same_loop_reused_across_calls() -> None:
    bridge = get_bridge()

    async def _loop_id() -> int:
        return id(asyncio.get_running_loop())

    seen = {bridge.call_sync(_loop_id()) for _ in range(5)}
    assert len(seen) == 1, f"expected single shared loop, saw {seen}"


# ---------------------------------------------------------------------------
# bonus: get_bridge returns the same singleton
# ---------------------------------------------------------------------------


def test_get_bridge_returns_singleton() -> None:
    assert get_bridge() is get_bridge()


# ---------------------------------------------------------------------------
# bonus: coroutine kicked off before shutdown that sleeps past shutdown
# is cancelled cleanly (no hang on thread.join)
# ---------------------------------------------------------------------------


def test_shutdown_cancels_pending_tasks_without_hanging() -> None:
    bridge = _fresh_bridge()

    async def _long_sleep() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise

    # schedule in background then shutdown quickly — thread.join must return
    loop_future = {}

    def _schedule() -> None:
        try:
            bridge.call_sync(_long_sleep(), timeout=5.0)
        except concurrent.futures.TimeoutError:
            loop_future["timed_out"] = True
        except concurrent.futures.CancelledError:
            # Expected: shutdown() cancels pending tasks, and
            # run_coroutine_threadsafe's future then reports cancelled.
            loop_future["cancelled"] = True

    t = threading.Thread(target=_schedule)
    t.start()
    # give it a moment to schedule the coroutine
    time.sleep(0.1)
    bridge.shutdown(timeout=5.0)
    t.join(timeout=5.0)
    assert not t.is_alive()
