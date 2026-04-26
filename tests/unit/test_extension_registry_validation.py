"""Unit tests — ExtensionRegistry.register() validation paths.

Wave 10.5 W5-F: every reject path in ExtensionRegistry.register() must raise ValueError.

Layer 1 (Unit): no network or external I/O; uses PluginManifest as a concrete manifest.
"""

from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture
from hi_agent.contracts.extension_manifest import ExtensionRegistry
from hi_agent.plugin.manifest import PluginManifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(**overrides) -> PluginManifest:
    """Return a minimal valid PluginManifest."""
    defaults = {"name": "ext-a", "version": "1.0.0"}
    defaults.update(overrides)
    return PluginManifest(**defaults)


def _make_registry() -> ExtensionRegistry:
    return ExtensionRegistry()


# ---------------------------------------------------------------------------
# Valid registration
# ---------------------------------------------------------------------------


def test_register_valid_manifest_succeeds():
    """A valid manifest with all required fields registers without error."""
    reg = _make_registry()
    pm = _make_manifest()
    reg.register(pm, Posture.DEV)
    assert len(reg) == 1


def test_register_returns_none():
    """register() returns None (not the manifest)."""
    reg = _make_registry()
    result = reg.register(_make_manifest(), Posture.DEV)
    assert result is None


def test_list_manifests_after_register():
    """list_manifests() returns the registered manifest."""
    reg = _make_registry()
    pm = _make_manifest()
    reg.register(pm, Posture.DEV)
    assert pm in reg.list_manifests()


def test_get_manifest_after_register():
    """get() returns the manifest by name:version."""
    reg = _make_registry()
    pm = _make_manifest(name="ext-b", version="2.0.0")
    reg.register(pm, Posture.DEV)
    assert reg.get("ext-b", "2.0.0") is pm


# ---------------------------------------------------------------------------
# Invalid manifest_kind
# ---------------------------------------------------------------------------


def test_register_invalid_manifest_kind_raises_value_error():
    """Invalid manifest_kind raises ValueError."""
    reg = _make_registry()
    pm = _make_manifest(manifest_kind="unsupported_kind")
    with pytest.raises(ValueError, match="manifest_kind"):
        reg.register(pm, Posture.DEV)


def test_register_empty_manifest_kind_raises_value_error():
    """Empty manifest_kind raises ValueError."""
    reg = _make_registry()
    pm = _make_manifest(manifest_kind="")
    with pytest.raises(ValueError, match="manifest_kind"):
        reg.register(pm, Posture.DEV)


# ---------------------------------------------------------------------------
# Duplicate name:version
# ---------------------------------------------------------------------------


def test_register_duplicate_raises_value_error():
    """Registering the same name:version twice raises ValueError."""
    reg = _make_registry()
    pm = _make_manifest(name="dup-ext", version="1.0.0")
    reg.register(pm, Posture.DEV)
    pm2 = _make_manifest(name="dup-ext", version="1.0.0")
    with pytest.raises(ValueError, match="already registered"):
        reg.register(pm2, Posture.DEV)


def test_register_same_name_different_version_allowed():
    """Same name but different version is allowed."""
    reg = _make_registry()
    pm1 = _make_manifest(name="ext-c", version="1.0.0")
    pm2 = _make_manifest(name="ext-c", version="2.0.0")
    reg.register(pm1, Posture.DEV)
    reg.register(pm2, Posture.DEV)
    assert len(reg) == 2


# ---------------------------------------------------------------------------
# Empty posture_support
# ---------------------------------------------------------------------------


def test_register_empty_posture_support_raises_value_error():
    """Empty posture_support dict raises ValueError."""
    reg = _make_registry()
    pm = _make_manifest(posture_support={})
    with pytest.raises(ValueError, match="posture_support"):
        reg.register(pm, Posture.DEV)


# ---------------------------------------------------------------------------
# Missing enforcement fields under strict posture
# ---------------------------------------------------------------------------


def test_register_invalid_required_posture_value_strict_raises_value_error():
    """Under research posture, a manifest with an invalid required_posture raises ValueError."""
    reg = _make_registry()
    pm = _make_manifest(required_posture="unsupported_posture")
    with pytest.raises(ValueError, match="required_posture"):
        reg.register(pm, Posture.RESEARCH)


def test_register_invalid_required_posture_value_dev_warns_not_raises():
    """Under dev posture, an invalid required_posture logs a warning but succeeds."""
    reg = _make_registry()
    pm = _make_manifest(required_posture="unsupported_posture")
    # Should not raise under dev posture — issues are warned but allowed.
    reg.register(pm, Posture.DEV)
    assert len(reg) == 1


# ---------------------------------------------------------------------------
# Missing name/version
# ---------------------------------------------------------------------------


def test_register_empty_name_raises_value_error():
    """Empty name raises ValueError."""
    reg = _make_registry()
    pm = _make_manifest(name="")
    with pytest.raises(ValueError, match="name"):
        reg.register(pm, Posture.DEV)


def test_register_empty_version_raises_value_error():
    """Empty version raises ValueError."""
    reg = _make_registry()
    pm = _make_manifest(version="")
    with pytest.raises(ValueError, match="version"):
        reg.register(pm, Posture.DEV)
