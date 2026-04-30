"""Integration tests for /v1/manifest (W24 Track I-C).

These tests are the TDD-RED stage per R-AS-5. They drive the build of:
  - agent_server/api/routes_manifest.py
  - agent_server/facade/manifest_facade.py

Track D (per-capability matrix wiring) is now wired (commit 3809930). The
facade uses ``CapabilityRegistry.to_extension_manifest_dict()`` when
constructed with the live registry, and tags the response body with
``posture_matrix_provenance: descriptor`` accordingly. When constructed
with a hardcoded callable for tests, ``posture_matrix_provenance:
hardcoded`` is emitted instead.
"""
from __future__ import annotations

from typing import Any

import pytest
from agent_server.api import build_app
from agent_server.facade.artifact_facade import ArtifactFacade
from agent_server.facade.event_facade import EventFacade
from agent_server.facade.manifest_facade import ManifestFacade
from agent_server.facade.run_facade import RunFacade
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    run_facade = RunFacade(
        start_run=lambda **_: {
            "tenant_id": "t", "run_id": "r", "state": "queued",
            "current_stage": None, "started_at": None, "finished_at": None,
            "metadata": {}, "llm_fallback_count": 0,
        },
        get_run=lambda **_: {
            "tenant_id": "t", "run_id": "r", "state": "queued",
            "current_stage": None, "llm_fallback_count": 0, "finished_at": None,
        },
        signal_run=lambda **_: {
            "tenant_id": "t", "run_id": "r", "state": "queued",
            "current_stage": None, "llm_fallback_count": 0, "finished_at": None,
        },
    )
    event_facade = EventFacade(
        cancel_run=lambda **_: {
            "tenant_id": "t", "run_id": "r", "state": "cancelled",
            "current_stage": None, "llm_fallback_count": 0,
            "finished_at": "2026-04-30T00:00:00Z",
        },
        get_run=lambda **_: {
            "tenant_id": "t", "run_id": "r", "state": "queued",
            "current_stage": None, "llm_fallback_count": 0, "finished_at": None,
        },
        iter_events=lambda **_: iter([]),
    )
    artifact_facade = ArtifactFacade(
        list_artifacts=lambda **_: [],
        get_artifact=lambda **_: {},
    )
    manifest_facade = ManifestFacade()
    app = build_app(
        run_facade=run_facade,
        event_facade=event_facade,
        artifact_facade=artifact_facade,
        manifest_facade=manifest_facade,
    )
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"X-Tenant-Id": "tenant-A"}


def test_manifest_returns_200(client: TestClient) -> None:
    resp = client.get("/v1/manifest", headers=_headers())
    assert resp.status_code == 200


def test_manifest_includes_api_version(client: TestClient) -> None:
    resp = client.get("/v1/manifest", headers=_headers())
    data = resp.json()
    assert data["api_version"] == "v1"


def test_manifest_capabilities_is_list(client: TestClient) -> None:
    resp = client.get("/v1/manifest", headers=_headers())
    data = resp.json()
    caps: list[Any] = data["capabilities"]
    assert isinstance(caps, list)
    assert len(caps) >= 1
    for cap in caps:
        assert "name" in cap
        assert "postures" in cap
        # postures matrix maps {dev, research, prod} -> bool
        assert set(cap["postures"]).issuperset({"dev", "research", "prod"})


def test_manifest_provenance_is_hardcoded_when_track_d_absent(
    client: TestClient,
) -> None:
    """Track D not yet landed → provenance must be tagged hardcoded."""
    resp = client.get("/v1/manifest", headers=_headers())
    data = resp.json()
    assert data["posture_matrix_provenance"] == "hardcoded"


def test_manifest_missing_tenant_header_returns_401(client: TestClient) -> None:
    resp = client.get("/v1/manifest")
    assert resp.status_code == 401
