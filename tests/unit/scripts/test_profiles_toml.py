"""Tests for the profile taxonomy defined in tests/profiles.toml."""
import tomllib
from pathlib import Path

import pytest

PROFILES_PATH = Path(__file__).resolve().parent.parent.parent / "profiles.toml"
REQUIRED_PROFILES = {
    "smoke",
    "default-offline",
    "release",
    "live_api",
    "prod_e2e",
    "soak",
    "chaos",
}
REQUIRED_FIELDS = {
    "targets",
    "excluded_markers",
    "timeout_seconds",
    "allows_real_network",
    "allows_real_llm",
    "allows_secrets",
}


@pytest.mark.skipif(
    not PROFILES_PATH.exists(),
    reason="profiles.toml not found",
    expiry_wave="Wave 16",
)
def test_all_required_profiles_present():
    with open(PROFILES_PATH, "rb") as f:
        data = tomllib.load(f)
    profiles = set(data.get("profiles", {}).keys())
    assert REQUIRED_PROFILES.issubset(profiles), (
        f"Missing profiles: {REQUIRED_PROFILES - profiles}"
    )


@pytest.mark.skipif(
    not PROFILES_PATH.exists(),
    reason="profiles.toml not found",
    expiry_wave="Wave 16",
)
def test_all_profiles_have_required_fields():
    with open(PROFILES_PATH, "rb") as f:
        data = tomllib.load(f)
    profiles = data.get("profiles", {})
    for name, p_def in profiles.items():
        missing = REQUIRED_FIELDS - set(p_def.keys())
        assert not missing, f"Profile '{name}' missing fields: {missing}"


@pytest.mark.skipif(
    not PROFILES_PATH.exists(),
    reason="profiles.toml not found",
    expiry_wave="Wave 16",
)
def test_default_offline_no_real_network():
    with open(PROFILES_PATH, "rb") as f:
        data = tomllib.load(f)
    p = data["profiles"]["default-offline"]
    assert p["allows_real_network"] is False
    assert p["allows_real_llm"] is False
    assert p["allows_secrets"] is False


@pytest.mark.skipif(
    not PROFILES_PATH.exists(),
    reason="profiles.toml not found",
    expiry_wave="Wave 16",
)
def test_smoke_no_real_network():
    with open(PROFILES_PATH, "rb") as f:
        data = tomllib.load(f)
    p = data["profiles"]["smoke"]
    assert p["allows_real_network"] is False
    assert p["allows_real_llm"] is False
    assert p["allows_secrets"] is False


@pytest.mark.skipif(
    not PROFILES_PATH.exists(),
    reason="profiles.toml not found",
    expiry_wave="Wave 16",
)
def test_targets_are_lists():
    with open(PROFILES_PATH, "rb") as f:
        data = tomllib.load(f)
    for name, p_def in data.get("profiles", {}).items():
        assert isinstance(p_def.get("targets"), list), (
            f"Profile '{name}': 'targets' must be a list"
        )
