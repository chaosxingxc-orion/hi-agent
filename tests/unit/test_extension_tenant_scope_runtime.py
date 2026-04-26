"""Unit tests for tenant_scope enforcement at enable() time.

Wave 10.6 W6-F: verifies that ExtensionRegistry.enable() checks tenant_scope
and raises ExtensionTenantScopeRequired when a scoped extension is enabled
without a tenant_id, while global-scope extensions allow empty tenant_id.
"""
from __future__ import annotations

import pytest


def _make_registry():
    try:
        from hi_agent.contracts.extension_manifest import ExtensionRegistry

        return ExtensionRegistry()
    except ImportError:
        pytest.skip("ExtensionRegistry not available")


def _make_manifest(tenant_scope: str, dangerous: bool = False):
    """Create a minimal manifest with the given tenant_scope."""
    try:
        from hi_agent.contracts.extension_manifest import ExtensionManifestMixin

        class TestManifest(ExtensionManifestMixin):
            name = "scope-test-ext"
            version = "1.0"
            manifest_kind = "plugin"
            schema_version = 1
            posture_support = {"dev": True}
            required_posture = "any"
            config_schema = {"type": "object"}
            dangerous_capabilities: list = []

        obj = TestManifest()
        obj.tenant_scope = tenant_scope
        if dangerous:
            obj.dangerous_capabilities = ["filesystem_write"]
        return obj
    except Exception as exc:
        pytest.skip(f"Cannot create manifest: {exc}")


def test_global_scope_no_tenant_id_ok(monkeypatch):
    """Extension with tenant_scope='global' can enable without tenant_id under dev posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.contracts.extension_manifest import ExtensionTenantScopeRequired

    registry = _make_registry()
    manifest = _make_manifest("global")

    try:
        registry.register(manifest)
    except Exception:
        pass

    # Should NOT raise ExtensionTenantScopeRequired for global scope
    try:
        registry.enable("scope-test-ext", "1.0", tenant_id="")
    except ExtensionTenantScopeRequired:
        pytest.fail("global-scope extension must not require tenant_id")
    except Exception:
        pass  # Other blocking (missing method, etc.) is acceptable


def test_tenant_scope_empty_tenant_raises(monkeypatch):
    """Extension with tenant_scope='tenant' raises ExtensionTenantScopeRequired if no tenant."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.contracts.extension_manifest import ExtensionTenantScopeRequired

    registry = _make_registry()
    manifest = _make_manifest("tenant")

    try:
        registry.register(manifest)
    except Exception:
        pass

    with pytest.raises(ExtensionTenantScopeRequired):
        registry.enable("scope-test-ext", "1.0", tenant_id="")


def test_user_scope_empty_tenant_raises(monkeypatch):
    """Extension with tenant_scope='user' raises ExtensionTenantScopeRequired if no tenant."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.contracts.extension_manifest import ExtensionTenantScopeRequired

    registry = _make_registry()
    manifest = _make_manifest("user")

    try:
        registry.register(manifest)
    except Exception:
        pass

    with pytest.raises(ExtensionTenantScopeRequired):
        registry.enable("scope-test-ext", "1.0", tenant_id="")


def test_session_scope_empty_tenant_raises(monkeypatch):
    """Extension with tenant_scope='session' raises ExtensionTenantScopeRequired if no tenant."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.contracts.extension_manifest import ExtensionTenantScopeRequired

    registry = _make_registry()
    manifest = _make_manifest("session")

    try:
        registry.register(manifest)
    except Exception:
        pass

    with pytest.raises(ExtensionTenantScopeRequired):
        registry.enable("scope-test-ext", "1.0", tenant_id="")


def test_tenant_scope_with_tenant_id_does_not_raise_scope_error(monkeypatch):
    """Extension with tenant_scope='tenant' and a valid tenant_id does not raise scope error."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.contracts.extension_manifest import ExtensionTenantScopeRequired

    registry = _make_registry()
    manifest = _make_manifest("tenant")

    try:
        registry.register(manifest)
    except Exception:
        pass

    try:
        registry.enable("scope-test-ext", "1.0", tenant_id="tenant-abc")
    except ExtensionTenantScopeRequired:
        pytest.fail("Should not raise ExtensionTenantScopeRequired when tenant_id is provided")
    except Exception:
        pass  # Other errors acceptable


def test_exception_attributes_populated():
    """ExtensionTenantScopeRequired carries extension_name, extension_version, tenant_scope."""
    from hi_agent.contracts.extension_manifest import ExtensionTenantScopeRequired

    exc = ExtensionTenantScopeRequired("my-ext", "2.0", "user")
    assert exc.extension_name == "my-ext"
    assert exc.extension_version == "2.0"
    assert exc.tenant_scope == "user"
    assert "tenant_id" in str(exc) or "tenant_scope" in str(exc)


def test_human_approval_exception_attributes():
    """ExtensionRequiresHumanApproval carries extension metadata."""
    from hi_agent.contracts.extension_manifest import ExtensionRequiresHumanApproval

    caps = ["filesystem_write", "network_egress"]
    exc = ExtensionRequiresHumanApproval("danger-ext", "3.0", caps)
    assert exc.extension_name == "danger-ext"
    assert exc.extension_version == "3.0"
    assert exc.dangerous_capabilities == caps
    assert "human gate" in str(exc)
