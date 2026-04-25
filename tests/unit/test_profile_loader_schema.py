"""Unit tests: jsonschema profile validation in load_profiles_from_dir().

CO-8: verifies that:
- Valid profiles load successfully under all postures.
- Invalid profiles (missing required fields) are skipped under dev posture.
- Invalid profiles raise ValueError under research/prod posture (fail-closed).
- The profile schema itself loads and is a valid schema dict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hi_agent.profiles.loader import load_profiles_from_dir
from hi_agent.profiles.registry import ProfileRegistry


def _make_registry() -> ProfileRegistry:
    return ProfileRegistry()


def _write_profile(directory: Path, filename: str, data: dict) -> None:
    (directory / filename).write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared valid/invalid fixtures
# ---------------------------------------------------------------------------

VALID_PROFILE = {
    "profile_id": "research_agent",
    "display_name": "Research Agent",
    "description": "A valid research profile.",
    "required_capabilities": ["web_search"],
    "stage_actions": {"S1_plan": "plan"},
    "config_overrides": {},
    "metadata": {},
}

INVALID_PROFILE_MISSING_DISPLAY_NAME = {
    "profile_id": "no_display",
    # "display_name" is required but omitted
}

INVALID_PROFILE_MISSING_PROFILE_ID = {
    "display_name": "Has display name but no profile_id",
}


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


def test_profile_schema_file_exists() -> None:
    """hi_agent/profiles/schema.json must exist and parse as a dict."""
    from hi_agent.profiles.loader import _get_profile_schema

    schema = _get_profile_schema()
    assert isinstance(schema, dict)
    assert "required" in schema
    assert "profile_id" in schema["required"]
    assert "display_name" in schema["required"]


# ---------------------------------------------------------------------------
# Dev posture: warn and skip invalid profiles
# ---------------------------------------------------------------------------


def test_dev_posture_valid_profile_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under dev posture, a valid profile must load successfully."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    _write_profile(tmp_path, "valid.json", VALID_PROFILE)
    registry = _make_registry()

    registered = load_profiles_from_dir(tmp_path, registry)
    assert "research_agent" in registered


def test_dev_posture_invalid_profile_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under dev posture, an invalid profile must be skipped (warn-and-skip)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    _write_profile(tmp_path, "invalid.json", INVALID_PROFILE_MISSING_DISPLAY_NAME)
    _write_profile(tmp_path, "valid.json", VALID_PROFILE)
    registry = _make_registry()

    registered = load_profiles_from_dir(tmp_path, registry)
    # The valid profile loads; the invalid one is silently skipped.
    assert "research_agent" in registered
    assert "no_display" not in registered


# ---------------------------------------------------------------------------
# Research/prod posture: fail-closed on invalid profiles
# ---------------------------------------------------------------------------


def test_research_posture_valid_profile_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under research posture, a valid profile must load successfully."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    _write_profile(tmp_path, "valid.json", VALID_PROFILE)
    registry = _make_registry()

    registered = load_profiles_from_dir(tmp_path, registry)
    assert "research_agent" in registered


def test_research_posture_invalid_profile_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under research posture, an invalid profile must raise ValueError (fail-closed)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    _write_profile(tmp_path, "invalid.json", INVALID_PROFILE_MISSING_DISPLAY_NAME)
    registry = _make_registry()

    with pytest.raises(ValueError, match="schema validation failed"):
        load_profiles_from_dir(tmp_path, registry)


def test_prod_posture_invalid_profile_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under prod posture, an invalid profile must raise ValueError (fail-closed)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    _write_profile(tmp_path, "invalid.json", INVALID_PROFILE_MISSING_PROFILE_ID)
    registry = _make_registry()

    with pytest.raises(ValueError, match="schema validation failed"):
        load_profiles_from_dir(tmp_path, registry)
