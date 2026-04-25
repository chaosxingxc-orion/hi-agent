"""Integration tests for /manifest HTTP contract — H1 Hardening Track 3.

Covers:
- version field is a non-empty string matching semver or "dev"
- endpoints list is derived from the route table and includes "/manifest" itself
- at least one capability has a parameters key (via capabilities_with_params)
- hi_agent_global appears in profiles[] when the server is configured
"""

from __future__ import annotations

import re

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient backed by a real AgentServer in dev mode."""
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_manifest_version_is_semver_or_dev(test_client: TestClient) -> None:
    """version must be a non-empty string matching semver X.Y.Z or exactly 'dev'."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    version = resp.json().get("version", "")
    assert isinstance(version, str) and len(version) > 0, "version must be a non-empty string"
    assert version == "dev" or SEMVER_RE.match(version), (
        f"version {version!r} is neither 'dev' nor a semver string"
    )


def test_manifest_endpoints_contains_manifest_self_reference(test_client: TestClient) -> None:
    """endpoints list must include GET /manifest (self-reference, derived from route table)."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    endpoints = resp.json().get("endpoints", [])
    assert isinstance(endpoints, list), "endpoints must be a list"
    assert "GET /manifest" in endpoints, f"/manifest missing from endpoints list. Got: {endpoints}"


def test_manifest_endpoints_is_not_empty(test_client: TestClient) -> None:
    """endpoints list must be non-empty (route table has routes)."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    endpoints = resp.json().get("endpoints", [])
    assert len(endpoints) > 0, "endpoints list must not be empty"


def test_manifest_capabilities_with_params_field_present(test_client: TestClient) -> None:
    """capabilities_with_params field must be present and be a list."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert "capabilities_with_params" in body, (
        "capabilities_with_params field missing from manifest"
    )
    assert isinstance(body["capabilities_with_params"], list)


def test_manifest_at_least_one_capability_has_parameters_key(test_client: TestClient) -> None:
    """At least one entry in capabilities_with_params must have a 'parameters' key."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    items = resp.json().get("capabilities_with_params", [])
    if not items:
        pytest.skip("No capabilities registered in this environment — cannot assert parameters key")
    has_params = any("parameters" in item for item in items)
    assert has_params, (
        f"No entry in capabilities_with_params has a 'parameters' key. Got items: {items[:3]}"
    )


def test_manifest_hi_agent_global_in_profiles(test_client: TestClient) -> None:
    """hi_agent_global must appear in /manifest.profiles[] when the server is configured."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    profiles = resp.json().get("profiles", [])
    assert isinstance(profiles, list), "profiles must be a list"
    profile_ids = [p.get("profile_id") for p in profiles]
    assert "hi_agent_global" in profile_ids, (
        f"hi_agent_global not found in profiles. Got profile_ids: {profile_ids}"
    )


def test_manifest_profiles_items_have_required_shape(test_client: TestClient) -> None:
    """Every entry in profiles[] must have profile_id, display_name, stage_count, has_evaluator."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    profiles = resp.json().get("profiles", [])
    for p in profiles:
        assert "profile_id" in p, f"profile entry missing profile_id: {p}"
        assert "display_name" in p, f"profile entry missing display_name: {p}"
        assert "stage_count" in p, f"profile entry missing stage_count: {p}"
        assert "has_evaluator" in p, f"profile entry missing has_evaluator: {p}"


def test_manifest_endpoints_each_entry_has_method_and_path(test_client: TestClient) -> None:
    """Every endpoint entry must be in the form 'METHOD /path'."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    endpoints = resp.json().get("endpoints", [])
    for entry in endpoints:
        parts = entry.split(" ", 1)
        assert len(parts) == 2, f"endpoint entry does not have METHOD /path form: {entry!r}"
        method, path = parts
        assert method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}, (
            f"unrecognised HTTP method in endpoint: {entry!r}"
        )
        assert path.startswith("/"), f"path does not start with /: {entry!r}"
