"""Integration tests for /v1/runs route handlers (W23 Track F, R-AS-5 RED).

These tests are the TDD-RED stage. They drive the build of:
  - agent_server/api/routes_runs.py
  - agent_server/api/middleware/tenant_context.py
  - agent_server/facade/run_facade.py
  - agent_server/api/__init__.py::build_app

They use FastAPI's TestClient against a real ASGI app. The facade is
constructed with an in-process stub backend so the tests stay in the
default-offline profile (no network, no real LLM, no secrets).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_server.api import build_app
from agent_server.contracts.errors import ConflictError, NotFoundError
from agent_server.contracts.run import RunRequest, RunResponse, RunStatus
from agent_server.contracts.tenancy import TenantContext
from agent_server.facade.run_facade import RunFacade


class _StubBackend:
    """In-memory stub backend used to drive the facade in tests.

    Exposes a callable surface that the facade marshals contract types
    into. Tracks idempotency keys and signals so we can assert behaviour.
    """

    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], dict[str, Any]] = {}
        self.idempotency: dict[tuple[str, str], str] = {}
        self.signals: list[tuple[str, str, str]] = []

    def start_run(self, *, tenant_id: str, profile_id: str, goal: str,
                  project_id: str, run_id: str, idempotency_key: str,
                  metadata: dict[str, Any]) -> dict[str, Any]:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        key = (tenant_id, idempotency_key)
        if key in self.idempotency:
            raise ConflictError(
                "duplicate idempotency_key",
                tenant_id=tenant_id,
                detail=idempotency_key,
            )
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
        self.idempotency[key] = rid
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
        self.signals.append((tenant_id, run_id, signal))
        record["state"] = "cancelling" if signal == "cancel" else record["state"]
        return record


@pytest.fixture()
def backend() -> _StubBackend:
    return _StubBackend()


@pytest.fixture()
def client(backend: _StubBackend) -> TestClient:
    facade = RunFacade(
        start_run=backend.start_run,
        get_run=backend.get_run,
        signal_run=backend.signal_run,
    )
    app = build_app(run_facade=facade)
    return TestClient(app)


def _headers(tenant: str = "tenant-A") -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


def test_post_runs_success_returns_200_and_run_id(client: TestClient) -> None:
    body = {
        "profile_id": "default",
        "goal": "demo",
        "idempotency_key": "idem-001",
        "metadata": {"k": "v"},
    }
    resp = client.post("/v1/runs", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["tenant_id"] == "tenant-A"
    assert data["run_id"].startswith("run_")
    assert data["state"] == "queued"


def test_post_runs_missing_tenant_header_returns_401(client: TestClient) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "i-01"}
    resp = client.post("/v1/runs", json=body)  # no header
    assert resp.status_code == 401
    assert "tenant" in resp.json().get("error", "").lower() or \
           "tenant" in resp.json().get("detail", "").lower()


def test_post_runs_missing_idempotency_key_returns_400(client: TestClient) -> None:
    body = {"profile_id": "default", "goal": "x"}  # no idempotency_key
    resp = client.post("/v1/runs", json=body, headers=_headers())
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["error"] == "ContractError"


def test_post_runs_duplicate_idempotency_key_returns_409(
    client: TestClient,
) -> None:
    body = {
        "profile_id": "default",
        "goal": "x",
        "idempotency_key": "dup-1",
    }
    first = client.post("/v1/runs", json=body, headers=_headers())
    assert first.status_code == 200
    second = client.post("/v1/runs", json=body, headers=_headers())
    assert second.status_code == 409
    assert second.json()["error"] == "ConflictError"


def test_get_run_success_returns_status(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "y", "idempotency_key": "g-1"}
    created = client.post("/v1/runs", json=body, headers=_headers()).json()
    rid = created["run_id"]
    resp = client.get(f"/v1/runs/{rid}", headers=_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == "tenant-A"
    assert data["run_id"] == rid
    assert data["state"] == "queued"
    assert data["llm_fallback_count"] == 0


def test_get_run_not_found_returns_404(client: TestClient) -> None:
    resp = client.get("/v1/runs/run_does_not_exist", headers=_headers())
    assert resp.status_code == 404
    assert resp.json()["error"] == "NotFoundError"


def test_get_run_tenant_isolation(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "y", "idempotency_key": "iso-1"}
    created = client.post("/v1/runs", json=body, headers=_headers("tenant-A")).json()
    rid = created["run_id"]
    # Other tenant must NOT see tenant-A's run
    resp = client.get(f"/v1/runs/{rid}", headers=_headers("tenant-B"))
    assert resp.status_code == 404


def test_post_signal_success_returns_200(
    client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "z", "idempotency_key": "s-1"}
    created = client.post("/v1/runs", json=body, headers=_headers()).json()
    rid = created["run_id"]
    resp = client.post(
        f"/v1/runs/{rid}/signal",
        json={"signal": "cancel"},
        headers=_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == rid
    assert data["state"] == "cancelling"
    assert backend.signals == [("tenant-A", rid, "cancel")]


def test_post_signal_unknown_run_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/runs/run_missing/signal",
        json={"signal": "cancel"},
        headers=_headers(),
    )
    assert resp.status_code == 404


def test_facade_constructs_run_response_dataclass(backend: _StubBackend) -> None:
    """Facade must return contract dataclasses, not dicts (R-AS-2)."""
    facade = RunFacade(
        start_run=backend.start_run,
        get_run=backend.get_run,
        signal_run=backend.signal_run,
    )
    ctx = TenantContext(tenant_id="t-1")
    req = RunRequest(
        tenant_id="t-1",
        profile_id="default",
        goal="hi",
        idempotency_key="k-1",
    )
    resp = facade.start(ctx, req)
    assert isinstance(resp, RunResponse)
    assert resp.tenant_id == "t-1"
    status = facade.status(ctx, resp.run_id)
    assert isinstance(status, RunStatus)
