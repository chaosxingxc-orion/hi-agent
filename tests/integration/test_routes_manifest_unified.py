"""Integration: GET /manifest includes unified 'extensions' array.

Layer 2 — Integration: real AgentServer + Starlette TestClient, no mocks on
the subsystem under test.  Verifies that:
  1. The 'extensions' key is present in the response.
  2. All existing keys remain unchanged (additive-only change).
  3. When an extension is registered, it appears in the response.
"""

from __future__ import annotations

import pytest
from hi_agent.contracts.extension_manifest import get_extension_registry
from hi_agent.plugins.manifest import PluginManifest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

_EXISTING_KEYS = {
    "name",
    "version",
    "capabilities",
    "capability_views",
    "mcp_servers",
    "endpoints",
    "profiles",
    "skills",
    "models",
    "plugins",
}


@pytest.fixture()
def test_client() -> TestClient:
    """Real AgentServer wrapped in a Starlette TestClient."""
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


def test_manifest_extensions_key_present(test_client: TestClient) -> None:
    """GET /manifest response must include 'extensions' as a list."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert "extensions" in data, "'extensions' key missing from /manifest response"
    assert isinstance(data["extensions"], list), "'extensions' must be a list"


def test_manifest_existing_keys_unchanged(test_client: TestClient) -> None:
    """Existing manifest keys must still be present after the additive change."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    data = resp.json()
    for key in _EXISTING_KEYS:
        assert key in data, f"Existing key {key!r} missing from /manifest after W4-B change"


def test_manifest_registered_extension_appears(test_client: TestClient) -> None:
    """An extension registered in the global registry appears in the response.

    We register a dev-posture plugin, then call GET /manifest (which defaults
    to dev posture via HI_AGENT_POSTURE=dev).  The response must include it.
    After the test we clean up to avoid leaking state to other tests.
    """
    registry = get_extension_registry()
    plugin = PluginManifest(
        name="__test_w4b_integration__",
        version="0.1",
        posture_support={"dev": True, "research": True, "prod": True},
    )
    registry.register(plugin)
    try:
        resp = test_client.get("/manifest")
        assert resp.status_code == 200
        data = resp.json()
        extensions = data.get("extensions", [])
        names = [e.get("name") for e in extensions]
        assert "__test_w4b_integration__" in names, (
            "Registered extension not found in /manifest extensions list"
        )
    finally:
        # Clean up: remove the test extension from the global registry.
        registry._registry.pop("__test_w4b_integration__", None)
