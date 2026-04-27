"""Test that build_manifest returns all required spec §5 schema fields."""

REQUIRED_TOP_KEYS = {
    "manifest_id", "schema_version", "generated_at", "git",
    "wave", "gates", "scorecard", "t3", "clean_env", "route_scope",
}
REQUIRED_SCORECARD_KEYS = {
    "raw_implementation_maturity", "current_verified_readiness",
    "conditional_readiness_after_blockers", "cap_reason", "cap_factors",
}


def test_manifest_schema_has_required_top_keys(monkeypatch, tmp_path):
    import scripts.build_release_manifest as brm
    from scripts.build_release_manifest import build_manifest
    monkeypatch.setattr(brm, "_GATE_SCRIPTS", {})
    monkeypatch.setattr(brm, "_load_weights", lambda: [])
    manifest, _ = build_manifest()
    for key in REQUIRED_TOP_KEYS:
        assert key in manifest, f"Missing key: {key}"


def test_manifest_scorecard_has_three_tiers(monkeypatch):
    import scripts.build_release_manifest as brm
    from scripts.build_release_manifest import build_manifest
    monkeypatch.setattr(brm, "_GATE_SCRIPTS", {})
    monkeypatch.setattr(brm, "_load_weights", lambda: [])
    manifest, _ = build_manifest()
    sc = manifest["scorecard"]
    for key in REQUIRED_SCORECARD_KEYS:
        assert key in sc, f"Scorecard missing: {key}"
