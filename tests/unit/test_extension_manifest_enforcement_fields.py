"""Unit tests — ExtensionManifest enforcement fields on concrete manifests.

Wave 10.5 W5-F: verify that PluginManifest has the 4 new enforcement fields
and that production_eligibility() works correctly.

Layer 1 (Unit): pure field + method checks; no network or external I/O.
"""

from __future__ import annotations

from hi_agent.config.posture import Posture
from hi_agent.contracts.extension_manifest import ExtensionManifestMixin
from hi_agent.plugins.manifest import PluginManifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin(**overrides) -> PluginManifest:
    """Return a minimal valid PluginManifest with optional field overrides."""
    defaults = {"name": "test-plugin", "version": "1.0.0"}
    defaults.update(overrides)
    return PluginManifest(**defaults)


# ---------------------------------------------------------------------------
# Field presence tests
# ---------------------------------------------------------------------------


def test_plugin_manifest_has_required_posture():
    """PluginManifest must have required_posture field with default 'any'."""
    pm = _make_plugin()
    assert hasattr(pm, "required_posture")
    assert pm.required_posture == "any"


def test_plugin_manifest_has_tenant_scope():
    """PluginManifest must have tenant_scope field with default 'tenant'."""
    pm = _make_plugin()
    assert hasattr(pm, "tenant_scope")
    assert pm.tenant_scope == "tenant"


def test_plugin_manifest_has_dangerous_capabilities():
    """PluginManifest must have dangerous_capabilities field defaulting to []."""
    pm = _make_plugin()
    assert hasattr(pm, "dangerous_capabilities")
    assert pm.dangerous_capabilities == []


def test_plugin_manifest_has_config_schema():
    """PluginManifest must have config_schema field defaulting to None."""
    pm = _make_plugin()
    assert hasattr(pm, "config_schema")
    assert pm.config_schema is None


def test_plugin_manifest_has_manifest_kind():
    """PluginManifest must have manifest_kind == 'plugin'."""
    pm = _make_plugin()
    assert pm.manifest_kind == "plugin"


def test_plugin_manifest_has_schema_version():
    """PluginManifest must have schema_version field."""
    pm = _make_plugin()
    assert isinstance(pm.schema_version, int)
    assert pm.schema_version >= 1


def test_plugin_manifest_has_posture_support():
    """PluginManifest must have non-empty posture_support."""
    pm = _make_plugin()
    assert pm.posture_support
    assert "dev" in pm.posture_support


# ---------------------------------------------------------------------------
# production_eligibility — eligible cases
# ---------------------------------------------------------------------------


def test_production_eligibility_any_posture_dev():
    """Extension with required_posture='any' is eligible under dev posture."""
    pm = _make_plugin(required_posture="any")
    eligible, reasons = pm.production_eligibility(Posture.DEV)
    assert eligible is True
    assert reasons == []


def test_production_eligibility_any_posture_research():
    """Extension with required_posture='any' is eligible under research posture."""
    pm = _make_plugin(required_posture="any")
    eligible, reasons = pm.production_eligibility(Posture.RESEARCH)
    assert eligible is True
    assert reasons == []


def test_production_eligibility_research_required_under_research():
    """Extension with required_posture='research' is eligible under research posture."""
    pm = _make_plugin(required_posture="research")
    eligible, reasons = pm.production_eligibility(Posture.RESEARCH)
    assert eligible is True
    assert reasons == []


def test_production_eligibility_prod_required_under_prod():
    """Extension with required_posture='prod' is eligible under prod posture."""
    pm = _make_plugin(required_posture="prod")
    eligible, reasons = pm.production_eligibility(Posture.PROD)
    assert eligible is True
    assert reasons == []


# ---------------------------------------------------------------------------
# production_eligibility — blocked cases
# ---------------------------------------------------------------------------


def test_production_eligibility_prod_required_under_dev_blocked():
    """Extension with required_posture='prod' is blocked under dev posture."""
    pm = _make_plugin(required_posture="prod")
    eligible, reasons = pm.production_eligibility(Posture.DEV)
    assert eligible is False
    assert len(reasons) >= 1
    assert any("prod" in r for r in reasons)


def test_production_eligibility_research_required_under_dev_blocked():
    """Extension with required_posture='research' is blocked under dev posture."""
    pm = _make_plugin(required_posture="research")
    eligible, reasons = pm.production_eligibility(Posture.DEV)
    assert eligible is False
    assert len(reasons) >= 1
    assert any("research" in r for r in reasons)


def test_production_eligibility_dangerous_no_schema_strict_blocked():
    """Dangerous extension without config_schema is blocked under strict posture."""
    pm = _make_plugin(
        dangerous_capabilities=["filesystem_write"],
        config_schema=None,
    )
    eligible, reasons = pm.production_eligibility(Posture.RESEARCH)
    assert eligible is False
    assert len(reasons) >= 1
    assert any("dangerous" in r.lower() or "config_schema" in r for r in reasons)


def test_production_eligibility_dangerous_with_schema_strict_eligible():
    """Dangerous extension WITH config_schema is eligible under strict posture."""
    pm = _make_plugin(
        dangerous_capabilities=["filesystem_write"],
        config_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    eligible, reasons = pm.production_eligibility(Posture.RESEARCH)
    assert eligible is True
    assert reasons == []


# ---------------------------------------------------------------------------
# Mixin inheritance
# ---------------------------------------------------------------------------


def test_plugin_manifest_inherits_extension_manifest_mixin():
    """PluginManifest must inherit from ExtensionManifestMixin."""
    assert issubclass(PluginManifest, ExtensionManifestMixin)


def test_to_manifest_dict_includes_enforcement_fields():
    """to_manifest_dict() must include all 4 enforcement fields."""
    pm = _make_plugin(
        required_posture="research",
        tenant_scope="global",
        dangerous_capabilities=["network_egress"],
        config_schema={"type": "object"},
    )
    d = pm.to_manifest_dict()
    assert d["required_posture"] == "research"
    assert d["tenant_scope"] == "global"
    assert d["dangerous_capabilities"] == ["network_egress"]
    assert d["config_schema"] == {"type": "object"}
    assert d["manifest_kind"] == "plugin"
    assert "schema_version" in d
