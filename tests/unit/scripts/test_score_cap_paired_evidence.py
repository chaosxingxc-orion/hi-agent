"""W31-L (W31-G1) tests for the score-cap paired-evidence rule.

The rule: when a cap_factor is RETIRED between the previous wave's manifest
and the current manifest, a paired ``provenance: real`` evidence artifact
must exist at ``docs/verification/<short-head>-<factor>.json``. Without
paired evidence, check_score_cap.py fails closed.

This blocks the W28 metric-redefinition pattern (verified=65 -> 94.55 with
no offsetting engineering evidence; soak cap retired without paired soak
evidence).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_manifest(
    dir_path: Path,
    *,
    sha: str,
    wave: str,
    cap_factors: list[str],
    generated_at: str,
    verified: float = 80.0,
) -> Path:
    """Helper: write a manifest file with the given cap_factors."""
    name = f"platform-release-manifest-2026-05-02-{sha}.json"
    payload = {
        "manifest_id": f"2026-05-02-{sha}",
        "release_head": sha + ("0" * (40 - len(sha))),
        "wave": wave,
        "generated_at": generated_at,
        "git": {
            "head_sha": sha + ("0" * (40 - len(sha))),
            "short_sha": sha,
            "is_dirty": False,
        },
        "scorecard": {
            "current_verified_readiness": verified,
            "verified": verified,
            "cap": verified if cap_factors else None,
            "cap_reason": ", ".join(cap_factors) if cap_factors else "all gates pass",
            "cap_factors": cap_factors,
        },
    }
    p = dir_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _write_paired_evidence(
    verif_dir: Path,
    *,
    sha_short: str,
    factor: str,
    provenance: str = "real",
) -> Path:
    verif_dir.mkdir(parents=True, exist_ok=True)
    out = verif_dir / f"{sha_short}-{factor}.json"
    payload = {
        "schema_version": "1",
        "check": factor,
        "provenance": provenance,
        "status": "pass",
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def test_no_previous_manifest_skips_check(tmp_path):
    """When no previous-wave manifest exists, the rule cannot fire."""
    import check_score_cap as mod

    current = {
        "wave": "31",
        "release_head": "abc123",
        "scorecard": {"cap_factors": []},
    }
    issues = mod._check_paired_evidence(
        previous_manifest=None,
        current_manifest=current,
        current_head="abc123",
    )
    assert issues == []


def test_no_factors_retired_passes(tmp_path):
    """Same factors in both waves -> no retirement -> rule passes."""
    import check_score_cap as mod

    prev = {"wave": "30", "scorecard": {"cap_factors": ["gate_fail"]}}
    cur = {"wave": "31", "scorecard": {"cap_factors": ["gate_fail"]}}
    issues = mod._check_paired_evidence(
        previous_manifest=prev,
        current_manifest=cur,
        current_head="abc123",
    )
    assert issues == []


def test_retirement_with_paired_real_evidence_passes(tmp_path, monkeypatch):
    """Cap retired AND paired real evidence at HEAD -> rule passes."""
    import check_score_cap as mod

    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    sha = "abcdef12"
    _write_paired_evidence(tmp_path, sha_short=sha, factor="soak_evidence", provenance="real")

    prev = {"wave": "30", "scorecard": {"cap_factors": ["soak_evidence"]}}
    cur = {"wave": "31", "scorecard": {"cap_factors": []}}
    issues = mod._check_paired_evidence(
        previous_manifest=prev,
        current_manifest=cur,
        current_head=sha + "0" * 32,
    )
    assert issues == [], f"Expected no issues, got {issues}"


def test_retirement_without_paired_evidence_fails(tmp_path, monkeypatch):
    """The W28 pattern: cap retired with no paired evidence -> rule fails."""
    import check_score_cap as mod

    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    # No paired evidence written.
    sha = "12345678"
    prev = {"wave": "30", "scorecard": {"cap_factors": ["soak_evidence"]}}
    cur = {"wave": "31", "scorecard": {"cap_factors": []}}
    issues = mod._check_paired_evidence(
        previous_manifest=prev,
        current_manifest=cur,
        current_head=sha + "0" * 32,
    )
    assert len(issues) == 1
    assert "unpaired_cap_retirement" in issues[0]
    assert "soak_evidence" in issues[0]
    # The reason MUST point to the missing path so the operator knows what to do.
    assert f"docs/verification/{sha}-soak_evidence.json" in issues[0]


def test_retirement_with_synthetic_provenance_fails(tmp_path, monkeypatch):
    """Paired evidence exists but provenance != real -> rule fails."""
    import check_score_cap as mod

    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    sha = "deadbeef"
    _write_paired_evidence(
        tmp_path, sha_short=sha, factor="soak_evidence", provenance="structural",
    )

    prev = {"wave": "30", "scorecard": {"cap_factors": ["soak_evidence"]}}
    cur = {"wave": "31", "scorecard": {"cap_factors": []}}
    issues = mod._check_paired_evidence(
        previous_manifest=prev,
        current_manifest=cur,
        current_head=sha + "0" * 32,
    )
    assert len(issues) == 1
    assert "provenance='structural'" in issues[0] or "provenance=\"structural\"" in issues[0]
    assert "required provenance:real" in issues[0]


def test_factor_with_descriptor_strips_correctly(tmp_path, monkeypatch):
    """Factors like 'foo: bar=baz' must be keyed by 'foo' for the filename."""
    import check_score_cap as mod

    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    sha = "feedbeef"
    # Paired evidence keyed by base factor name only.
    _write_paired_evidence(tmp_path, sha_short=sha, factor="soak_evidence", provenance="real")

    prev = {"wave": "30", "scorecard": {"cap_factors": ["soak_evidence: missing"]}}
    cur = {"wave": "31", "scorecard": {"cap_factors": []}}
    issues = mod._check_paired_evidence(
        previous_manifest=prev,
        current_manifest=cur,
        current_head=sha + "0" * 32,
    )
    assert issues == [], f"Expected no issues with stripped factor, got {issues}"


def test_factor_basename_helper():
    """_factor_basename strips trailing 'descriptor' tail."""
    import check_score_cap as mod

    assert mod._factor_basename("gate_fail") == "gate_fail"
    assert mod._factor_basename("gate_fail: details") == "gate_fail"
    assert mod._factor_basename("foo: bar: baz") == "foo"
    assert mod._factor_basename("  spaced  ") == "spaced"


def test_previous_wave_lookup_picks_max_smaller_wave(tmp_path, monkeypatch):
    """_previous_wave_manifest finds the latest manifest at strictly-smaller wave."""
    import check_score_cap as mod

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    _write_manifest(
        tmp_path, sha="aaa11111", wave="29", cap_factors=["gate_fail"],
        generated_at="2026-05-01T10:00:00+00:00",
    )
    _write_manifest(
        tmp_path, sha="bbb22222", wave="30", cap_factors=[],
        generated_at="2026-05-02T10:00:00+00:00",
    )
    _write_manifest(
        tmp_path, sha="ccc33333", wave="31", cap_factors=[],
        generated_at="2026-05-03T10:00:00+00:00",
    )
    current = {"wave": "31", "scorecard": {}}
    prev = mod._previous_wave_manifest(current)
    assert prev is not None
    assert prev.get("manifest_id") == "2026-05-02-bbb22222", (
        f"Expected previous=W30 (bbb22222), got {prev.get('manifest_id')}"
    )


def test_previous_wave_lookup_returns_none_for_first_wave(tmp_path, monkeypatch):
    """If no earlier manifest exists, return None."""
    import check_score_cap as mod

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    _write_manifest(
        tmp_path, sha="aaa11111", wave="31", cap_factors=[],
        generated_at="2026-05-03T10:00:00+00:00",
    )
    current = {"wave": "31", "scorecard": {}}
    prev = mod._previous_wave_manifest(current)
    assert prev is None
