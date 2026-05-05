"""Integration: GET /v1/manifest exposes the resolved platform posture.

W34 Track C (B-W34-5). The Research Intelligence App (RIA) consumes this
field per acceptance ID **R-RIA-6** (RIA refuses to start under prod
against a dev-posture platform). These tests assert that:

  1. ``HI_AGENT_POSTURE=dev`` -> response body contains ``"posture": "dev"``.
  2. ``HI_AGENT_POSTURE=research`` -> ``"posture": "research"``.
  3. ``HI_AGENT_POSTURE=prod`` -> ``"posture": "prod"``.
  4. ``HI_AGENT_POSTURE=garbage`` -> facade falls back to ``"dev"`` (the
     manifest path tolerates an invalid env value rather than 500-ing
     because the manifest is the diagnostic surface RIA polls during
     start-up).

Layer 2 — Integration: real :func:`agent_server.api.build_app` with the
v1 middleware stack and a real :class:`ManifestFacade` constructed with
its default env-reading resolver. Stub run/event/artifact facades are
acceptable here because none of the endpoints under test depends on the
kernel — only the manifest path is exercised. Per Rule 4: zero mocks on
``ManifestFacade`` (the subsystem under test).
"""
from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest
from agent_server.api import build_app
from agent_server.facade.artifact_facade import ArtifactFacade
from agent_server.facade.event_facade import EventFacade
from agent_server.facade.manifest_facade import ManifestFacade
from agent_server.facade.run_facade import RunFacade
from fastapi.testclient import TestClient

# W33-C.4: the JWT auth middleware fails closed under research/prod.
# The three-posture matrix below MUST authenticate so the auth
# middleware does not 401 us before the manifest handler runs. We sign
# tokens with a fixed test secret and inject it via monkeypatch in each
# test so dev posture (which would otherwise pass through) shares the
# same code path as research/prod.
_JWT_SECRET = "test-secret-w34-track-c-manifest-posture-must-be-32-bytes-padding"
_JWT_AUDIENCE = "hi-agent"


def _make_bearer(tenant: str = "tenant-A") -> str:
    payload = {
        "sub": f"user-for-{tenant}",
        "tenant_id": tenant,
        "role": "read",
        "aud": _JWT_AUDIENCE,
        "exp": int(time.time()) + 3600,
    }
    token = pyjwt.encode(payload, _JWT_SECRET, algorithm="HS256")
    return f"Bearer {token}"


def _headers(tenant: str = "tenant-A") -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "Authorization": _make_bearer(tenant)}


# ---------------------------------------------------------------------------
# Stubs for the non-manifest facades — build_app needs run_facade at minimum.
# ---------------------------------------------------------------------------

def _stub_run() -> dict[str, Any]:
    return {
        "tenant_id": "t",
        "run_id": "r",
        "state": "queued",
        "current_stage": None,
        "started_at": None,
        "finished_at": None,
        "metadata": {},
        "llm_fallback_count": 0,
    }


def _build_client() -> TestClient:
    """Construct the v1 ASGI app with a real ManifestFacade."""
    run_facade = RunFacade(
        start_run=lambda **_: _stub_run(),
        get_run=lambda **_: _stub_run(),
        signal_run=lambda **_: _stub_run(),
    )
    event_facade = EventFacade(
        cancel_run=lambda **_: _stub_run(),
        get_run=lambda **_: _stub_run(),
        iter_events=lambda **_: iter([]),
    )
    artifact_facade = ArtifactFacade(
        list_artifacts=lambda **_: [],
        get_artifact=lambda **_: {},
    )
    # Real facade with its default env-reading resolver — that's the
    # subsystem under test for B-W34-5.
    manifest_facade = ManifestFacade()
    app = build_app(
        run_facade=run_facade,
        event_facade=event_facade,
        artifact_facade=artifact_facade,
        manifest_facade=manifest_facade,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# The three-posture matrix.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_value", ["dev", "research", "prod"])
def test_manifest_posture_field_reflects_env(
    monkeypatch: pytest.MonkeyPatch, posture_value: str
) -> None:
    """``HI_AGENT_POSTURE=<value>`` -> manifest reports ``posture: <value>``."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_value)
    monkeypatch.setenv("HI_AGENT_JWT_SECRET", _JWT_SECRET)

    client = _build_client()
    resp = client.get("/v1/manifest", headers=_headers())
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert "posture" in data, "manifest response missing 'posture' field"
    assert data["posture"] == posture_value


# ---------------------------------------------------------------------------
# Defensive fallback: a malformed env value does not 500 the manifest.
# ---------------------------------------------------------------------------

def test_posture_invalid_env_value_falls_back_to_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrecognised ``HI_AGENT_POSTURE`` value falls back to ``"dev"``.

    The manifest is the diagnostic surface RIA polls during start-up; a
    typo in the env var must not turn the surface into a 500. The
    facade catches ``ValueError`` from ``Posture.from_env`` and emits
    ``posture: "dev"`` so callers can still observe and react.

    We exercise this directly on :class:`ManifestFacade` rather than
    through the HTTP layer because a malformed env var also breaks the
    JWT middleware's posture lookup; the facade's own fallback is the
    contract under test for B-W34-5 / R-RIA-6.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "garbage")

    facade = ManifestFacade()
    body = facade.manifest()

    assert body.get("posture") == "dev"
    # Sanity: the rest of the response shape is unchanged.
    assert body["api_version"] == "v1"
    assert isinstance(body["capabilities"], list)
    assert body["posture_matrix_provenance"] == "hardcoded"
