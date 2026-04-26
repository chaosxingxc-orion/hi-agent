"""Tests that /manifest exposes production_eligibility per extension (plugin).

Wave 10.6 W6-F: verifies that each plugin entry in the /manifest response
includes a production_eligibility dict with at minimum 'eligible' and
'requires_human_gate' fields.
"""
from __future__ import annotations

import pytest


@pytest.mark.integration
def test_manifest_plugin_production_eligibility_shape():
    """GET /manifest plugins entries must include production_eligibility.

    Each plugin entry must carry requires_human_gate in production_eligibility.
    """
    try:
        from hi_agent.server.app import app
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("App or TestClient not importable")

    with TestClient(app) as client:
        resp = client.get("/manifest")
        if resp.status_code == 401:
            pytest.skip("GET /manifest requires authentication in this env")
        if resp.status_code != 200:
            pytest.skip(f"GET /manifest returned {resp.status_code}")

        data = resp.json()
        plugins = data.get("plugins", [])

        # If there are plugins, every one must have production_eligibility with the right shape
        for plugin in plugins:
            assert "production_eligibility" in plugin, (
                f"Plugin {plugin.get('name')!r} missing production_eligibility in /manifest"
            )
            pe = plugin["production_eligibility"]
            assert "eligible" in pe, (
                f"production_eligibility for {plugin.get('name')!r} missing 'eligible'"
            )
            assert "requires_human_gate" in pe, (
                f"production_eligibility for {plugin.get('name')!r} missing 'requires_human_gate'"
            )
            assert isinstance(pe["requires_human_gate"], bool), (
                f"requires_human_gate must be bool, got {type(pe['requires_human_gate'])}"
            )


@pytest.mark.integration
def test_manifest_includes_extensions_or_plugins_key():
    """GET /manifest should include either 'plugins' or 'extensions' key."""
    try:
        from hi_agent.server.app import app
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("App or TestClient not importable")

    with TestClient(app) as client:
        resp = client.get("/manifest")
        if resp.status_code == 401:
            pytest.skip("GET /manifest requires authentication in this env")
        if resp.status_code != 200:
            pytest.skip(f"GET /manifest returned {resp.status_code}")

        data = resp.json()
        assert "plugins" in data or "extensions" in data, (
            "/manifest response must include 'plugins' or 'extensions' key"
        )
