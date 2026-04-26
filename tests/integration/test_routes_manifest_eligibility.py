"""Integration tests — /manifest endpoint includes production_eligibility per extension.

Wave 10.5 W5-F: when plugins are listed in the /manifest response, each plugin
entry must carry a production_eligibility dict with an 'eligible' boolean field.

Layer 2 (Integration): tests the routes_manifest response structure.
Zero mocks on the subsystem under test (routes_manifest logic).
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


@pytest.fixture()
def _app_with_plugin_loader(monkeypatch):
    """Build a minimal Starlette app that wires routes_manifest and injects
    a plugin loader with at least one loaded manifest.
    """
    import hi_agent.server.routes_manifest as _routes_manifest
    from hi_agent.plugins.loader import PluginLoader
    from hi_agent.plugins.manifest import PluginManifest
    from hi_agent.server.routes_manifest import handle_manifest

    # Patch require_tenant_context in the routes_manifest module namespace to
    # avoid 401 in the test environment.
    monkeypatch.setattr(_routes_manifest, "require_tenant_context", lambda: None)

    # Build a plugin loader with one synthetic manifest already loaded.
    pm = PluginManifest(
        name="test-plugin",
        version="1.0.0",
        description="Test plugin for eligibility check",
    )
    loader = PluginLoader(plugin_dirs=[])
    loader._loaded["test-plugin"] = pm  # inject directly

    class _FakeBuilder:
        _plugin_loader = loader

        def build_invoker(self):
            return None

        def build_skill_loader(self):
            return None

        def build_profile_registry(self):
            return None

        def readiness(self):
            return {}

    class _FakeServer:
        """Minimal server stub for the handle_manifest handler."""

        def __init__(self) -> None:
            self._builder = _FakeBuilder()
            self.mcp_server = None
            self.stage_graph = None

    fake_server = _FakeServer()

    app = Starlette(routes=[Route("/manifest", handle_manifest, methods=["GET"])])
    app.state.agent_server = fake_server

    return app


def test_manifest_plugins_have_production_eligibility(_app_with_plugin_loader):
    """Each plugin entry in /manifest must have a production_eligibility field."""
    with TestClient(_app_with_plugin_loader) as client:
        response = client.get("/manifest")
    assert response.status_code == 200
    data = response.json()
    plugins = data.get("plugins", [])
    # If plugins are listed, each must carry production_eligibility.
    for plugin in plugins:
        assert "production_eligibility" in plugin, (
            f"Plugin {plugin.get('name')!r} missing 'production_eligibility' key"
        )
        pe = plugin["production_eligibility"]
        assert "eligible" in pe, (
            f"Plugin {plugin.get('name')!r} production_eligibility missing 'eligible'"
        )
        assert isinstance(pe["eligible"], bool)
        assert "blocked_reasons" in pe


def test_manifest_endpoint_returns_200(_app_with_plugin_loader):
    """Baseline: /manifest endpoint responds with 200 OK."""
    with TestClient(_app_with_plugin_loader) as client:
        response = client.get("/manifest")
    assert response.status_code == 200
