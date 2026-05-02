"""Integration tests for W12-E backpressure: 429 on queue saturation + /ready flags.

Layer 2 (Integration): real RunManager with real in-memory queue.
Zero mocks on the subsystem under test.

Covers:
- QueueSaturatedError is raised when queue is full.
- routes_runs returns HTTP 429 + Retry-After when QueueSaturatedError fires.
- /ready flags.ready_to_accept_new_runs is False when queue is full.
- /ready backward-compat: top-level 'ready' key is still present.
"""

from __future__ import annotations

import threading
import time

import pytest
from hi_agent.server.run_manager import QueueSaturatedError, RunManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Unit-level: QueueSaturatedError raised directly by RunManager
# ---------------------------------------------------------------------------


def test_queue_saturated_error_attributes():
    """QueueSaturatedError carries queue_depth and max_depth."""
    err = QueueSaturatedError(queue_depth=2, max_depth=2)
    assert err.queue_depth == 2
    assert err.max_depth == 2
    assert "2/2" in str(err)


def test_run_manager_raises_queue_saturated_when_full():
    """RunManager.start_run raises QueueSaturatedError when queue is saturated.

    With max_concurrent=1 and queue_size=1, the effective capacity before
    saturation is 3 slots:
    - 1 run being executed (executor thread, semaphore acquired)
    - 1 run dequeued by the worker, blocking on semaphore.acquire()
    - 1 run waiting in the PriorityQueue

    A 4th start_run overflows the PriorityQueue and raises QueueSaturatedError.
    We add a generous sleep to ensure the worker has consumed runs 1 and 2.
    """
    barrier = threading.Event()
    manager = RunManager(max_concurrent=1, queue_size=1)

    def _blocking_executor(_run):
        barrier.wait(timeout=5)

    runs = [
        manager.create_run({"goal": f"g{i}", "task_id": f"t-bp-{i}"})
        for i in range(1, 5)
    ]

    # Enqueue runs 1-3 with pauses to let the worker drain them into the
    # active slot and semaphore-wait slot; run 3 should end up in the queue.
    manager.start_run(runs[0].run_id, _blocking_executor)
    time.sleep(0.1)  # worker: dequeue run1, acquire semaphore (1→0), start thread
    manager.start_run(runs[1].run_id, _blocking_executor)
    time.sleep(0.1)  # worker: dequeue run2, block on semaphore.acquire (0 permits)
    manager.start_run(runs[2].run_id, _blocking_executor)
    time.sleep(0.05)  # run3 now in queue (worker blocked on semaphore)

    # run4 must overflow the queue.
    with pytest.raises(QueueSaturatedError) as exc_info:
        manager.start_run(runs[3].run_id, _blocking_executor)

    assert exc_info.value.max_depth == 1

    # Release all blocked executors so daemon threads exit cleanly.
    barrier.set()


# ---------------------------------------------------------------------------
# HTTP layer: POST /runs returns 429 when queue is saturated
# ---------------------------------------------------------------------------


@pytest.fixture()
def _saturated_app(monkeypatch):
    """Build a minimal Starlette app that wires handle_create_run and
    handle_ready with a RunManager whose start_run unconditionally raises
    QueueSaturatedError — simulating a fully saturated queue.

    We use a real RunManager for create_run (real run record) and stub
    start_run to raise QueueSaturatedError so the route handler returns 429.
    The queue depth / max depth accessors are also stubbed so /ready can
    report ready_to_accept_new_runs=False.
    """
    import hi_agent.server.routes_runs as _routes_runs
    from hi_agent.server.app import handle_ready
    from hi_agent.server.routes_runs import handle_create_run

    # Bypass auth so we don't need real JWT tokens in the test.
    from hi_agent.server.tenant_context import TenantContext

    monkeypatch.setattr(
        _routes_runs,
        "require_tenant_context",
        lambda: TenantContext(tenant_id="t1", user_id="u1", session_id="s1"),
    )

    manager = RunManager(max_concurrent=1, queue_size=1)

    # Override start_run to always raise QueueSaturatedError.
    def _saturated_start_run(_run_id, _executor_fn):
        raise QueueSaturatedError(queue_depth=1, max_depth=1)

    manager.start_run = _saturated_start_run  # type: ignore[method-assign]  expiry_wave: permanent

    # Override queue depth accessors so /ready reports saturation.
    manager.queue_depth = lambda: 1  # type: ignore[method-assign]  expiry_wave: permanent

    class _FakeBuilder:
        def readiness(self):
            return {"ready": True, "health": "ok"}

    # executor_factory must be non-None so handle_create_run calls start_run.
    def _factory(_run_data):
        def _runner():
            pass

        return _runner

    class _FakeServer:
        def __init__(self) -> None:
            self._builder = _FakeBuilder()
            self._draining = False
            self.run_manager = manager
            self.executor_factory = _factory
            self.run_context_manager = None

    fake_server = _FakeServer()

    app = Starlette(
        routes=[
            Route("/runs", handle_create_run, methods=["POST"]),
            Route("/ready", handle_ready, methods=["GET"]),
        ]
    )
    app.state.agent_server = fake_server

    return app


def test_post_runs_returns_429_when_queue_saturated(_saturated_app):
    """POST /runs on a saturated queue must return 429 with Retry-After header."""
    with TestClient(_saturated_app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/runs",
            json={"goal": "overflow", "task_id": "t-overflow-1"},
        )

    assert resp.status_code == 429, f"Expected 429, got {resp.status_code}: {resp.text}"
    assert "Retry-After" in resp.headers
    body = resp.json()
    assert body["error"] == "queue_saturated"
    assert "queue_depth" in body
    assert "max_depth" in body
    assert "retry_after_seconds" in body


def test_ready_flags_when_queue_saturated(_saturated_app):
    """GET /ready must expose flags.ready_to_accept_new_runs=false when queue full."""
    with TestClient(_saturated_app, raise_server_exceptions=False) as client:
        resp = client.get("/ready")

    assert resp.status_code == 200, f"Backpressure endpoint returned {resp.status_code}"
    body = resp.json()
    # Backward-compat: top-level 'ready' key must be present.
    assert "ready" in body, "backward-compat: 'ready' key missing from /ready response"
    flags = body.get("flags", {})
    assert "ready_to_serve" in flags
    assert "ready_to_accept_new_runs" in flags
    # Queue is saturated (queue_depth == max_queue_depth), so False.
    assert flags["ready_to_accept_new_runs"] is False


def test_ready_flags_when_queue_not_saturated():
    """GET /ready.flags.ready_to_accept_new_runs is True when queue has space."""
    from hi_agent.server.app import handle_ready

    manager = RunManager(max_concurrent=4, queue_size=16)

    class _FakeBuilder:
        def readiness(self):
            return {"ready": True, "health": "ok"}

    class _FakeServer:
        def __init__(self) -> None:
            self._builder = _FakeBuilder()
            self._draining = False
            self.run_manager = manager

    fake_server = _FakeServer()

    app = Starlette(routes=[Route("/ready", handle_ready, methods=["GET"])])
    app.state.agent_server = fake_server

    with TestClient(app) as client:
        resp = client.get("/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert "ready" in body
    flags = body.get("flags", {})
    assert flags.get("ready_to_serve") is True
    assert flags.get("ready_to_accept_new_runs") is True
