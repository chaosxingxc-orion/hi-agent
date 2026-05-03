"""Integration tests for POST /v1/skills and POST /v1/memory/write (W24-P).

Layer 2 integration tests: real TestClient against a real ASGI app instance
with no mocks on the route handlers or middleware under test. The app is
built with minimal stub facades (run_facade only — skills/memory routes
need no facade; they are self-contained handlers).

Coverage:
  POST /v1/skills
    - happy path: 200 + response envelope fields
    - missing skill_id -> 400
    - missing version -> 400
    - missing handler_ref -> 400
    - missing X-Tenant-Id header -> 401
    - tenant_id in response reflects X-Tenant-Id header (isolation)
    - idempotency_key echo in response

  POST /v1/memory/write
    - happy path: 200 + response envelope fields
    - missing key -> 400
    - invalid tier -> 400
    - missing X-Tenant-Id header -> 401
    - tenant_id in response reflects X-Tenant-Id header (isolation)
    - idempotency_key echo in response
"""
from __future__ import annotations

import os
import time
from typing import Any

import jwt as pyjwt
import pytest
from agent_server.api import build_app
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.run_facade import RunFacade
from fastapi.testclient import TestClient

# W33-C.4: JWT auth middleware was added to build_app(); under
# research/prod posture, every request needs a valid Bearer token.
# Tests that previously ran under research without auth now must
# present a bearer.
_JWT_SECRET = "test-secret-w33-skills-memory-must-be-32-bytes-padding-pad"
_JWT_AUDIENCE = "hi-agent"


def _make_bearer(tenant: str = "tenant-A", role: str = "write") -> str:
    payload = {
        "sub": f"user-for-{tenant}",
        "tenant_id": tenant,
        "role": role,
        "aud": _JWT_AUDIENCE,
        "exp": int(time.time()) + 3600,
    }
    token = pyjwt.encode(payload, _JWT_SECRET, algorithm="HS256")
    return f"Bearer {token}"


@pytest.fixture(autouse=True)
def _jwt_secret_env(monkeypatch):
    """All tests in this module sign tokens with the same test secret."""
    monkeypatch.setenv("HI_AGENT_JWT_SECRET", _JWT_SECRET)
    yield

# ---------------------------------------------------------------------------
# Minimal stub backend so build_app's required run_facade is satisfied.
# The skills/memory routes do NOT touch the run_facade; they are
# self-contained handlers, so this stub never has its methods called.
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
        include_skills_memory=True,
        include_gates=False,
        include_mcp_tools=False,
    )
    return TestClient(app)


def _headers(tenant: str = "tenant-A", *, role: str = "write") -> dict[str, str]:
    """Return canonical headers including a valid JWT (W33-C.4 auth)."""
    return {"X-Tenant-Id": tenant, "Authorization": _make_bearer(tenant, role)}


# ---------------------------------------------------------------------------
# POST /v1/skills — happy path
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_skills_happy_path_returns_200(client: TestClient) -> None:
    body = {
        "skill_id": "greet",
        "version": "1.0.0",
        "handler_ref": "myapp.skills.greet",
    }
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["tenant_id"] == "tenant-A"
    assert data["skill_id"] == "greet"
    assert data["version"] == "1.0.0"
    assert data["status"] == "registered"


@pytest.mark.integration
def test_post_skills_response_contains_all_envelope_fields(
    client: TestClient,
) -> None:
    body = {
        "skill_id": "summarize",
        "version": "2.1.0",
        "handler_ref": "myapp.skills.summarize",
    }
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "tenant_id" in data
    assert "skill_id" in data
    assert "version" in data
    assert "status" in data
    assert "idempotency_key" in data


@pytest.mark.integration
def test_post_skills_idempotency_key_echoed_in_response(
    client: TestClient,
) -> None:
    body = {
        "skill_id": "translate",
        "version": "3.0.0",
        "handler_ref": "myapp.skills.translate",
    }
    idem_key = "idem-skill-001"
    resp = client.post(
        "/v1/skills",
        json=body,
        headers={**_headers(), "Idempotency-Key": idem_key},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["idempotency_key"] == idem_key


@pytest.mark.integration
def test_post_skills_without_idempotency_key_returns_200_dev_posture(
    client: TestClient, monkeypatch
) -> None:
    """Under dev posture (default), missing Idempotency-Key is allowed."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    body = {
        "skill_id": "classify",
        "version": "1.0.0",
        "handler_ref": "myapp.skills.classify",
    }
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["idempotency_key"] == ""


# ---------------------------------------------------------------------------
# POST /v1/skills — validation errors
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_skills_missing_skill_id_returns_400(client: TestClient) -> None:
    body = {
        "version": "1.0.0",
        "handler_ref": "myapp.skills.greet",
    }
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "skill_id" in data["message"]


@pytest.mark.integration
def test_post_skills_missing_version_returns_400(client: TestClient) -> None:
    body = {
        "skill_id": "greet",
        "handler_ref": "myapp.skills.greet",
    }
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "version" in data["message"]


@pytest.mark.integration
def test_post_skills_missing_handler_ref_returns_400(client: TestClient) -> None:
    body = {
        "skill_id": "greet",
        "version": "1.0.0",
    }
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "handler_ref" in data["message"]


# ---------------------------------------------------------------------------
# POST /v1/skills — tenant scoping
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_skills_missing_tenant_header_returns_401(
    client: TestClient,
) -> None:
    body = {
        "skill_id": "greet",
        "version": "1.0.0",
        "handler_ref": "myapp.skills.greet",
    }
    resp = client.post("/v1/skills", json=body)  # no X-Tenant-Id header
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
def test_post_skills_tenant_id_in_response_matches_header(
    client: TestClient,
) -> None:
    """tenant_id in response must reflect the X-Tenant-Id header (isolation)."""
    body = {
        "skill_id": "detect",
        "version": "1.0.0",
        "handler_ref": "myapp.skills.detect",
    }
    resp_a = client.post("/v1/skills", json=body, headers=_headers("tenant-A"))
    resp_b = client.post("/v1/skills", json=body, headers=_headers("tenant-B"))
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["tenant_id"] == "tenant-A"
    assert resp_b.json()["tenant_id"] == "tenant-B"


@pytest.mark.integration
def test_post_skills_research_posture_missing_idempotency_key_returns_400(
    client: TestClient, monkeypatch
) -> None:
    """Under research/prod posture, missing Idempotency-Key must be rejected."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    body = {
        "skill_id": "greet",
        "version": "1.0.0",
        "handler_ref": "myapp.skills.greet",
    }
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "idempotency" in data["message"].lower()


