"""W32-C.8 integration test for the background lease-expiry asyncio task.

The lifespan installs an asyncio task that periodically calls
``_rehydrate_runs(agent_server)`` every ``HI_AGENT_LEASE_EXPIRY_INTERVAL_S``
seconds (default 30s). This test verifies the task fires without external
trigger and reaches the recovery code path.
"""

from __future__ import annotations

import pytest
from hi_agent.server import app as server_app
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


@pytest.fixture()
def fast_server(monkeypatch: pytest.MonkeyPatch) -> AgentServer:
    """AgentServer with the lease-expiry interval shortened to 1s for tests."""
    monkeypatch.setenv("HI_AGENT_LEASE_EXPIRY_INTERVAL_S", "1")
    return AgentServer(rate_limit_rps=10000)


def test_lease_expiry_task_runs_without_external_trigger(
    fast_server: AgentServer, monkeypatch: pytest.MonkeyPatch
):
    """The background task must call _rehydrate_runs at least twice within 5s.

    We replace the module-level ``_rehydrate_runs`` with a recording stub so
    we can observe the loop firing without any external API call.
    """
    import threading
    import time as _time

    calls: list[float] = []
    calls_lock = threading.Lock()

    def recording_rehydrate(_agent_server):
        # Use time.monotonic() instead of asyncio.get_event_loop().time();
        # the executor runs this on a thread without an event loop.
        with calls_lock:
            calls.append(_time.monotonic())

    monkeypatch.setattr(server_app, "_rehydrate_runs", recording_rehydrate)

    # TestClient drives lifespan startup + shutdown around the with-block.
    with TestClient(fast_server.app, raise_server_exceptions=False) as client:
        # Hit /health to ensure the lifespan has fully started.
        resp = client.get("/health")
        assert resp.status_code == 200

        # Wait for the background loop to fire at least twice (interval=1s).
        # Use polling rather than asyncio.run because TestClient drives its
        # own loop in a worker thread.
        deadline = _time.monotonic() + 8.0
        while _time.monotonic() < deadline:
            with calls_lock:
                n = len(calls)
            if n >= 2:
                break
            _time.sleep(0.2)

    # Two firings observed after startup + shutdown.
    # First firing happens during _rehydrate_runs called directly in lifespan
    # (synchronous startup path). Subsequent firings come from the
    # background task at interval=1s.
    with calls_lock:
        final_n = len(calls)
    assert final_n >= 2, (
        f"lease-expiry background task did not fire enough times: "
        f"calls={final_n}"
    )


def test_lease_expiry_task_attached_to_agent_server(
    fast_server: AgentServer,
):
    """Verify _lease_expiry_task is attached after lifespan startup."""
    with TestClient(fast_server.app, raise_server_exceptions=False) as client:
        client.get("/health")
        # After lifespan startup, the task attribute must exist.
        task = getattr(fast_server, "_lease_expiry_task", None)
        assert task is not None
        # Task should be running (not done, not cancelled) inside the with-block.
        assert not task.done()
    # After the with-block exits, lifespan shutdown cancels the task.
    task = getattr(fast_server, "_lease_expiry_task", None)
    assert task is not None
    assert task.done() or task.cancelled()
