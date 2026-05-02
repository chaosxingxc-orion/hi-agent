"""W31-N (N.10): idempotency middleware coverage for skills + memory + gates.

Verifies that ``IdempotencyMiddleware._DEFAULT_PREDICATES`` extends
beyond ``/v1/runs/**`` to also catch:

  - POST /v1/skills
  - POST /v1/memory/write
  - POST /v1/gates/{gate_id}/decide

When the middleware is wired (production bootstrap path), the same
``Idempotency-Key`` header replays a byte-identical response on retry.
A reused key with a different body yields 409.

These tests construct a real ASGI app (FastAPI + TestClient) with the
real middleware + real route handlers + a fresh on-disk
:class:`IdempotencyFacade`. No mocks on the subject under test.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from agent_server.api.middleware.idempotency import (
    IDEMPOTENCY_HEADER,
    _DEFAULT_PREDICATES,
    _is_gates_decide_mutation,
    _is_memory_write_mutation,
    _is_skills_mutation,
    register_idempotency_middleware,
)
from agent_server.api.middleware.tenant_context import TenantContextMiddleware
from agent_server.api.routes_gates import build_router as build_gates_router
from agent_server.api.routes_skills_memory import (
    build_router as build_skills_memory_router,
)
from agent_server.facade.idempotency_facade import IdempotencyFacade
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Predicate-level tests
# ---------------------------------------------------------------------------

def test_skills_predicate_matches_post() -> None:
    assert _is_skills_mutation("POST", "/v1/skills") is True
    assert _is_skills_mutation("PUT", "/v1/skills/foo") is True


def test_skills_predicate_ignores_get() -> None:
    assert _is_skills_mutation("GET", "/v1/skills") is False
    assert _is_skills_mutation("GET", "/v1/skills/bar") is False


def test_memory_write_predicate_matches_post() -> None:
    assert _is_memory_write_mutation("POST", "/v1/memory/write") is True


def test_memory_write_predicate_ignores_other_paths() -> None:
    assert _is_memory_write_mutation("POST", "/v1/memory") is False
    assert _is_memory_write_mutation("POST", "/v1/memory/read") is False
    assert _is_memory_write_mutation("GET", "/v1/memory/write") is False


def test_gates_decide_predicate_matches_post() -> None:
    assert _is_gates_decide_mutation("POST", "/v1/gates/abc/decide") is True
    assert _is_gates_decide_mutation("POST", "/v1/gates/foo/decide") is True


def test_gates_decide_predicate_ignores_get() -> None:
    assert _is_gates_decide_mutation("GET", "/v1/gates/abc/decide") is False


def test_default_predicates_include_all_new_predicates() -> None:
    assert _is_skills_mutation in _DEFAULT_PREDICATES
    assert _is_memory_write_mutation in _DEFAULT_PREDICATES
    assert _is_gates_decide_mutation in _DEFAULT_PREDICATES


# ---------------------------------------------------------------------------
# End-to-end middleware tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def skills_memory_app(tmp_path: Path) -> FastAPI:
    """Build an app with the idempotency middleware wired and skills/memory routers."""
    facade = IdempotencyFacade(db_path=tmp_path / "idem.db", is_strict=False)
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    register_idempotency_middleware(app, facade=facade, strict=False)
    app.include_router(build_skills_memory_router(idempotency_facade=facade))
    app.include_router(build_gates_router())
    return app


@pytest.fixture()
def client(skills_memory_app: FastAPI) -> TestClient:
    return TestClient(skills_memory_app)


def _headers(tenant: str = "tenant-A", *, idem_key: str | None = None) -> dict[str, str]:
    h = {"X-Tenant-Id": tenant}
    if idem_key:
        h[IDEMPOTENCY_HEADER] = idem_key
    return h


def test_skills_idempotency_replay_returns_same_response(client: TestClient) -> None:
    """W31-N N.10: same key + same body returns the cached response byte-identical."""
    body = {"skill_id": "greet", "version": "1.0.0", "handler_ref": "myapp.skills.greet"}
    headers = _headers(idem_key="idem-skill-replay")
    r1 = client.post("/v1/skills", json=body, headers=headers)
    r2 = client.post("/v1/skills", json=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r2.json() == r1.json(), "replay must be byte-identical"


def test_memory_write_idempotency_replay_returns_same_response(
    client: TestClient,
) -> None:
    body = {"key": "k1", "value": "v1", "tier": "L0"}
    headers = _headers(idem_key="idem-mem-replay")
    r1 = client.post("/v1/memory/write", json=body, headers=headers)
    r2 = client.post("/v1/memory/write", json=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r2.json() == r1.json()


def test_gates_idempotency_replay_returns_same_response(client: TestClient) -> None:
    body = {"run_id": "run-001", "decision": "approved"}
    headers = _headers(idem_key="idem-gate-replay")
    r1 = client.post("/v1/gates/g-1/decide", json=body, headers=headers)
    r2 = client.post("/v1/gates/g-1/decide", json=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    # Replay returns cached body. Note: decided_at is stamped by the
    # handler, but on replay the cached value is returned, so the two
    # responses MUST equal.
    assert r2.json() == r1.json()


def test_skills_idempotency_conflict_on_body_mismatch(client: TestClient) -> None:
    """W31-N N.10: same key + DIFFERENT body returns 409."""
    headers = _headers(idem_key="idem-skill-conflict")
    body_a = {"skill_id": "greet", "version": "1.0.0", "handler_ref": "myapp.skills.greet"}
    body_b = {"skill_id": "greet", "version": "2.0.0", "handler_ref": "myapp.skills.greet"}
    r1 = client.post("/v1/skills", json=body_a, headers=headers)
    r2 = client.post("/v1/skills", json=body_b, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"] == "ConflictError"


def test_memory_write_cross_tenant_isolation(client: TestClient) -> None:
    """W31-N N.10: same key in different tenants does NOT collide."""
    body = {"key": "k1", "value": "v1", "tier": "L0"}
    r_a = client.post(
        "/v1/memory/write",
        json=body,
        headers=_headers("tenant-A", idem_key="shared-key"),
    )
    r_b = client.post(
        "/v1/memory/write",
        json=body,
        headers=_headers("tenant-B", idem_key="shared-key"),
    )
    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text
    # Each tenant gets its own response.
    assert r_a.json()["tenant_id"] == "tenant-A"
    assert r_b.json()["tenant_id"] == "tenant-B"


def test_skills_no_idempotency_key_passes_through_under_dev(
    client: TestClient,
) -> None:
    """W31-N N.10: dev posture without idem-key still returns 200 (warning only)."""
    body = {"skill_id": "greet", "version": "1.0.0", "handler_ref": "myapp.skills.greet"}
    resp = client.post("/v1/skills", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
