"""Integration tests for POST /v1/artifacts write API (W10-M.2 / W27-L15).

Layer 2 — Integration: real ArtifactFacade + real route handlers wired via
build_app. Stub backend is used in place of the kernel so tests stay in the
default-offline profile (no network, no real LLM, no secrets).

R-AS-5: this file is the TDD evidence for the POST /v1/artifacts handler
added in routes_artifacts.py (tdd-red-sha: 326a0e1e).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_server.api import build_app
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.artifact_facade import ArtifactFacade
from agent_server.facade.event_facade import EventFacade
from agent_server.facade.run_facade import RunFacade


# ---------------------------------------------------------------------------
# Stub backend
# ---------------------------------------------------------------------------


class _StubArtifactBackend:
    """In-memory artifact backend that supports both read and write paths."""

    def __init__(self) -> None:
        self._artifacts: dict[str, dict[str, Any]] = {}

    # --- write path (POST /v1/artifacts) ---

    def register(
        self,
        *,
        tenant_id: str,
        run_id: str,
        artifact_type: str,
        content: Any,
        metadata: dict[str, Any],
    ) -> str:
        import uuid
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        self._artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "artifact_type": artifact_type,
            "content": content,
            "metadata": metadata,
            "created_at": "2026-05-01T00:00:00Z",
        }
        return artifact_id

    # --- read path (GET /v1/runs/{id}/artifacts, GET /v1/artifacts/{id}) ---

    def list_for_tenant(
        self, *, tenant_id: str, run_id: str = ""
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in self._artifacts.values():
            if rec["tenant_id"] != tenant_id:
                continue
            if run_id and rec.get("run_id") != run_id:
                continue
            out.append({k: v for k, v in rec.items() if k != "content"})
        return out

    def get(self, *, tenant_id: str, artifact_id: str) -> dict[str, Any]:
        rec = self._artifacts.get(artifact_id)
        if rec is None or rec["tenant_id"] != tenant_id:
            raise NotFoundError(
                "artifact not found",
                tenant_id=tenant_id,
                detail=artifact_id,
            )
        return dict(rec)

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "state": "done",
            "current_stage": None,
            "llm_fallback_count": 0,
            "finished_at": None,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend() -> _StubArtifactBackend:
    return _StubArtifactBackend()


@pytest.fixture()
def client(backend: _StubArtifactBackend) -> TestClient:
    run_facade = RunFacade(
        start_run=lambda **_: {
            "tenant_id": "t1",
            "run_id": "r1",
            "state": "queued",
            "current_stage": None,
            "started_at": None,
            "finished_at": None,
            "metadata": {},
            "llm_fallback_count": 0,
        },
        get_run=backend.get_run,
        signal_run=lambda **kw: backend.get_run(
            tenant_id=kw["tenant_id"], run_id=kw["run_id"]
        ),
    )
    event_facade = EventFacade(
        cancel_run=lambda **kw: backend.get_run(
            tenant_id=kw["tenant_id"], run_id=kw["run_id"]
        ),
        get_run=backend.get_run,
        iter_events=lambda **_: iter([]),
    )
    artifact_facade = ArtifactFacade(
        list_artifacts=backend.list_for_tenant,
        get_artifact=backend.get,
        register_artifact=backend.register,
    )
    app = build_app(
        run_facade=run_facade,
        event_facade=event_facade,
        artifact_facade=artifact_facade,
    )
    with TestClient(app) as c:
        yield c


def _headers(tenant: str = "t1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


# ---------------------------------------------------------------------------
# POST /v1/artifacts — happy path
# ---------------------------------------------------------------------------


def test_post_artifacts_returns_201(client: TestClient) -> None:
    """POST with a valid payload returns HTTP 201 and an artifact_id."""
    resp = client.post(
        "/v1/artifacts",
        json={
            "run_id": "r1",
            "artifact_type": "base",
            "content": "hello world",
            "metadata": {"key": "value"},
        },
        headers=_headers(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "artifact_id" in data
    assert data["artifact_id"].startswith("art_")
    assert "created_at" in data
    assert data["tenant_id"] == "t1"
    assert data["run_id"] == "r1"


# ---------------------------------------------------------------------------
# POST /v1/artifacts — validation errors
# ---------------------------------------------------------------------------


def test_post_artifacts_missing_run_id_returns_400(client: TestClient) -> None:
    """Omitting run_id returns HTTP 400."""
    resp = client.post(
        "/v1/artifacts",
        json={
            "artifact_type": "base",
            "content": "hello",
        },
        headers=_headers(),
    )
    assert resp.status_code == 400, resp.text
    assert "run_id" in resp.json().get("message", "").lower()


def test_post_artifacts_missing_type_returns_400(client: TestClient) -> None:
    """Omitting artifact_type returns HTTP 400."""
    resp = client.post(
        "/v1/artifacts",
        json={
            "run_id": "r1",
            "content": "hello",
        },
        headers=_headers(),
    )
    assert resp.status_code == 400, resp.text
    assert "artifact_type" in resp.json().get("message", "").lower()


def test_post_artifacts_missing_content_returns_400(client: TestClient) -> None:
    """Omitting content returns HTTP 400."""
    resp = client.post(
        "/v1/artifacts",
        json={
            "run_id": "r1",
            "artifact_type": "base",
        },
        headers=_headers(),
    )
    assert resp.status_code == 400, resp.text
    assert "content" in resp.json().get("message", "").lower()


def test_post_artifacts_missing_tenant_header_returns_401(
    client: TestClient,
) -> None:
    """Missing X-Tenant-Id header returns HTTP 401 (middleware gate)."""
    resp = client.post(
        "/v1/artifacts",
        json={"run_id": "r1", "artifact_type": "base", "content": "x"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/artifacts — persistence round-trip
# ---------------------------------------------------------------------------


def test_artifact_persisted_after_post(
    client: TestClient, backend: _StubArtifactBackend
) -> None:
    """After POST, GET /v1/runs/{id}/artifacts includes the new artifact."""
    resp = client.post(
        "/v1/artifacts",
        json={
            "run_id": "r1",
            "artifact_type": "base",
            "content": "test-content",
            "metadata": {"source": "test"},
        },
        headers=_headers(),
    )
    assert resp.status_code == 201, resp.text
    artifact_id = resp.json()["artifact_id"]

    # Verify via the list endpoint.
    list_resp = client.get("/v1/runs/r1/artifacts", headers=_headers())
    assert list_resp.status_code == 200, list_resp.text
    ids = [a["artifact_id"] for a in list_resp.json()["artifacts"]]
    assert artifact_id in ids
