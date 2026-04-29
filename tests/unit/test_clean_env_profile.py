"""Verify that the three clean-env profiles define non-overlapping test scopes.

These are Layer-1 unit tests against the module-level constants in
scripts/verify_clean_env.py.  No subprocess is spawned; no external
dependencies are required.
"""

import pathlib
import sys

# Make the scripts/ directory importable without installing it as a package.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "scripts"))

import verify_clean_env as vce


def test_default_offline_excludes_integration():
    """default-offline must NOT include tests/integration."""
    paths = vce._DEFAULT_OFFLINE_PATHS
    assert not any("integration" in p for p in paths), (
        f"default-offline must not include tests/integration, got: {paths}"
    )


def test_default_offline_excludes_server():
    """default-offline must NOT include tests/server (slow)."""
    paths = vce._DEFAULT_OFFLINE_PATHS
    assert not any("server" in p for p in paths), (
        f"default-offline must not include tests/server, got: {paths}"
    )


def test_default_offline_excludes_runtime_adapter():
    """default-offline must NOT include tests/runtime_adapter (slow)."""
    paths = vce._DEFAULT_OFFLINE_PATHS
    assert not any("runtime_adapter" in p for p in paths), (
        f"default-offline must not include tests/runtime_adapter, got: {paths}"
    )


def test_default_offline_includes_unit():
    """default-offline must include tests/unit."""
    paths = vce._DEFAULT_OFFLINE_PATHS
    assert any("unit" in p for p in paths), (
        f"default-offline must include tests/unit, got: {paths}"
    )


def test_nightly_includes_e2e():
    """nightly profile must include tests/e2e."""
    paths = vce._NIGHTLY_PATHS
    assert any("e2e" in p for p in paths), (
        f"nightly must include tests/e2e, got: {paths}"
    )


def test_nightly_includes_perf():
    """nightly profile must include tests/perf."""
    paths = vce._NIGHTLY_PATHS
    assert any("perf" in p for p in paths), (
        f"nightly must include tests/perf, got: {paths}"
    )


def test_nightly_is_superset_of_wave_bundle():
    """nightly paths must contain all WAVE_TEST_BUNDLE paths."""
    for p in vce.WAVE_TEST_BUNDLE:
        assert p in vce._NIGHTLY_PATHS, (
            f"nightly missing WAVE_TEST_BUNDLE path: {p}"
        )


def test_release_uses_wave_bundle():
    """release profile resolves to WAVE_TEST_BUNDLE (verified via argparse simulation).

    The release profile excludes live_api, external_llm, soak, and chaos markers
    per tests/profiles.toml, so extra_args carries a -m marker expression.
    """
    import argparse

    ns = argparse.Namespace(profile="release", bundle=None)
    raw_paths, extra_args = vce._resolve_bundle_and_marker_args(ns)
    assert raw_paths == list(vce.WAVE_TEST_BUNDLE)
    # profiles.toml defines excluded_markers for release; extra_args carries -m expression.
    if extra_args:
        assert extra_args[0] == "-m"
        marker_expr = extra_args[1]
        for excluded in ("live_api", "external_llm", "soak", "chaos"):
            assert f"not {excluded}" in marker_expr, (
                f"release profile must exclude '{excluded}' marker, got: {marker_expr}"
            )
    else:
        # Fallback path (profiles.toml absent): no marker exclusions
        assert extra_args == []


def test_default_offline_applies_marker_exclusions():
    """default-offline must include -m marker expression in extra_args.

    The resolved paths come from profiles.toml when present (which may include
    additional paths like tests/agent_server/ added in W22-A4).  This test
    validates the marker-exclusion behaviour rather than the exact path list;
    exact path validation is covered by the per-property tests above.
    """
    import argparse

    ns = argparse.Namespace(profile="default-offline", bundle=None)
    raw_paths, extra_args = vce._resolve_bundle_and_marker_args(ns)
    # Must include the baseline unit path at minimum.
    assert any("unit" in p for p in raw_paths), (
        f"default-offline resolver must return at least tests/unit, got: {raw_paths}"
    )
    assert "-m" in extra_args
    marker_expr = extra_args[extra_args.index("-m") + 1]
    for marker in vce._OFFLINE_EXCLUDED_MARKERS:
        assert f"not {marker}" in marker_expr, (
            f"marker exclusion missing '{marker}' in: {marker_expr}"
        )


def test_nightly_resolver_returns_nightly_paths():
    """nightly profile resolves to _NIGHTLY_PATHS with no extra marker args."""
    import argparse

    ns = argparse.Namespace(profile="nightly", bundle=None)
    raw_paths, extra_args = vce._resolve_bundle_and_marker_args(ns)
    assert raw_paths == list(vce._NIGHTLY_PATHS)
    assert extra_args == []
