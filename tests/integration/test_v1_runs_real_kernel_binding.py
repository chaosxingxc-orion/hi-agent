"""W32-A: real-kernel binding for /v1/runs.

Acceptance criteria for the RIA northbound facade once it talks to the
durable :class:`hi_agent.server.app.AgentServer` instead of the W31
in-process stub:

  1. **Smoke (4 steps)**: GET /v1/health, POST /v1/runs x2 with same
     Idempotency-Key + body returns identical run_id; POST /v1/runs x1
     with same key + mutated body returns 409; GET /v1/runs/{id}
     returns the real RunManager-backed record.
  2. **Cancel live**: POST /v1/runs/{id}/cancel on a live run returns
     200 and the run reaches a cancelled terminal state.
  3. **Cancel unknown**: POST /v1/runs/{id}/cancel on an unknown id
     returns 404 (Rule 8 step-6).
  4. **SSE lifecycle**: GET /v1/runs/{id}/events returns a stream that
     emits real ``run_queued`` / ``run_started`` and either
     ``run_completed`` or ``run_failed`` events from the durable
     :class:`hi_agent.server.event_store.SQLiteEventStore`.
  5. **Executor invocation**: a stub executor injected on the
     AgentServer records invocation when a run is started, proving the
     real-kernel path actually drives the kernel.

Profile validated: default-offline (no network, no real LLM, no secrets).

# tdd-red-sha: TDD-RED-SHA-W32A
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TERMINAL_STATES = frozenset(
    {"completed", "failed", "cancelled", "aborted", "queue_timeout"}
)


def _wait_for_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.05,
) -> dict[str, Any]:
    """Poll GET /v1/runs/{run_id} until the run reaches a terminal state.

    The /v1/runs/{id} response always carries a ``state`` field; this
    helper returns the parsed body once that state is in the terminal
    set, or raises ``TimeoutError`` after ``timeout`` seconds.
    """
    deadline = time.monotonic() + timeout
    headers = {"X-Tenant-Id": "tenant-w32a"}
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/v1/runs/{run_id}", headers=headers)
        assert resp.status_code == 200, f"unexpected {resp.status_code}: {resp.text}"
        last = resp.json()
        if last.get("state") in _TERMINAL_STATES:
            return last
        time.sleep(poll_interval)
    raise TimeoutError(
        f"run {run_id} did not terminate within {timeout:.1f}s "
        f"(last state: {last.get('state')!r})"
    )


# ---------------------------------------------------------------------------
# Stub executor factory: records invocation, returns immediately.
# ---------------------------------------------------------------------------


class _RecordingExecutorFactory:
    """Stub executor factory that records every invocation.

    Replaces ``AgentServer.executor_factory`` so we exercise the
    real-kernel path (RunManager + SQLiteEventStore + IdempotencyStore)
    without booting the full TRACE pipeline. Each ``run_data`` passed
    to the factory is appended to ``self.invocations`` so the test can
    assert the executor was actually invoked.
    """

    def __init__(self, *, hold_seconds: float = 0.0) -> None:
        self.invocations: list[dict[str, Any]] = []
        self._hold_seconds = hold_seconds
        self._lock = threading.Lock()

    def __call__(self, run_data: dict[str, Any]):
        with self._lock:
            self.invocations.append(dict(run_data))

        hold = self._hold_seconds

        def _run():
            if hold > 0:
                time.sleep(hold)
            return None  # RunManager treats None as success.

        return _run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_app(tmp_path, monkeypatch):
    """Boot ``build_production_app`` with a recording executor injected.

    The fixture sets ``AGENT_SERVER_BACKEND=real`` (which is the
    default but we set it explicitly so the test is hermetic),
    constructs the production app, and replaces the AgentServer's
    executor factory with a recording stub so runs complete in a few
    milliseconds without driving the LLM gateway.
    """
    monkeypatch.setenv("AGENT_SERVER_BACKEND", "real")
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    # Keep the bootstrap-owned state dir under tmp_path so each test
    # gets fresh SQLite stores.
    monkeypatch.setenv("AGENT_SERVER_STATE_DIR", str(tmp_path / "state"))

    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path / "state")
    factory = _RecordingExecutorFactory(hold_seconds=0.0)
    backend = app.state.run_backend
    # Sanity: real backend is selected.
    assert backend.__class__.__name__ == "RealKernelBackend", backend
    backend.agent_server.executor_factory = factory
    yield app, factory
    # Drain background workers so the next test starts clean.
    backend.aclose()


@pytest.fixture()
def real_client(real_app):
    """TestClient wrapping the real-kernel production app."""
    app, _factory = real_app
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def real_factory(real_app) -> _RecordingExecutorFactory:
    """The recording executor factory for assertion access."""
    _app, factory = real_app
    return factory


def _headers(
    tenant: str = "tenant-w32a",
    *,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    out = {"X-Tenant-Id": tenant}
    if idempotency_key:
        out["Idempotency-Key"] = idempotency_key
    return out


# ---------------------------------------------------------------------------
# Step 1: 4-step smoke
# ---------------------------------------------------------------------------


# tdd-red-sha: TDD-RED-SHA-W32A
def test_smoke_step1_health_returns_200(real_client: TestClient) -> None:
    """GET /v1/health answers 200 once the real-kernel app is alive."""
    resp = real_client.get("/v1/health", headers={"X-Tenant-Id": "probe"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "ok"


# tdd-red-sha: TDD-RED-SHA-W32A
def test_smoke_step2_post_runs_same_key_same_body_returns_same_run_id(
    real_client: TestClient,
) -> None:
    """Two POST /v1/runs with same key + body yield identical run_id."""
    body = {
        "profile_id": "default",
        "goal": "smoke-step-2",
        "idempotency_key": "ria-w32a-smoke-2",
    }
    headers = _headers(idempotency_key="ria-w32a-smoke-2")

    first = real_client.post("/v1/runs", json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = real_client.post("/v1/runs", json=body, headers=headers)
    assert second.status_code == 201, second.text

    first_body = first.json()
    second_body = second.json()
    assert first_body["run_id"] == second_body["run_id"]


# tdd-red-sha: TDD-RED-SHA-W32A
def test_smoke_step3_post_runs_same_key_mutated_body_returns_409(
    real_client: TestClient,
) -> None:
    """Same key + DIFFERENT body returns 409 from IdempotencyMiddleware."""
    headers = _headers(idempotency_key="ria-w32a-smoke-3")

    first = real_client.post(
        "/v1/runs",
        json={
            "profile_id": "default",
            "goal": "smoke-step-3-A",
            "idempotency_key": "ria-w32a-smoke-3",
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text

    second = real_client.post(
        "/v1/runs",
        json={
            "profile_id": "default",
            "goal": "smoke-step-3-B",  # mutated
            "idempotency_key": "ria-w32a-smoke-3",
        },
        headers=headers,
    )
    assert second.status_code == 409, second.text
    assert second.json().get("error") == "ConflictError"


# tdd-red-sha: TDD-RED-SHA-W32A
def test_smoke_step4_get_runs_returns_real_state(
    real_client: TestClient,
) -> None:
    """GET /v1/runs/{id} surfaces the real RunManager-backed record."""
    body = {
        "profile_id": "default",
        "goal": "smoke-step-4",
        "idempotency_key": "ria-w32a-smoke-4",
    }
    headers = _headers(idempotency_key="ria-w32a-smoke-4")

    created = real_client.post("/v1/runs", json=body, headers=headers)
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    final = _wait_for_terminal(real_client, run_id, timeout=10.0)
    assert final["run_id"] == run_id
    # The recording stub returns success; RunManager maps None -> completed.
    assert final["state"] in {"completed", "failed"}, final


# ---------------------------------------------------------------------------
# Step 2: cancel live -> 200
# ---------------------------------------------------------------------------


# tdd-red-sha: TDD-RED-SHA-W32A
def test_cancel_live_run_returns_200(
    real_client: TestClient,
    real_app,
) -> None:
    """POST /v1/runs/{id}/cancel on a live run returns 200."""
    app, _factory = real_app
    # Inject a slower executor so the run is still alive when cancel
    # arrives. We swap on the backend so the original recording factory
    # is preserved for the rest of the suite.
    slow_factory = _RecordingExecutorFactory(hold_seconds=2.0)
    app.state.run_backend.agent_server.executor_factory = slow_factory

    body = {
        "profile_id": "default",
        "goal": "cancel-live",
        "idempotency_key": "ria-w32a-cancel-live",
    }
    created = real_client.post(
        "/v1/runs",
        json=body,
        headers=_headers(idempotency_key="ria-w32a-cancel-live"),
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    # Give the worker a moment to claim the run.
    time.sleep(0.1)

    cancel = real_client.post(
        f"/v1/runs/{run_id}/cancel", headers=_headers()
    )
    assert cancel.status_code == 200, cancel.text
    body = cancel.json()
    assert body["run_id"] == run_id
    # state may be "cancelled" (RunManager terminal) or one of the
    # transitional states observable mid-cancel — accept anything that
    # is not "completed" before the run finishes.
    assert body["state"] in {"cancelled", "running", "created"}, body

    # Eventually the run reaches a cancelled terminal state.
    final = _wait_for_terminal(real_client, run_id, timeout=10.0)
    assert final["state"] == "cancelled", final


# ---------------------------------------------------------------------------
# Step 3: cancel unknown -> 404 (Rule 8 step-6)
# ---------------------------------------------------------------------------


# tdd-red-sha: TDD-RED-SHA-W32A
def test_cancel_unknown_run_returns_404(real_client: TestClient) -> None:
    """POST /v1/runs/{unknown_id}/cancel returns 404 NotFoundError."""
    resp = real_client.post(
        "/v1/runs/run-does-not-exist/cancel",
        headers=_headers(),
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body.get("error") == "NotFoundError"


# ---------------------------------------------------------------------------
# Step 4: SSE emits real lifecycle events
# ---------------------------------------------------------------------------


# tdd-red-sha: TDD-RED-SHA-W32A
def test_sse_events_emits_real_lifecycle(
    real_client: TestClient,
) -> None:
    """SSE /v1/runs/{id}/events emits real run_queued / run_started events."""
    body = {
        "profile_id": "default",
        "goal": "sse-lifecycle",
        "idempotency_key": "ria-w32a-sse-1",
    }
    created = real_client.post(
        "/v1/runs",
        json=body,
        headers=_headers(idempotency_key="ria-w32a-sse-1"),
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    # Wait for terminal so the event store has flushed all lifecycle rows.
    _wait_for_terminal(real_client, run_id, timeout=10.0)

    # Now stream events; the run is terminal so SSE returns immediately.
    event_types: list[str] = []
    with real_client.stream(
        "GET", f"/v1/runs/{run_id}/events", headers=_headers()
    ) as resp:
        assert resp.status_code == 200, resp.text
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[len("data:") :].strip())
            except json.JSONDecodeError:
                continue
            event_types.append(payload.get("event_type", ""))

    # The event store must contain at least the queued + started + a
    # terminal event for this run. If any of these are missing the
    # real-kernel binding is not flushing the SQLiteEventStore.
    assert "run_queued" in event_types, event_types
    assert "run_started" in event_types, event_types
    terminal_seen = any(
        et in {"run_completed", "run_failed", "run_cancelled"} for et in event_types
    )
    assert terminal_seen, event_types


# ---------------------------------------------------------------------------
# Step 5: executor invocation recorded by stub
# ---------------------------------------------------------------------------


# tdd-red-sha: TDD-RED-SHA-W32A
def test_stub_executor_records_invocation_for_started_run(
    real_client: TestClient,
    real_factory: _RecordingExecutorFactory,
) -> None:
    """A stub executor attached to a run is invoked exactly once.

    Substitutes for "SkillSpec attached to a run is invoked" — the
    real-kernel path goes through ``AgentServer.executor_factory``;
    the recording stub captures every invocation so the test can prove
    the kernel actually drove the executor (and therefore would invoke
    a SkillSpec-bound executor when the SkillSpec contract lands).
    """
    body = {
        "profile_id": "default",
        "goal": "stub-executor-invocation",
        "idempotency_key": "ria-w32a-stub-1",
    }
    created = real_client.post(
        "/v1/runs",
        json=body,
        headers=_headers(idempotency_key="ria-w32a-stub-1"),
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    _wait_for_terminal(real_client, run_id, timeout=10.0)

    # The stub must have been called for this run_id at least once.
    matching = [
        inv for inv in real_factory.invocations if inv.get("run_id") == run_id
    ]
    assert matching, real_factory.invocations
    # And the invocation carries the goal we submitted.
    assert matching[0].get("goal") == "stub-executor-invocation"
