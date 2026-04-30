"""Integration tests for /v1/runs/{id}/cancel and /v1/runs/{id}/events (W24 Track I-A).

These tests are the TDD-RED stage per R-AS-5. They drive the build of:
  - agent_server/api/routes_runs_extended.py
  - agent_server/facade/event_facade.py

Tests use FastAPI's TestClient against a real ASGI app. Facades are
constructed with in-process stub callables so the tests stay in the
default-offline profile (no network, no real LLM, no secrets).
"""
from __future__ import annotations

import json
from typing import Any, Iterable

import pytest
from fastapi.testclient import TestClient

from agent_server.api import build_app
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.event_facade import EventFacade
from agent_server.facade.run_facade import RunFacade


class _StubBackend:
    """In-memory stub that exposes both run + event surfaces."""

    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], dict[str, Any]] = {}
        self.idempotency: dict[tuple[str, str], str] = {}
        self.cancelled: list[tuple[str, str]] = []
        self.events: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def start_run(self, *, tenant_id: str, profile_id: str, goal: str,
                  project_id: str, run_id: str, idempotency_key: str,
                  metadata: dict[str, Any]) -> dict[str, Any]:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        rid = run_id or f"run_{len(self.runs) + 1:04d}"
        record = {
            "tenant_id": tenant_id,
            "run_id": rid,
            "state": "queued",
            "current_stage": None,
            "started_at": "2026-04-30T00:00:00Z",
            "finished_at": None,
            "metadata": dict(metadata),
            "llm_fallback_count": 0,
        }
        self.runs[(tenant_id, rid)] = record
        return record

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        return record

    def signal_run(self, *, tenant_id: str, run_id: str,
                   signal: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        return record

    def cancel_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        self.cancelled.append((tenant_id, run_id))
        # Idempotent: if already terminal, return current state unchanged.
        if record["state"] in {"done", "failed", "cancelled"}:
            return record
        record["state"] = "cancelled"
        record["finished_at"] = "2026-04-30T00:01:00Z"
        return record

    def iter_events(
        self, *, tenant_id: str, run_id: str
    ) -> Iterable[dict[str, Any]]:
        # Tenant scoping: cross-tenant queries return empty.
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            return iter([])
        return iter(self.events.get((tenant_id, run_id), []))


@pytest.fixture()
def backend() -> _StubBackend:
    return _StubBackend()


@pytest.fixture()
def client(backend: _StubBackend) -> TestClient:
    run_facade = RunFacade(
        start_run=backend.start_run,
        get_run=backend.get_run,
        signal_run=backend.signal_run,
    )
    event_facade = EventFacade(
        cancel_run=backend.cancel_run,
        get_run=backend.get_run,
        iter_events=backend.iter_events,
    )
    app = build_app(run_facade=run_facade, event_facade=event_facade)
    return TestClient(app)


def _headers(tenant: str = "tenant-A") -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


# ---------------------------------------------------------------------------
# /v1/runs/{id}/cancel
# ---------------------------------------------------------------------------


def test_cancel_run_success_returns_200(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "c-1"}
    created = client.post("/v1/runs", json=body, headers=_headers()).json()
    rid = created["run_id"]
    resp = client.post(f"/v1/runs/{rid}/cancel", headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run_id"] == rid
    assert data["state"] == "cancelled"
    assert backend.cancelled == [("tenant-A", rid)]


def test_cancel_unknown_run_returns_404(client: TestClient) -> None:
    resp = client.post("/v1/runs/run_missing/cancel", headers=_headers())
    assert resp.status_code == 404
    assert resp.json()["error"] == "NotFoundError"


def test_cancel_cross_tenant_returns_404(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "iso-c-1"}
    created = client.post(
        "/v1/runs", json=body, headers=_headers("tenant-A")
    ).json()
    rid = created["run_id"]
    resp = client.post(f"/v1/runs/{rid}/cancel", headers=_headers("tenant-B"))
    assert resp.status_code == 404
    assert ("tenant-B", rid) not in backend.cancelled


def test_cancel_idempotent_on_terminal_run(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "term-1"}
    created = client.post("/v1/runs", json=body, headers=_headers()).json()
    rid = created["run_id"]
    # Force terminal state directly on the stub.
    backend.runs[("tenant-A", rid)]["state"] = "done"
    backend.runs[("tenant-A", rid)]["finished_at"] = "2026-04-30T00:00:30Z"
    resp = client.post(f"/v1/runs/{rid}/cancel", headers=_headers())
    assert resp.status_code == 200
    data = resp.json()
    # Idempotent: state stays "done", not "cancelled".
    assert data["state"] == "done"


# ---------------------------------------------------------------------------
# /v1/runs/{id}/events
# ---------------------------------------------------------------------------


def test_events_stream_returns_sse_content_type(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "ev-ct"}
    created = client.post("/v1/runs", json=body, headers=_headers()).json()
    rid = created["run_id"]
    backend.runs[("tenant-A", rid)]["state"] = "done"
    backend.events[("tenant-A", rid)] = [
        {"sequence": 1, "event_type": "stage", "payload_json": '{"k":"v"}'}
    ]
    with client.stream("GET", f"/v1/runs/{rid}/events", headers=_headers()) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


def test_events_stream_yields_events(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "ev-y-1"}
    created = client.post("/v1/runs", json=body, headers=_headers()).json()
    rid = created["run_id"]
    # Force terminal so the stream closes deterministically.
    backend.runs[("tenant-A", rid)]["state"] = "done"
    backend.events[("tenant-A", rid)] = [
        {"sequence": 1, "event_type": "stage", "payload_json": '{"a":1}'},
        {"sequence": 2, "event_type": "done", "payload_json": '{"a":2}'},
    ]
    with client.stream("GET", f"/v1/runs/{rid}/events", headers=_headers()) as resp:
        assert resp.status_code == 200
        body_text = "".join(chunk for chunk in resp.iter_text())
    assert "id: 1" in body_text
    assert "id: 2" in body_text
    # Each event has a data: line.
    parsed = [
        json.loads(seg.split("data: ", 1)[1].strip())
        for seg in body_text.split("\n\n")
        if "data: " in seg
    ]
    assert any(ev["event_type"] == "stage" for ev in parsed)
    assert any(ev["event_type"] == "done" for ev in parsed)


def test_events_unknown_run_returns_404(client: TestClient) -> None:
    resp = client.get("/v1/runs/run_missing/events", headers=_headers())
    assert resp.status_code == 404
    assert resp.json()["error"] == "NotFoundError"


def test_events_cross_tenant_returns_404(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "ev-iso-1"}
    created = client.post(
        "/v1/runs", json=body, headers=_headers("tenant-A")
    ).json()
    rid = created["run_id"]
    backend.events[("tenant-A", rid)] = [
        {"sequence": 1, "event_type": "stage", "payload_json": '{}'}
    ]
    resp = client.get(f"/v1/runs/{rid}/events", headers=_headers("tenant-B"))
    assert resp.status_code == 404
