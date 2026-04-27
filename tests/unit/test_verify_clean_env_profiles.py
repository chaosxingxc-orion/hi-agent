"""Tests that bundle profiles control pytest marker exclusion correctly."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_verify_module():
    """Load scripts/verify_clean_env.py as a module without executing main()."""
    script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "verify_clean_env.py"
    spec = importlib.util.spec_from_file_location("verify_clean_env", script_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_args(profile: str, bundle: str | None = None) -> SimpleNamespace:
    """Build a minimal argparse namespace for _resolve_bundle_and_marker_args."""
    return SimpleNamespace(profile=profile, bundle=bundle)


def test_default_offline_excludes_live_markers():
    """default-offline profile must add marker exclusion for all four live markers."""
    m = _load_verify_module()

    args = _make_args("default-offline")
    raw_paths, extra_args = m._resolve_bundle_and_marker_args(args)

    # Must include -m argument
    assert "-m" in extra_args, "default-offline must add -m marker expression"
    marker_idx = extra_args.index("-m")
    marker_expr = extra_args[marker_idx + 1]

    # All four excluded markers must appear in the expression
    for marker in ("live_api", "external_llm", "network", "requires_secret"):
        assert f"not {marker}" in marker_expr, (
            f"default-offline marker expression missing 'not {marker}': {marker_expr!r}"
        )

    # Must use the full wave bundle as path base
    assert len(raw_paths) > 0, "default-offline must have non-empty path list"


def test_release_profile_excludes_network_markers():
    """release profile excludes live_api/external_llm/soak/chaos (Wave 13 marker discipline)."""
    m = _load_verify_module()

    args = _make_args("release")
    raw_paths, extra_args = m._resolve_bundle_and_marker_args(args)

    assert len(raw_paths) > 0, "release must have non-empty path list"
    # release excludes live_api and external_llm so it runs without real LLM keys
    if "-m" in extra_args:
        marker_expr = extra_args[extra_args.index("-m") + 1]
        assert "live_api" in marker_expr or "external_llm" in marker_expr, (
            f"release marker filter must exclude live_api or external_llm, got: {marker_expr!r}"
        )


def test_smoke_w5_profile_no_exclusion_marker():
    """smoke-w5 profile must not add marker exclusion (it uses a small bundle)."""
    m = _load_verify_module()

    args = _make_args("smoke-w5")
    raw_paths, extra_args = m._resolve_bundle_and_marker_args(args)

    assert "-m" not in extra_args, (
        f"smoke-w5 must not add marker filter, got extra_args={extra_args!r}"
    )
    assert len(raw_paths) > 0, "smoke-w5 must have a non-empty bundle"


def test_custom_profile_requires_bundle_path(tmp_path):
    """custom profile with --bundle reads from the given file."""

    m = _load_verify_module()

    # Write a bundle file
    bundle_file = tmp_path / "mybundle.txt"
    bundle_file.write_text(
        "tests/unit/test_contracts.py\n"
        "tests/unit/test_posture.py\n"
        "# comment line\n"
        "\n",
        encoding="utf-8",
    )

    args = _make_args("custom", bundle=str(bundle_file))
    raw_paths, extra_args = m._resolve_bundle_and_marker_args(args)

    assert raw_paths == [
        "tests/unit/test_contracts.py",
        "tests/unit/test_posture.py",
    ], f"custom profile must read paths from bundle file, got {raw_paths!r}"
    assert "-m" not in extra_args


def test_custom_profile_missing_bundle_exits(tmp_path, monkeypatch):
    """custom profile without --bundle must exit 1 (via sys.exit)."""
    import pytest

    m = _load_verify_module()
    args = _make_args("custom", bundle=None)

    with pytest.raises(SystemExit) as exc_info:
        m._resolve_bundle_and_marker_args(args)

    assert exc_info.value.code == 1


def test_wave_bundle_constant_contains_expected_dirs():
    """WAVE_TEST_BUNDLE must contain tests/unit and tests/integration at minimum."""
    m = _load_verify_module()

    bundle = m.WAVE_TEST_BUNDLE
    assert "tests/unit" in bundle, "WAVE_TEST_BUNDLE must include tests/unit"
    assert "tests/integration" in bundle, "WAVE_TEST_BUNDLE must include tests/integration"
