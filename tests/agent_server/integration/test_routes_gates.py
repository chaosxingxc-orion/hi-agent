"""Integration tests for POST /v1/gates/{gate_id}/decide (W24-P).

Layer 2 integration tests: real TestClient against a real ASGI app instance
with no mocks on the route handlers or middleware under test. The app is
built with a minimal stub run_facade — the gates route is self-contained and
needs no gate-specific facade.

Coverage:
  POST /v1/gates/{gate_id}/decide
    - happy path: approved decision -> 200 + full response envelope
    - happy path: rejected decision -> 200 + full response envelope
    - missing run_id -> 400
    - missing / invalid decision -> 400
    - unknown decision value -> 400
    - missing X-Tenant-Id header -> 401
    - tenant_id in response reflects X-Tenant-Id header (isolation)
    - gate_id in response matches path parameter
    - decided_at is auto-stamped when not supplied
    - decided_at is forwarded when supplied
    - reason and decided_by are forwarded when supplied
"""
from __future__ import annotations

from typing import Any

import pytest
from agent_server.api import build_app
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.run_facade import RunFacade
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Minimal stub backend so build_app's required run_facade is satisfied.
# The gates route does NOT touch the run_facade.
# ---------------------------------------------------------------------------

def _stub_start_run(**_: Any) -> dict[str, Any]:
    return {
        "tenant_id": "stub",
        "run_id": "run_stub",
        "state": "queued",
        "current_stage": None,
        "started_at": None,
        "finished_at": None,
        "metadata": {},
        "llm_fallback_count": 0,
    }


def _stub_get_run(*, tenant_id: str, run_id: str) -> dict[str, Any]:
    raise NotFoundError("stub", tenant_id=tenant_id, detail=run_id)


def _stub_signal_run(**_: Any) -> dict[str, Any]:
    raise NotFoundError("stub")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    run_facade = RunFacade(
        start_run=_stub_start_run,
        get_run=_stub_get_run,
        signal_run=_stub_signal_run,
    )
    app = build_app(
        run_facade=run_facade,
        include_skills_memory=False,
        include_gates=True,
        include_mcp_tools=False,
    )
    return TestClient(app)


def _headers(tenant: str = "tenant-A") -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


