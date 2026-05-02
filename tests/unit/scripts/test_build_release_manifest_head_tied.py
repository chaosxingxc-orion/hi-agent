"""W31-L (L-2') tests for build_release_manifest HEAD-tied evidence lookup.

Verifies that the architectural_seven_by_twenty_four cap fires when no
arch-7x24 evidence exists at the current HEAD, and clears only when an
exact SHA-keyed evidence file is present.

Previously _compute_cap used ``sorted(glob, key=mtime)[-1]`` which silently
cleared the cap whenever ANY arch-7x24 evidence existed in
docs/verification/, even from an earlier SHA. This is the L-2' regression
fix.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _seed_score_caps(root: Path) -> None:
    """Copy real score_caps.yaml into the tmp ROOT so _compute_cap can run."""
    src = REPO_ROOT / "docs" / "governance" / "score_caps.yaml"
    dst_dir = root / "docs" / "governance"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst_dir / "score_caps.yaml")


def _write_arch_evidence(verif_dir: Path, sha_short: str, *, all_pass: bool = True) -> Path:
    verif_dir.mkdir(parents=True, exist_ok=True)
    out = verif_dir / f"{sha_short}-arch-7x24.json"
    val = "PASS" if all_pass else "FAIL"
    payload = {
        "schema_version": "1",
        "check": "architectural_seven_by_twenty_four",
        "provenance": "real",
        "assertions": {
            "cross_loop_stability": val,
            "lifespan_observable": val,
            "cancellation_round_trip": val,
            "spine_provenance_real": val,
            "chaos_runtime_coupled_all": val,
        },
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def test_find_arch_evidence_for_head_returns_short_sha_match(tmp_path, monkeypatch):
    """_find_arch_evidence_for_head locates evidence by 8-char short SHA."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    verif = tmp_path / "docs" / "verification"
    fake_full = "abcdef12" + ("0" * 32)
    _write_arch_evidence(verif, fake_full[:8])

    found = mod._find_arch_evidence_for_head(fake_full)
    assert found is not None
    assert found.name == f"{fake_full[:8]}-arch-7x24.json"


def test_find_arch_evidence_returns_none_for_unrelated_sha(tmp_path, monkeypatch):
    """No mtime-fallback: stale evidence at a different SHA is not surfaced."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    verif = tmp_path / "docs" / "verification"
    # Write evidence keyed to STALE SHA.
    stale_full = "11111111" + ("0" * 32)
    _write_arch_evidence(verif, stale_full[:8])

    # Look up evidence for a DIFFERENT current HEAD; must return None.
    current_full = "99999999" + ("0" * 32)
    found = mod._find_arch_evidence_for_head(current_full)
    assert found is None, (
        "L-2' regression: stale evidence at a different SHA must NOT clear "
        "the cap; HEAD-tied lookup is required."
    )


def test_find_arch_evidence_handles_missing_dir(tmp_path, monkeypatch):
    """Missing verification directory yields None (no exception)."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)  # no docs/verification under tmp_path
    fake_full = "deadbeef" + ("0" * 32)
    found = mod._find_arch_evidence_for_head(fake_full)
    assert found is None


def test_find_arch_evidence_unknown_sha_returns_none(tmp_path, monkeypatch):
    """Empty or 'unknown' SHA returns None (no glob ambiguity)."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod._find_arch_evidence_for_head("") is None
    assert mod._find_arch_evidence_for_head("unknown") is None


def test_arch_cap_fires_when_evidence_at_different_sha(tmp_path, monkeypatch):
    """_compute_cap fires the architectural cap when evidence is for a stale SHA.

    This is the core L-2' assertion: a manifest at HEAD=A must NOT clear
    the 7x24 cap by reading evidence written for HEAD=B.
    """
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    _seed_score_caps(tmp_path)
    verif = tmp_path / "docs" / "verification"
    # Write PASS evidence at a stale SHA only.
    stale_full = "22222222" + ("0" * 32)
    _write_arch_evidence(verif, stale_full[:8], all_pass=True)
    # Mock _git_head_sha to return a DIFFERENT current SHA.
    current_full = "77777777" + ("0" * 32)
    monkeypatch.setattr(mod, "_git_head_sha", lambda: current_full)

    cap, _reason, factors = mod._compute_cap(
        {},
        tier="seven_by_twenty_four_operational_readiness",
    )
    # Cap=90 fires per architectural_seven_by_twenty_four rule
    assert cap is not None and cap <= 90, f"Expected cap <=90, got {cap}"
    assert any("architectural_seven_by_twenty_four" in f for f in factors), (
        f"Expected architectural_seven_by_twenty_four factor in {factors}"
    )
    # The factor or reason should mention HEAD-tied lookup
    assert any("no evidence file at HEAD" in f for f in factors), (
        f"Expected 'no evidence file at HEAD' in factors={factors}"
    )


def test_arch_cap_clears_when_evidence_matches_head(tmp_path, monkeypatch):
    """_compute_cap clears the architectural cap when HEAD-keyed evidence is PASS."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    _seed_score_caps(tmp_path)
    verif = tmp_path / "docs" / "verification"
    # Write PASS evidence at the CURRENT SHA.
    current_full = "55555555" + ("0" * 32)
    _write_arch_evidence(verif, current_full[:8], all_pass=True)
    monkeypatch.setattr(mod, "_git_head_sha", lambda: current_full)

    _cap, _reason, factors = mod._compute_cap(
        {},
        tier="seven_by_twenty_four_operational_readiness",
    )
    # The architectural factor should NOT be present.
    assert not any("architectural_seven_by_twenty_four" in f for f in factors), (
        f"architectural_seven_by_twenty_four cap fired even with HEAD-matched "
        f"PASS evidence; factors={factors}"
    )
