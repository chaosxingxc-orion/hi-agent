"""Integration tests for /v1/artifacts/* (W24 Track I-B).

These tests are the TDD-RED stage per R-AS-5. They drive the build of:
  - agent_server/api/routes_artifacts.py
  - agent_server/facade/artifact_facade.py

HD-4 closure: under research/prod posture, the facade must refuse to
surface artifacts whose stored ``tenant_id`` is empty (mapped to 404,
not "owned by everyone").
"""
from __future__ import annotations

from typing import Any

import pytest
from agent_server.api import build_app
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.artifact_facade import ArtifactFacade
from agent_server.facade.event_facade import EventFacade
from agent_server.facade.run_facade import RunFacade
from fastapi.testclient import TestClient


class _StubArtifactBackend:
    """In-memory artifact store keyed by artifact_id."""

    def __init__(self) -> None:
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.tampered: set[str] = set()

    def add(self, artifact_id: str, *, tenant_id: str, run_id: str = "",
            content: bytes = b"hello", content_hash: str = "") -> None:
        self.artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "content": content,
            "content_hash": content_hash or _sha256_hex(content),
            "kind": "blob",
            "created_at": "2026-04-30T00:00:00Z",
        }

    def list_for_tenant(
        self, *, tenant_id: str, run_id: str = ""
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for a in self.artifacts.values():
            if a["tenant_id"] != tenant_id:
                continue
            if run_id and a.get("run_id") != run_id:
                continue
            out.append({k: v for k, v in a.items() if k != "content"})
        return out

    def get(
        self, *, tenant_id: str, artifact_id: str
    ) -> dict[str, Any]:
        rec = self.artifacts.get(artifact_id)
        if rec is None or rec["tenant_id"] != tenant_id:
            raise NotFoundError(
                "artifact not found",
                tenant_id=tenant_id,
                detail=artifact_id,
            )
        return dict(rec)

    def get_tampered(
        self, *, tenant_id: str, artifact_id: str
    ) -> dict[str, Any]:
        """Variant: simulates a content/hash mismatch by mutating content."""
        rec = self.get(tenant_id=tenant_id, artifact_id=artifact_id)
        if artifact_id in self.tampered:
            return {**rec, "content": rec["content"] + b"!"}
        return rec

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "state": "done",
            "current_stage": None,
            "llm_fallback_count": 0,
            "finished_at": None,
        }


def _sha256_hex(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def backend() -> _StubArtifactBackend:
    return _StubArtifactBackend()


@pytest.fixture()
def client_factory(backend: _StubArtifactBackend, monkeypatch):
    """Build a TestClient with the given posture environment."""
    created_clients: list[TestClient] = []

    def _make(*, posture: str = "dev", tampered: bool = False) -> TestClient:
        monkeypatch.setenv("HI_AGENT_POSTURE", posture)
        run_facade = RunFacade(
            start_run=lambda **_: {
                "tenant_id": "tenant-A", "run_id": "r1", "state": "queued",
                "current_stage": None, "started_at": None, "finished_at": None,
                "metadata": {}, "llm_fallback_count": 0,
            },
            get_run=backend.get_run,
            signal_run=lambda **kw: backend.get_run(
                tenant_id=kw["tenant_id"], run_id=kw["run_id"],
            ),
        )
        # event_facade required by build_app even when not exercised
        event_facade = EventFacade(
            cancel_run=lambda **kw: backend.get_run(
                tenant_id=kw["tenant_id"], run_id=kw["run_id"],
            ),
            get_run=backend.get_run,
            iter_events=lambda **_: iter([]),
        )
        get_callable = backend.get_tampered if tampered else backend.get
        artifact_facade = ArtifactFacade(
            list_artifacts=backend.list_for_tenant,
            get_artifact=get_callable,
        )
        app = build_app(
            run_facade=run_facade,
            event_facade=event_facade,
            artifact_facade=artifact_facade,
        )
        c = TestClient(app)
        created_clients.append(c)
        return c

    yield _make

    for c in created_clients:
        c.close()


def _headers(tenant: str = "tenant-A") -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


# ---------------------------------------------------------------------------
# GET /v1/runs/{id}/artifacts
# ---------------------------------------------------------------------------


def test_list_artifacts_returns_only_my_tenant(
    client_factory, backend: _StubArtifactBackend
) -> None:
    backend.add("a-1", tenant_id="tenant-A", run_id="r1")
    backend.add("a-2", tenant_id="tenant-B", run_id="r1")
    client = client_factory(posture="dev")
    resp = client.get("/v1/runs/r1/artifacts", headers=_headers("tenant-A"))
    assert resp.status_code == 200
    data = resp.json()
    ids = sorted(a["artifact_id"] for a in data["artifacts"])
    assert ids == ["a-1"]


def test_list_artifacts_empty_returns_empty_list(client_factory) -> None:
    client = client_factory(posture="dev")
    resp = client.get("/v1/runs/r1/artifacts", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["artifacts"] == []


def test_list_artifacts_missing_tenant_header_returns_401(
    client_factory,
) -> None:
    client = client_factory(posture="dev")
    resp = client.get("/v1/runs/r1/artifacts")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/artifacts/{artifact_id}
# ---------------------------------------------------------------------------


def test_get_artifact_returns_metadata(
    client_factory, backend: _StubArtifactBackend
) -> None:
    backend.add("a-1", tenant_id="tenant-A", content=b"hi-world")
    client = client_factory(posture="dev")
    resp = client.get("/v1/artifacts/a-1", headers=_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact_id"] == "a-1"
    assert data["tenant_id"] == "tenant-A"
    assert data["content_hash"] == _sha256_hex(b"hi-world")


def test_get_artifact_unknown_returns_404(client_factory) -> None:
    client = client_factory(posture="dev")
    resp = client.get("/v1/artifacts/missing", headers=_headers())
    assert resp.status_code == 404
    assert resp.json()["error"] == "NotFoundError"


def test_get_artifact_cross_tenant_returns_404(
    client_factory, backend: _StubArtifactBackend
) -> None:
    backend.add("a-1", tenant_id="tenant-A")
    client = client_factory(posture="dev")
    resp = client.get("/v1/artifacts/a-1", headers=_headers("tenant-B"))
    assert resp.status_code == 404


def test_get_artifact_tamper_under_research_returns_409(
    client_factory, backend: _StubArtifactBackend
) -> None:
    backend.add("a-tamper", tenant_id="tenant-A", content=b"original")
    backend.tampered.add("a-tamper")
    client = client_factory(posture="research", tampered=True)
    resp = client.get("/v1/artifacts/a-tamper", headers=_headers())
    assert resp.status_code == 409
    assert "ArtifactIntegrity" in resp.json().get("error", "")


def test_get_artifact_empty_tenant_blocked_under_research_hd4(
    client_factory, backend: _StubArtifactBackend
) -> None:
    """HD-4 closure: under research/prod, an artifact with empty tenant_id
    must NOT be surfaced — 404, not "owned by everyone"."""
    backend.add("orphan", tenant_id="", content=b"data")
    client = client_factory(posture="research")
    # Even with a real tenant header, the orphan record must not surface.
    resp = client.get("/v1/artifacts/orphan", headers=_headers("tenant-A"))
    assert resp.status_code == 404