# ---------------------------------------------------------------------------
# POST /v1/gates/{gate_id}/decide — happy path
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_gates_decide_approved_returns_200(client: TestClient) -> None:
    body = {
        "run_id": "run-001",
        "decision": "approved",
    }
    resp = client.post("/v1/gates/gate-xyz/decide", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["tenant_id"] == "tenant-A"
    assert data["gate_id"] == "gate-xyz"
    assert data["run_id"] == "run-001"
    assert data["decision"] == "approved"
    assert data["status"] == "recorded"


@pytest.mark.integration
def test_post_gates_decide_rejected_returns_200(client: TestClient) -> None:
    body = {
        "run_id": "run-002",
        "decision": "rejected",
    }
    resp = client.post("/v1/gates/gate-abc/decide", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["decision"] == "rejected"
    assert data["gate_id"] == "gate-abc"
    assert data["status"] == "recorded"


@pytest.mark.integration
def test_post_gates_decide_response_contains_all_envelope_fields(
    client: TestClient,
) -> None:
    body = {"run_id": "run-003", "decision": "approved"}
    resp = client.post("/v1/gates/gate-full/decide", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "tenant_id" in data
    assert "gate_id" in data
    assert "run_id" in data
    assert "decision" in data
    assert "reason" in data
    assert "decided_by" in data
    assert "decided_at" in data
    assert "status" in data


@pytest.mark.integration
def test_post_gates_decide_gate_id_matches_path_parameter(
    client: TestClient,
) -> None:
    """gate_id in response envelope must echo the URL path parameter."""
    for gid in ("gate-alpha", "gate-beta", "gate-gamma"):
        body = {"run_id": "run-004", "decision": "approved"}
        resp = client.post(f"/v1/gates/{gid}/decide", json=body, headers=_headers())
        assert resp.status_code == 200, resp.text
        assert resp.json()["gate_id"] == gid


@pytest.mark.integration
def test_post_gates_decide_decided_at_auto_stamped_when_absent(
    client: TestClient,
) -> None:
    """When decided_at is not in body, handler stamps current timestamp."""
    body = {"run_id": "run-005", "decision": "approved"}
    resp = client.post("/v1/gates/gate-stamp/decide", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    decided_at = resp.json()["decided_at"]
    assert decided_at  # non-empty
    # Must look like an ISO 8601 timestamp (contains 'T' separator)
    assert "T" in decided_at


@pytest.mark.integration
def test_post_gates_decide_decided_at_forwarded_when_supplied(
    client: TestClient,
) -> None:
    """When decided_at is supplied, it must be forwarded as-is."""
    ts = "2026-05-01T12:00:00+00:00"
    body = {"run_id": "run-006", "decision": "rejected", "decided_at": ts}
    resp = client.post("/v1/gates/gate-ts/decide", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["decided_at"] == ts


@pytest.mark.integration
def test_post_gates_decide_reason_forwarded(client: TestClient) -> None:
    body = {
        "run_id": "run-007",
        "decision": "approved",
        "reason": "All checks passed.",
    }
    resp = client.post("/v1/gates/gate-reason/decide", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["reason"] == "All checks passed."


@pytest.mark.integration
def test_post_gates_decide_decided_by_forwarded(client: TestClient) -> None:
    body = {
        "run_id": "run-008",
        "decision": "rejected",
        "decided_by": "alice@example.com",
    }
    resp = client.post("/v1/gates/gate-by/decide", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["decided_by"] == "alice@example.com"


# ---------------------------------------------------------------------------
# POST /v1/gates/{gate_id}/decide — validation errors
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_gates_decide_missing_run_id_returns_400(client: TestClient) -> None:
    body = {"decision": "approved"}  # run_id omitted
    resp = client.post("/v1/gates/gate-x/decide", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "run_id" in data["message"]


@pytest.mark.integration
def test_post_gates_decide_missing_decision_returns_400(client: TestClient) -> None:
    body = {"run_id": "run-009"}  # decision omitted — defaults to "" which is invalid
    resp = client.post("/v1/gates/gate-x/decide", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "decision" in data["message"]


@pytest.mark.integration
def test_post_gates_decide_invalid_decision_value_returns_400(
    client: TestClient,
) -> None:
    body = {"run_id": "run-010", "decision": "maybe"}
    resp = client.post("/v1/gates/gate-x/decide", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "decision" in data["message"]


@pytest.mark.integration
def test_post_gates_decide_empty_decision_returns_400(client: TestClient) -> None:
    body = {"run_id": "run-011", "decision": ""}
    resp = client.post("/v1/gates/gate-x/decide", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"


# ---------------------------------------------------------------------------
# POST /v1/gates/{gate_id}/decide — tenant scoping
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_gates_decide_missing_tenant_header_returns_401(
    client: TestClient,
) -> None:
    body = {"run_id": "run-012", "decision": "approved"}
    resp = client.post("/v1/gates/gate-x/decide", json=body)  # no X-Tenant-Id
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
def test_post_gates_decide_tenant_id_in_response_matches_header(
    client: TestClient,
) -> None:
    """tenant_id in response must reflect the X-Tenant-Id header (isolation)."""
    body = {"run_id": "run-013", "decision": "approved"}
    resp_a = client.post(
        "/v1/gates/gate-iso/decide", json=body, headers=_headers("tenant-A")
    )
    resp_b = client.post(
        "/v1/gates/gate-iso/decide", json=body, headers=_headers("tenant-B")
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["tenant_id"] == "tenant-A"
    assert resp_b.json()["tenant_id"] == "tenant-B"
