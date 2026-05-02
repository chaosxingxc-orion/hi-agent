"""W31-L (L-12'/L-13') tests for the soak_evidence_not_real cap rule.

Verifies:
  1. ``_ARCH_CONSTRAINT_GATES`` no longer contains ``soak_evidence``, so a
     real FAIL on soak does affect ``current_verified_readiness`` via
     ``gate_fail``.
  2. The new ``soak_evidence_not_real`` cap fires when no soak evidence
     exists at current HEAD.
  3. The cap fires when soak evidence has provenance != 'real'.
  4. The cap clears when a real soak evidence file at HEAD is present.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _seed_score_caps(root: Path) -> None:
    src = REPO_ROOT / "docs" / "governance" / "score_caps.yaml"
    dst_dir = root / "docs" / "governance"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst_dir / "score_caps.yaml")


def _write_soak_evidence(
    verif_dir: Path,
    sha_short: str,
    *,
    duration: str = "1h",
    provenance: str = "real",
) -> Path:
    verif_dir.mkdir(parents=True, exist_ok=True)
    out = verif_dir / f"{sha_short}-soak-{duration}.json"
    payload = {
        "schema_version": "1",
        "check": "soak",
        "provenance": provenance,
        "invariants_held": True,
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def test_arch_constraint_gates_excludes_soak_evidence():
    """L-12' fix: soak_evidence is removed from _ARCH_CONSTRAINT_GATES."""
    import build_release_manifest as mod

    assert "soak_evidence" not in mod._ARCH_CONSTRAINT_GATES, (
        "L-12' fix: soak_evidence MUST be removed from _ARCH_CONSTRAINT_GATES "
        "so a real FAIL on soak affects current_verified_readiness via "
        "gate_fail. The set should retain only "
        "{observability_spine_completeness, chaos_runtime_coupling}."
    )
    assert "observability_spine_completeness" in mod._ARCH_CONSTRAINT_GATES
    assert "chaos_runtime_coupling" in mod._ARCH_CONSTRAINT_GATES


def test_soak_cap_fires_when_no_evidence(tmp_path, monkeypatch):
    """L-13' fix: cap fires on missing soak evidence at HEAD."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    _seed_score_caps(tmp_path)
    monkeypatch.setattr(mod, "_git_head_sha", lambda: "f" * 40)

    cap, _reason, factors = mod._compute_cap(
        {},
        tier="current_verified_readiness",
    )
    assert cap is not None and cap <= 75, f"Expected cap <=75, got {cap}"
    assert any("soak_evidence_not_real" in f for f in factors), (
        f"Expected soak_evidence_not_real factor in {factors}"
    )
    assert any("no soak evidence at HEAD" in f for f in factors)


def test_soak_cap_fires_when_provenance_not_real(tmp_path, monkeypatch):
    """L-13' fix: cap fires when soak evidence has provenance != real."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    _seed_score_caps(tmp_path)
    head = "abc12345" + ("0" * 32)
    monkeypatch.setattr(mod, "_git_head_sha", lambda: head)
    verif = tmp_path / "docs" / "verification"
    _write_soak_evidence(verif, head[:8], duration="1h", provenance="structural")

    _cap, _reason, factors = mod._compute_cap(
        {},
        tier="current_verified_readiness",
    )
    assert any("soak_evidence_not_real" in f for f in factors), (
        f"Expected soak_evidence_not_real factor in {factors}"
    )
    # Reason should mention the wrong provenance.
    assert any("structural" in f for f in factors)


def test_soak_cap_clears_with_real_evidence(tmp_path, monkeypatch):
    """L-13' fix: cap clears with real soak evidence at HEAD."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    _seed_score_caps(tmp_path)
    head = "deadbeef" + ("0" * 32)
    monkeypatch.setattr(mod, "_git_head_sha", lambda: head)
    verif = tmp_path / "docs" / "verification"
    _write_soak_evidence(verif, head[:8], duration="1h", provenance="real")

    _cap, _reason, factors = mod._compute_cap(
        {},
        tier="current_verified_readiness",
    )
    assert not any("soak_evidence_not_real" in f for f in factors), (
        f"Expected soak_evidence_not_real cap to clear with real evidence; "
        f"factors={factors}"
    )


def test_soak_cap_only_on_verified_tier(tmp_path, monkeypatch):
    """soak_evidence_not_real has scope=[current_verified_readiness] only."""
    import build_release_manifest as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    _seed_score_caps(tmp_path)
    monkeypatch.setattr(mod, "_git_head_sha", lambda: "f" * 40)

    # On the 7x24 tier, soak_evidence_not_real should NOT fire.
    _cap, _reason, factors = mod._compute_cap(
        {},
        tier="seven_by_twenty_four_operational_readiness",
    )
    assert not any("soak_evidence_not_real" in f for f in factors), (
        "soak_evidence_not_real must be scoped to current_verified_readiness only"
    )


def test_score_caps_yaml_contains_soak_evidence_not_real():
    """The yaml registry MUST contain the new condition."""
    text = (REPO_ROOT / "docs" / "governance" / "score_caps.yaml").read_text(
        encoding="utf-8"
    )
    assert "soak_evidence_not_real" in text, (
        "score_caps.yaml must declare the soak_evidence_not_real condition "
        "(W31-L L-12'/L-13')"
    )
    assert "current_verified_readiness" in text
    # The cap value 75 should be present near the rule
    import re
    pattern = re.compile(
        r"-\s+condition:\s+soak_evidence_not_real\s+cap:\s+(\d+)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    assert m is not None, "soak_evidence_not_real rule must declare a cap value"
    assert int(m.group(1)) == 75, (
        f"Expected soak_evidence_not_real cap=75, got {m.group(1)}"
    )