# ---------------------------------------------------------------------------
# POST /v1/memory/write — happy path
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_memory_write_happy_path_returns_200(client: TestClient) -> None:
    body = {
        "key": "session::summary",
        "value": "The user asked about weather.",
        "tier": "L0",
    }
    resp = client.post("/v1/memory/write", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["tenant_id"] == "tenant-A"
    assert data["key"] == "session::summary"
    assert data["tier"] == "L0"
    assert data["status"] == "written"


@pytest.mark.integration
def test_post_memory_write_response_contains_all_envelope_fields(
    client: TestClient,
) -> None:
    body = {"key": "k1", "value": "v1"}
    resp = client.post("/v1/memory/write", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "tenant_id" in data
    assert "tier" in data
    assert "key" in data
    assert "status" in data
    assert "idempotency_key" in data


@pytest.mark.integration
def test_post_memory_write_default_tier_is_l0(client: TestClient) -> None:
    """When tier is omitted the handler defaults to L0."""
    body = {"key": "auto-tier-key", "value": "some-value"}
    resp = client.post("/v1/memory/write", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["tier"] == "L0"


@pytest.mark.integration
def test_post_memory_write_all_valid_tiers_accepted(client: TestClient) -> None:
    for tier in ("L0", "L1", "L2", "L3"):
        body = {"key": f"k-{tier}", "value": "val", "tier": tier}
        resp = client.post("/v1/memory/write", json=body, headers=_headers())
        assert resp.status_code == 200, f"tier {tier} failed: {resp.text}"
        assert resp.json()["tier"] == tier


@pytest.mark.integration
def test_post_memory_write_idempotency_key_echoed_in_response(
    client: TestClient,
) -> None:
    body = {"key": "echo-key", "value": "echo-val", "tier": "L1"}
    idem_key = "idem-mem-001"
    resp = client.post(
        "/v1/memory/write",
        json=body,
        headers={**_headers(), "Idempotency-Key": idem_key},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["idempotency_key"] == idem_key


@pytest.mark.integration
def test_post_memory_write_without_idempotency_key_returns_200_dev_posture(
    client: TestClient, monkeypatch
) -> None:
    """Under dev posture, missing Idempotency-Key is allowed."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    body = {"key": "dev-key", "value": "dev-val"}
    resp = client.post("/v1/memory/write", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["idempotency_key"] == ""


# ---------------------------------------------------------------------------
# POST /v1/memory/write — validation errors
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_memory_write_missing_key_returns_400(client: TestClient) -> None:
    body = {"value": "some-value", "tier": "L0"}
    resp = client.post("/v1/memory/write", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "key" in data["message"]


@pytest.mark.integration
def test_post_memory_write_invalid_tier_returns_400(client: TestClient) -> None:
    body = {"key": "some-key", "value": "val", "tier": "L9"}
    resp = client.post("/v1/memory/write", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "tier" in data["message"].lower()


# ---------------------------------------------------------------------------
# POST /v1/memory/write — tenant scoping
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_memory_write_missing_tenant_header_returns_401(
    client: TestClient,
) -> None:
    body = {"key": "k1", "value": "v1"}
    resp = client.post("/v1/memory/write", json=body)  # no X-Tenant-Id
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
def test_post_memory_write_tenant_id_in_response_matches_header(
    client: TestClient,
) -> None:
    """tenant_id in response must reflect the X-Tenant-Id header (isolation)."""
    body = {"key": "iso-key", "value": "iso-val"}
    resp_a = client.post(
        "/v1/memory/write", json=body, headers=_headers("tenant-A")
    )
    resp_b = client.post(
        "/v1/memory/write", json=body, headers=_headers("tenant-B")
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["tenant_id"] == "tenant-A"
    assert resp_b.json()["tenant_id"] == "tenant-B"


@pytest.mark.integration
def test_post_memory_write_research_posture_missing_idempotency_key_returns_400(
    client: TestClient, monkeypatch
) -> None:
    """Under research/prod posture, missing Idempotency-Key must be rejected."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    body = {"key": "strict-key", "value": "strict-val"}
    resp = client.post("/v1/memory/write", json=body, headers=_headers())
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "ContractError"
    assert "idempotency" in data["message"].lower()
