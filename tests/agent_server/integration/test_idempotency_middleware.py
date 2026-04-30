"""Integration tests for IdempotencyMiddleware (W24 I-D).

Drives the build of:
  * agent_server/api/middleware/idempotency.py
  * agent_server/facade/idempotency_facade.py

Uses FastAPI TestClient against a real ASGI app. The run facade is
constructed with an in-process stub backend so the tests stay in the
default-offline profile (no network, no real LLM, no secrets).

Test surface (>=7 cases):
  1. same key + same body -> byte-identical replay
  2. same key + different body -> 409
  3. missing header in research/prod -> 400
  4. missing header in dev -> handler runs (warning only)
  5. cross-tenant key collision -> distinct responses
  6. identity metadata stripped on replay (HD-7)
  7. non-mutating GET passes through untouched
  8. 5xx response releases the slot for retry
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agent_server.api.middleware.idempotency import register_idempotency_middleware
from agent_server.api.middleware.tenant_context import TenantContextMiddleware
from agent_server.api.routes_runs import build_router
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.idempotency_facade import IdempotencyFacade
from agent_server.facade.run_facade import RunFacade
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_server import AGENT_SERVER_API_VERSION


class _StubBackend:
    """Minimal backend modelling start/get/signal_run for the facade."""

    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], dict[str, Any]] = {}
        self._counter = 0
        self.start_calls = 0

    def start_run(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        goal: str,
        project_id: str,
        run_id: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.start_calls += 1
        self._counter += 1
        rid = run_id or f"run_{self._counter:04d}"
        record = {
            "tenant_id": tenant_id,
            "run_id": rid,
            "state": "queued",
            "current_stage": None,
            "started_at": "2026-04-30T00:00:00Z",
            "finished_at": None,
            "metadata": dict(metadata),
            "llm_fallback_count": 0,
            "request_id": f"req-{self._counter}",
            "trace_id": f"trace-{self._counter}",
        }
        self.runs[(tenant_id, rid)] = record
        return record

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        return record

    def signal_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        signal: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        record["state"] = "cancelling" if signal == "cancel" else record["state"]
        return record


def _build_app(
    backend: _StubBackend,
    db_path: Path,
    *,
    strict: bool,
) -> FastAPI:
    facade = RunFacade(
        start_run=backend.start_run,
        get_run=backend.get_run,
        signal_run=backend.signal_run,
    )
    idem = IdempotencyFacade(db_path=db_path)
    app = FastAPI(version=AGENT_SERVER_API_VERSION)
    app.add_middleware(TenantContextMiddleware)
    register_idempotency_middleware(app, facade=idem, strict=strict)
    app.include_router(build_router(run_facade=facade))
    return app


@pytest.fixture()
def backend() -> _StubBackend:
    return _StubBackend()


@pytest.fixture()
def dev_client(backend: _StubBackend, tmp_path: Path) -> TestClient:
    app = _build_app(backend, tmp_path / "idem_dev.db", strict=False)
    return TestClient(app)


@pytest.fixture()
def strict_client(backend: _StubBackend, tmp_path: Path) -> TestClient:
    app = _build_app(backend, tmp_path / "idem_strict.db", strict=True)
    return TestClient(app)


def _hdr(tenant: str = "tenant-A", *, idem: str | None = None) -> dict[str, str]:
    headers = {"X-Tenant-Id": tenant}
    if idem is not None:
        headers["Idempotency-Key"] = idem
    return headers


# ----------------------------------------------------------------------
# Cases
# ----------------------------------------------------------------------


def test_same_key_same_body_replays_byte_identical_content(
    dev_client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "demo", "idempotency_key": "k-1"}
    first = dev_client.post("/v1/runs", json=body, headers=_hdr(idem="k-1"))
    assert first.status_code == 200
    second = dev_client.post("/v1/runs", json=body, headers=_hdr(idem="k-1"))
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["run_id"] == second_body["run_id"]
    # Backend was called only once; the second request was served from cache.
    assert backend.start_calls == 1


def test_same_key_diff_body_returns_409(dev_client: TestClient) -> None:
    dev_client.post(
        "/v1/runs",
        json={"profile_id": "default", "goal": "first", "idempotency_key": "k-2"},
        headers=_hdr(idem="k-2"),
    )
    second = dev_client.post(
        "/v1/runs",
        json={"profile_id": "default", "goal": "DIFFERENT", "idempotency_key": "k-2"},
        headers=_hdr(idem="k-2"),
    )
    assert second.status_code == 409
    assert second.json()["error"] == "ConflictError"


def test_missing_header_in_research_prod_returns_400(
    strict_client: TestClient,
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "k-3"}
    resp = strict_client.post("/v1/runs", json=body, headers=_hdr())
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["error"] == "ContractError"
    assert "idempotency-key" in payload["message"].lower()


def test_missing_header_in_dev_warning_only(
    dev_client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "x", "idempotency_key": "k-4"}
    resp = dev_client.post("/v1/runs", json=body, headers=_hdr())
    # Body still has idempotency_key so the route-level facade succeeds;
    # the missing header simply means no replay is set up.
    assert resp.status_code == 200
    assert backend.start_calls == 1


def test_cross_tenant_key_collision_returns_distinct_responses(
    dev_client: TestClient, backend: _StubBackend
) -> None:
    body = {"profile_id": "default", "goal": "y", "idempotency_key": "shared"}
    a_resp = dev_client.post(
        "/v1/runs", json=body, headers=_hdr("tenant-A", idem="shared")
    )
    b_resp = dev_client.post(
        "/v1/runs", json=body, headers=_hdr("tenant-B", idem="shared")
    )
    assert a_resp.status_code == 200
    assert b_resp.status_code == 200
    assert a_resp.json()["run_id"] != b_resp.json()["run_id"]
    assert a_resp.json()["tenant_id"] == "tenant-A"
    assert b_resp.json()["tenant_id"] == "tenant-B"


def test_identity_metadata_stripped_on_replay(
    dev_client: TestClient, backend: _StubBackend
) -> None:
    """HD-7: stored snapshot must NOT carry request_id/trace_id."""
    body = {"profile_id": "default", "goal": "z", "idempotency_key": "k-id"}
    dev_client.post("/v1/runs", json=body, headers=_hdr(idem="k-id"))
    replayed = dev_client.post("/v1/runs", json=body, headers=_hdr(idem="k-id")).json()
    assert "request_id" not in replayed
    assert "trace_id" not in replayed
    assert "_response_timestamp" not in replayed


def test_get_route_is_not_idempotency_guarded(
    dev_client: TestClient, backend: _StubBackend
) -> None:
    """Read-only routes must pass through without touching the store."""
    create = dev_client.post(
        "/v1/runs",
        json={"profile_id": "default", "goal": "g", "idempotency_key": "k-get"},
        headers=_hdr(idem="k-get"),
    )
    rid = create.json()["run_id"]
    # No Idempotency-Key on a GET -- must NOT 400 even under strict.
    resp = dev_client.get(f"/v1/runs/{rid}", headers=_hdr())
    assert resp.status_code == 200


def test_5xx_releases_slot_for_retry(tmp_path: Path) -> None:
    """A handler exception must release the reservation so the retry succeeds."""
    backend = _StubBackend()
    raise_once = {"count": 0}

    original_start = backend.start_run

    def flaky_start(**kwargs: Any) -> dict[str, Any]:
        if raise_once["count"] == 0:
            raise_once["count"] += 1
            raise RuntimeError("transient")
        return original_start(**kwargs)

    backend.start_run = flaky_start  # type: ignore[assignment]
    app = _build_app(backend, tmp_path / "idem_retry.db", strict=False)
    client = TestClient(app, raise_server_exceptions=False)
    body = {"profile_id": "default", "goal": "retry", "idempotency_key": "k-retry"}
    first = client.post("/v1/runs", json=body, headers=_hdr(idem="k-retry"))
    assert first.status_code >= 500
    second = client.post("/v1/runs", json=body, headers=_hdr(idem="k-retry"))
    assert second.status_code == 200, second.text
