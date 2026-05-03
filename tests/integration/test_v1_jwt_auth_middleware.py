"""W33-C.4: JWT auth middleware on agent_server v1 routes.

Before this fix, the agent_server v1 surface trusted the X-Tenant-Id
header alone — any caller could supply an arbitrary tenant string
under research/prod and the platform would honour it. This test
validates the new ``JWTAuthMiddleware``:

* under research posture, missing JWT yields 401
* under research posture, valid JWT passes through (200/201)
* under research posture, invalid signature yields 401
* under research posture, expired token yields 401
* under dev posture, missing JWT passes through (legacy back-compat)
"""
from __future__ import annotations

import time

import jwt as pyjwt
from fastapi.testclient import TestClient

_JWT_SECRET = "test-secret-w33-c4-must-be-32-bytes-or-more-padding"
_AUDIENCE = "hi-agent"


def _make_token(
    *,
    sub: str = "user-1",
    tenant_id: str = "tenant-1",
    role: str = "write",
    exp_offset_s: int = 3600,
    secret: str = _JWT_SECRET,
    audience: str = _AUDIENCE,
) -> str:
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "aud": audience,
        "exp": int(time.time()) + exp_offset_s,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _build_app(tmp_path):
    """Construct the production app afresh.

    We import inside the helper so each test sees the correct posture
    that monkeypatch has installed before this is called.
    """
    from agent_server.bootstrap import build_production_app

    return build_production_app(state_dir=tmp_path)


def test_missing_jwt_under_research_returns_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_JWT_SECRET", _JWT_SECRET)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path / "data"))
    # Ensure RIA-strict idempotency middleware isn't blocking us first.
    app = _build_app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/v1/runs",
        headers={"X-Tenant-Id": "tenant-1"},
        json={"profile_id": "p", "goal": "g", "project_id": "proj"},
    )
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body.get("error_category") == "auth", body
    assert "missing_jwt" in body.get("reason", ""), body


def test_valid_jwt_under_research_passes_through(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_JWT_SECRET", _JWT_SECRET)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path / "data"))
    app = _build_app(tmp_path)
    client = TestClient(app)
    token = _make_token()
    # Probe the health endpoint to confirm the auth layer accepts the token.
    # (POST /v1/runs requires the kernel to dispatch a real run, which the
    # production app will do; we verify auth-acceptance separately by
    # using a route that does not require kernel dispatch — health
    # itself is exempt, so we use GET /v1/runs/{id} on a missing id.)
    resp = client.get(
        "/v1/runs/nonexistent",
        headers={
            "X-Tenant-Id": "tenant-1",
            "Authorization": f"Bearer {token}",
        },
    )
    # 404 is the legitimate downstream answer; the key assertion is that
    # we did NOT short-circuit at 401 (which would mean auth blocked us).
    assert resp.status_code != 401, (
        f"Auth must accept a valid JWT; got {resp.status_code} {resp.text}"
    )


def test_invalid_signature_under_research_returns_401(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_JWT_SECRET", _JWT_SECRET)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path / "data"))
    app = _build_app(tmp_path)
    client = TestClient(app)
    # Sign with a different secret so signature verification fails.
    bad_token = _make_token(
        secret="totally-different-secret-also-padded-out-to-32-bytes"
    )
    resp = client.get(
        "/v1/runs/any",
        headers={
            "X-Tenant-Id": "tenant-1",
            "Authorization": f"Bearer {bad_token}",
        },
    )
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body.get("error_category") == "auth", body


def test_expired_jwt_under_research_returns_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_JWT_SECRET", _JWT_SECRET)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path / "data"))
    app = _build_app(tmp_path)
    client = TestClient(app)
    expired = _make_token(exp_offset_s=-60)
    resp = client.get(
        "/v1/runs/any",
        headers={
            "X-Tenant-Id": "tenant-1",
            "Authorization": f"Bearer {expired}",
        },
    )
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body.get("error_category") == "auth", body


def test_missing_jwt_under_dev_passes_through(monkeypatch, tmp_path) -> None:
    """Under dev posture the auth middleware MUST be a passthrough.

    Anything else would break the default-offline test profile.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.delenv("HI_AGENT_JWT_SECRET", raising=False)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path / "data"))
    app = _build_app(tmp_path)
    client = TestClient(app)
    resp = client.get(
        "/v1/runs/any",
        headers={"X-Tenant-Id": "tenant-1"},
    )
    # Under dev with no token: must NOT be 401; downstream returns 404.
    assert resp.status_code != 401, (
        f"Dev posture must passthrough; got {resp.status_code} {resp.text}"
    )


def test_health_endpoint_is_exempt_from_auth(monkeypatch, tmp_path) -> None:
    """``/v1/health`` must remain reachable without a JWT."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_JWT_SECRET", _JWT_SECRET)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path / "data"))
    app = _build_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/v1/health", headers={"X-Tenant-Id": "tenant-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "ok", body
