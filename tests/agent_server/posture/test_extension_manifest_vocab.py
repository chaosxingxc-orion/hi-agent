"""Unit tests: extension_manifest vocabulary does not include invalid 'strict' posture."""
from __future__ import annotations

from typing import ClassVar

import pytest
from hi_agent.config.posture import Posture
from hi_agent.contracts.extension_manifest import (
    _VALID_REQUIRED_POSTURES,
    ExtensionRegistry,
)


def test_valid_required_postures_excludes_strict():
    """'strict' must not be in _VALID_REQUIRED_POSTURES — it is not a Posture enum member."""
    assert "strict" not in _VALID_REQUIRED_POSTURES, (
        "'strict' is not a valid Posture enum value and must be removed from "
        "_VALID_REQUIRED_POSTURES to prevent vocabulary drift"
    )


def test_valid_required_postures_contains_canonical_members():
    """_VALID_REQUIRED_POSTURES must contain exactly the canonical values plus 'any'."""
    canonical = {p.value for p in Posture} | {"any"}
    assert canonical == _VALID_REQUIRED_POSTURES, (
        f"_VALID_REQUIRED_POSTURES {_VALID_REQUIRED_POSTURES!r} must equal "
        f"canonical Posture values + 'any': {canonical!r}"
    )


def test_register_rejects_strict_required_posture():
    """ExtensionRegistry.register() rejects a manifest with required_posture='strict'."""
    registry = ExtensionRegistry()

    class FakeManifest:
        name = "test-ext"
        version = "1.0.0"
        manifest_kind = "plugin"
        schema_version = 1
        posture_support: ClassVar[dict] = {"dev": True}
        required_posture = "strict"  # invalid value
        tenant_scope = "global"
        dangerous_capabilities: ClassVar[list] = []
        config_schema = None

        def to_manifest_dict(self):
            return {}

        def production_eligibility(self, posture):
            return (True, [])

    with pytest.raises(ValueError, match="invalid required_posture"):
        registry.register(FakeManifest(), posture=Posture.RESEARCH)
