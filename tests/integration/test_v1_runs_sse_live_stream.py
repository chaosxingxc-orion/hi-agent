"""W33-C.5: ``GET /v1/runs/{id}/events`` must be a LIVE TAIL, not a snapshot.

Before this fix, ``RealKernelBackend.iter_events`` called
``event_store.list_since(0)`` once at connection time, returned that
list, and the route's generator iterated through it and exited. A
client who connected before the run finished would see only the events
already persisted at connect time and the connection would close.

The fix turns ``iter_events`` into a polling generator that yields new
events as they appear and exits only when the run reaches a terminal
state. This test verifies:

* Events that arrive AFTER the SSE connection opens are delivered.
* Multiple late events arriving in sequence are delivered separately
  (not coalesced by a stale snapshot read).
* The stream closes cleanly when the run terminates.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

_TERMINAL_STATES = frozenset(
    {"completed", "failed", "cancelled", "aborted", "queue_timeout"}
)


@pytest.fixture()
def real_app(tmp_path, monkeypatch):
    """Boot the production app with a held executor factory.

    The held executor blocks on an event the test owns so the run stays
    in a non-terminal state long enough to inject late events into the
    durable event store.
    """
    monkeypatch.setenv("AGENT_SERVER_BACKEND", "real")
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.setenv("AGENT_SERVER_STATE_DIR", str(tmp_path / "state"))

    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path / "state")

    release = threading.Event()

    class _HeldFactory:
        def __init__(self) -> None:
            self.invoked = threading.Event()

        def __call__(self, run_data: dict[str, Any]):
            def _run():
                self.invoked.set()
                # Block until the test releases us — keeps the run in a
                # non-terminal state long enough to test live streaming.
                release.wait(timeout=10.0)
                return None

            return _run

    factory = _HeldFactory()
    backend = app.state.run_backend
    assert backend.__class__.__name__ == "RealKernelBackend", backend
    backend.agent_server.executor_factory = factory
    try:
        yield app, factory, release, backend
    finally:
        # Allow the executor to finish so RunManager teardown is clean.
        release.set()
        backend.aclose()


def test_iter_events_yields_late_events_live(real_app) -> None:
    """Events appended AFTER iter_events starts must still be delivered."""
    app, factory, release, backend = real_app

    from fastapi.testclient import TestClient

    # r-as-1-seam: StoredEvent is the durable event-store contract
    from hi_agent.server.event_store import StoredEvent

    with TestClient(app) as client:
        body = {
            "profile_id": "default",
            "goal": "sse-live-1",
            "idempotency_key": "sse-live-1-key",
        }
        headers = {"X-Tenant-Id": "tenant-sse-1", "Idempotency-Key": "sse-live-1-key"}
        created = client.post("/v1/runs", json=body, headers=headers)
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]

        # Wait for the executor to be invoked so we know the run is in
        # the running state and any RunManager-emitted events have
        # already been persisted.
        assert factory.invoked.wait(timeout=5.0), "executor was never invoked"

        # Drive iter_events directly so we can interleave appends without
        # buffering through the SSE response chunking.
        events_iter = backend.iter_events(
            tenant_id="tenant-sse-1", run_id=run_id
        )

        received: list[dict[str, Any]] = []

        def _consume() -> None:
            for ev in events_iter:
                received.append(ev)

        consumer_thread = threading.Thread(target=_consume, daemon=True)
        consumer_thread.start()

        # Give the consumer a beat to settle on its initial poll. Any
        # events already persisted (run_queued / run_started) flow now.
        time.sleep(0.3)
        baseline = len(received)

        # Inject two late events 500 ms apart and assert each is
        # delivered separately, not coalesced.
        agent_server = backend.agent_server
        event_store = agent_server._event_store
        assert event_store is not None, "event store missing"

        def _next_seq() -> int:
            existing = event_store.list_since(
                run_id, since_sequence=-1, tenant_id="tenant-sse-1"
            )
            return (max((e.sequence for e in existing), default=-1)) + 1

        # First late event.
        seq1 = _next_seq()
        event_store.append(
            StoredEvent(
                event_id=f"late-1-{run_id}",
                run_id=run_id,
                sequence=seq1,
                event_type="late_marker_1",
                payload_json=json.dumps({"marker": 1}),
                tenant_id="tenant-sse-1",
            )
        )
        # Wait for live tail to deliver event 1.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if any(e.get("event_type") == "late_marker_1" for e in received):
                break
            time.sleep(0.05)
        else:
            pytest.fail(
                f"late_marker_1 never delivered to live tail; "
                f"received={[e.get('event_type') for e in received]}"
            )

        time.sleep(0.5)

        # Second late event.
        seq2 = _next_seq()
        event_store.append(
            StoredEvent(
                event_id=f"late-2-{run_id}",
                run_id=run_id,
                sequence=seq2,
                event_type="late_marker_2",
                payload_json=json.dumps({"marker": 2}),
                tenant_id="tenant-sse-1",
            )
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if any(e.get("event_type") == "late_marker_2" for e in received):
                break
            time.sleep(0.05)
        else:
            pytest.fail(
                f"late_marker_2 never delivered to live tail; "
                f"received={[e.get('event_type') for e in received]}"
            )

        # Now release the run so it terminates. The generator must exit
        # within the polling interval after the terminal state is seen.
        release.set()
        consumer_thread.join(timeout=10.0)
        assert not consumer_thread.is_alive(), (
            "live tail must close after the run reaches a terminal state"
        )

        types = [e.get("event_type") for e in received]
        # Late markers came in order, in separate poll passes.
        assert "late_marker_1" in types, types
        assert "late_marker_2" in types, types
        idx1 = types.index("late_marker_1")
        idx2 = types.index("late_marker_2")
        assert idx1 < idx2, f"events out of order: {types!r}"
        # The number of received events strictly exceeds the snapshot
        # count, demonstrating live tailing.
        assert len(received) > baseline, (
            f"live tail did not deliver any new events; baseline={baseline}, "
            f"received={types!r}"
        )


def test_iter_events_terminates_when_run_reaches_terminal_state(real_app) -> None:
    """The live-tail generator must exit when the run is terminal.

    Without this, a successfully completed run would keep the generator
    polling forever and the SSE connection would never close.
    """
    app, _factory, release, backend = real_app

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        body = {
            "profile_id": "default",
            "goal": "sse-live-2",
            "idempotency_key": "sse-live-2-key",
        }
        headers = {"X-Tenant-Id": "tenant-sse-2", "Idempotency-Key": "sse-live-2-key"}
        created = client.post("/v1/runs", json=body, headers=headers)
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        # Release immediately so the run terminates fast.
        release.set()

        # Poll the run until terminal so we know the generator's exit
        # condition will fire on the next polling pass.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            resp = client.get(
                f"/v1/runs/{run_id}", headers={"X-Tenant-Id": "tenant-sse-2"}
            )
            assert resp.status_code == 200, resp.text
            if resp.json().get("state") in _TERMINAL_STATES:
                break
            time.sleep(0.05)
        else:
            pytest.fail("run did not reach terminal state in time")

        # Now consume the generator — must terminate cleanly.
        events_iter = backend.iter_events(
            tenant_id="tenant-sse-2", run_id=run_id
        )
        start = time.monotonic()
        consumed = list(events_iter)
        elapsed = time.monotonic() - start
        # Should complete in < 1 s once the run is already terminal.
        assert elapsed < 5.0, (
            f"live tail did not exit promptly after terminal state; "
            f"elapsed={elapsed:.2f}s"
        )
        assert consumed, "expected at least one persisted event"
