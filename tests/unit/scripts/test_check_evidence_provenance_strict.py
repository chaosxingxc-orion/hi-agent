"""W31-L (L-5') tests for scripts/check_evidence_provenance.py strict mode.

Verifies that real-required gates (observability_spine_completeness,
chaos_runtime_coupling, soak_evidence) reject provenance values
'structural' and 'degraded' in addition to the original 'synthetic' /
'unknown'.

Pre-W31 the docstring claimed real-required semantics but the disallowed
set only blocked synthetic/unknown — a structural or degraded artifact
silently satisfied the gate. The L-5' fix expands the disallowed set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_evidence(verif_dir: Path, name: str, *, check: str, provenance: str) -> Path:
    verif_dir.mkdir(parents=True, exist_ok=True)
    p = verif_dir / name
    payload = {
        "schema_version": "1",
        "check": check,
        "provenance": provenance,
        "status": "pass",
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_disallowed_set_includes_structural_and_degraded():
    """The L-5' fix MUST add 'structural' and 'degraded' to the disallowed set."""
    import check_evidence_provenance as mod

    assert "structural" in mod._DISALLOWED_FOR_STRICT, (
        "L-5' fix: 'structural' must be in _DISALLOWED_FOR_STRICT for "
        "real-required gates to fail closed on structural evidence."
    )
    assert "degraded" in mod._DISALLOWED_FOR_STRICT, (
        "L-5' fix: 'degraded' must be in _DISALLOWED_FOR_STRICT."
    )
    # The original entries remain.
    assert "synthetic" in mod._DISALLOWED_FOR_STRICT
    assert "unknown" in mod._DISALLOWED_FOR_STRICT


def test_strict_gate_rejects_structural_evidence(tmp_path, monkeypatch):
    """Real-required gate with structural evidence -> issue raised."""
    import check_evidence_provenance as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_DIR", tmp_path / "delivery")
    monkeypatch.setattr(mod, "LEGACY_DIR", tmp_path / "_legacy")

    _write_evidence(
        tmp_path,
        "test-spine.json",
        check="observability_spine_completeness",
        provenance="structural",
    )

    results = mod._scan_dir(tmp_path)
    failing = [r for r in results if r.get("issues")]
    assert len(failing) == 1
    assert "observability_spine_completeness" in failing[0]["issues"][0]
    assert "structural" in failing[0]["issues"][0]


def test_strict_gate_rejects_degraded_evidence(tmp_path, monkeypatch):
    """Real-required gate with degraded evidence -> issue raised."""
    import check_evidence_provenance as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_DIR", tmp_path / "delivery")
    monkeypatch.setattr(mod, "LEGACY_DIR", tmp_path / "_legacy")

    _write_evidence(
        tmp_path,
        "test-chaos.json",
        check="chaos_runtime_coupling",
        provenance="degraded",
    )

    results = mod._scan_dir(tmp_path)
    failing = [r for r in results if r.get("issues")]
    assert len(failing) == 1
    assert "chaos_runtime_coupling" in failing[0]["issues"][0]


def test_strict_gate_accepts_real_evidence(tmp_path, monkeypatch):
    """Real-required gate with provenance:real -> no issue."""
    import check_evidence_provenance as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_DIR", tmp_path / "delivery")
    monkeypatch.setattr(mod, "LEGACY_DIR", tmp_path / "_legacy")

    _write_evidence(
        tmp_path,
        "test-soak.json",
        check="soak_evidence",
        provenance="real",
    )
    results = mod._scan_dir(tmp_path)
    failing = [r for r in results if r.get("issues")]
    assert failing == []


def test_non_strict_gate_accepts_structural_evidence(tmp_path, monkeypatch):
    """A non-strict-gate artifact with structural provenance -> still passes.

    The new disallow list ONLY applies to gates listed in
    _REAL_REQUIRED_CHECKS. Other gates may still produce structural evidence.
    """
    import check_evidence_provenance as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_DIR", tmp_path / "delivery")
    monkeypatch.setattr(mod, "LEGACY_DIR", tmp_path / "_legacy")

    _write_evidence(
        tmp_path,
        "test-other.json",
        check="some_other_gate",  # NOT in _REAL_REQUIRED_CHECKS
        provenance="structural",
    )
    results = mod._scan_dir(tmp_path)
    failing = [r for r in results if r.get("issues")]
    assert failing == [], f"non-strict gate should accept structural, got {failing}"


def test_unknown_provenance_value_still_fails(tmp_path, monkeypatch):
    """Unknown provenance values fail regardless of gate."""
    import check_evidence_provenance as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_DIR", tmp_path / "delivery")
    monkeypatch.setattr(mod, "LEGACY_DIR", tmp_path / "_legacy")

    _write_evidence(
        tmp_path,
        "test-bogus.json",
        check="other_gate",
        provenance="bogus_value",
    )
    results = mod._scan_dir(tmp_path)
    failing = [r for r in results if r.get("issues")]
    assert len(failing) == 1
    assert "unknown provenance value" in failing[0]["issues"][0]


def test_missing_provenance_field_fails(tmp_path, monkeypatch):
    """Missing 'provenance' field fails regardless of gate."""
    import check_evidence_provenance as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_DIR", tmp_path / "delivery")
    monkeypatch.setattr(mod, "LEGACY_DIR", tmp_path / "_legacy")

    p = tmp_path / "test-no-prov.json"
    p.write_text(json.dumps({"check": "soak_evidence"}), encoding="utf-8")
    results = mod._scan_dir(tmp_path)
    failing = [r for r in results if r.get("issues")]
    assert len(failing) == 1
    assert "missing 'provenance' field" in failing[0]["issues"][0]
