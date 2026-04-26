"""Unit tests — ExtensionRegistry.enable() fail-closed gate.

Wave 10.5 W5-F: enable() must call production_eligibility() and raise
ExtensionDisallowedError when the extension is blocked.

Layer 1 (Unit): no network or external I/O.
"""

from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture
from hi_agent.contracts.extension_manifest import ExtensionDisallowedError, ExtensionRegistry
from hi_agent.plugin.manifest import PluginManifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(**overrides) -> PluginManifest:
    defaults = {"name": "gate-ext", "version": "1.0.0"}
    defaults.update(overrides)
    return PluginManifest(**defaults)


def _register_and_enable(
    reg: ExtensionRegistry,
    pm: PluginManifest,
    posture: Posture,
) -> None:
    """Helper: register then enable."""
    reg.register(pm, Posture.DEV)  # always register under dev to avoid field rejection
    reg.enable(pm.name, pm.version, posture)


# ---------------------------------------------------------------------------
# is_enabled state
# ---------------------------------------------------------------------------


def test_is_enabled_returns_false_before_enable():
    """is_enabled() returns False before enable() is called."""
    reg = ExtensionRegistry()
    pm = _make_manifest()
    reg.register(pm, Posture.DEV)
    assert reg.is_enabled(pm.name, pm.version) is False


def test_is_enabled_returns_true_after_enable():
    """is_enabled() returns True after a successful enable() call."""
    reg = ExtensionRegistry()
    pm = _make_manifest()
    _register_and_enable(reg, pm, Posture.DEV)
    assert reg.is_enabled(pm.name, pm.version) is True


def test_is_enabled_unregistered_extension_returns_false():
    """is_enabled() on a non-existent extension returns False (no KeyError)."""
    reg = ExtensionRegistry()
    assert reg.is_enabled("nonexistent", "9.9.9") is False


# ---------------------------------------------------------------------------
# enable() on unregistered extension
# ---------------------------------------------------------------------------


def test_enable_unregistered_raises_key_error():
    """enable() on a non-registered extension raises KeyError."""
    reg = ExtensionRegistry()
    with pytest.raises(KeyError, match="not registered"):
        reg.enable("missing-ext", "1.0.0", Posture.DEV)


# ---------------------------------------------------------------------------
# Blocked by required_posture under dev
# ---------------------------------------------------------------------------


def test_enable_research_required_under_dev_raises_extension_disallowed():
    """Extension with required_posture='research' is blocked under dev posture."""
    reg = ExtensionRegistry()
    pm = _make_manifest(required_posture="research")
    reg.register(pm, Posture.DEV)
    with pytest.raises(ExtensionDisallowedError):
        reg.enable(pm.name, pm.version, Posture.DEV)


def test_enable_prod_required_under_dev_raises_extension_disallowed():
    """Extension with required_posture='prod' is blocked under dev posture."""
    reg = ExtensionRegistry()
    pm = _make_manifest(required_posture="prod")
    reg.register(pm, Posture.DEV)
    with pytest.raises(ExtensionDisallowedError):
        reg.enable(pm.name, pm.version, Posture.DEV)


def test_enable_research_required_under_research_succeeds():
    """Extension with required_posture='research' is allowed under research posture."""
    reg = ExtensionRegistry()
    pm = _make_manifest(required_posture="research")
    _register_and_enable(reg, pm, Posture.RESEARCH)
    assert reg.is_enabled(pm.name, pm.version) is True


def test_enable_prod_required_under_prod_succeeds():
    """Extension with required_posture='prod' is allowed under prod posture."""
    reg = ExtensionRegistry()
    pm = _make_manifest(required_posture="prod")
    _register_and_enable(reg, pm, Posture.PROD)
    assert reg.is_enabled(pm.name, pm.version) is True


# ---------------------------------------------------------------------------
# ExtensionDisallowedError exception
# ---------------------------------------------------------------------------


def test_extension_disallowed_has_reasons_attribute():
    """ExtensionDisallowedError must carry a non-empty reasons list."""
    reg = ExtensionRegistry()
    pm = _make_manifest(required_posture="prod")
    reg.register(pm, Posture.DEV)
    with pytest.raises(ExtensionDisallowedError) as exc_info:
        reg.enable(pm.name, pm.version, Posture.DEV)
    exc = exc_info.value
    assert hasattr(exc, "reasons")
    assert isinstance(exc.reasons, list)
    assert len(exc.reasons) >= 1


def test_extension_disallowed_reasons_describe_block():
    """ExtensionDisallowedError.reasons contains human-readable text."""
    exc = ExtensionDisallowedError("blocked", reasons=["reason A", "reason B"])
    assert exc.reasons == ["reason A", "reason B"]
    assert "blocked" in str(exc)


# ---------------------------------------------------------------------------
# Dangerous capabilities gate under strict posture
# ---------------------------------------------------------------------------


def test_enable_dangerous_no_schema_research_blocked():
    """Dangerous extension without config_schema blocked under research posture."""
    reg = ExtensionRegistry()
    pm = _make_manifest(
        dangerous_capabilities=["filesystem_write"],
        config_schema=None,
    )
    reg.register(pm, Posture.DEV)
    with pytest.raises(ExtensionDisallowedError):
        reg.enable(pm.name, pm.version, Posture.RESEARCH)


def test_enable_dangerous_with_schema_research_allowed():
    """Dangerous extension WITH config_schema is allowed under research posture."""
    reg = ExtensionRegistry()
    pm = _make_manifest(
        dangerous_capabilities=["filesystem_write"],
        config_schema={"type": "object"},
    )
    _register_and_enable(reg, pm, Posture.RESEARCH)
    assert reg.is_enabled(pm.name, pm.version) is True


# ---------------------------------------------------------------------------
# Double-enable is idempotent (no error)
# ---------------------------------------------------------------------------


def test_double_enable_is_idempotent():
    """Calling enable() twice on the same eligible extension does not raise."""
    reg = ExtensionRegistry()
    pm = _make_manifest()
    reg.register(pm, Posture.DEV)
    reg.enable(pm.name, pm.version, Posture.DEV)
    reg.enable(pm.name, pm.version, Posture.DEV)
    assert reg.is_enabled(pm.name, pm.version) is True
