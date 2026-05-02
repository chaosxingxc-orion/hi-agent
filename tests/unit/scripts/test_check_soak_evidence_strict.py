"""W31-L (L-1') tests for scripts/check_soak_evidence.py --strict flag.

Three scenarios:
  1. Evidence file exists at HEAD with all PASS → exit 0 (always).
  2. No evidence file + no --strict → exit 0 (back-compat behaviour).
  3. No evidence file + --strict → exit 1 (FAIL, CI-blocking).

The --strict flag is the W31-L fix for L-1': previously CI would silently
accept "deferred" (no arch-7x24 evidence) as a pass, never blocking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_arch_evidence(verif_dir: Path, sha_short: str, *, all_pass: bool = True) -> Path:
    """Write a minimal arch-7x24.json evidence file."""
    verif_dir.mkdir(parents=True, exist_ok=True)
    out = verif_dir / f"{sha_short}-arch-7x24.json"
    assertion_value = "PASS" if all_pass else "FAIL"
    payload = {
        "schema_version": "1",
        "check": "architectural_seven_by_twenty_four",
        "provenance": "real",
        "assertions": {
            "cross_loop_stability": assertion_value,
            "lifespan_observable": assertion_value,
            "cancellation_round_trip": assertion_value,
            "spine_provenance_real": assertion_value,
            "chaos_runtime_coupled_all": assertion_value,
        },
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def test_with_evidence_exits_0(tmp_path, monkeypatch, capsys):
    """When arch-7x24 evidence exists at current HEAD with all PASS, exit 0."""
    import check_soak_evidence as mod

    # Use a fake HEAD; write evidence keyed to its short SHA.
    fake_full = "abcdef01" + ("0" * 32)
    fake_short = fake_full[:8]
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "_repo_head", lambda: fake_full)
    _write_arch_evidence(tmp_path, fake_short, all_pass=True)

    monkeypatch.setattr(sys, "argv", ["check_soak_evidence.py", "--json"])
    rc = mod.main()
    assert rc == 0, "evidence present + all PASS should exit 0"
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "pass"


def test_without_evidence_no_strict_exits_0(tmp_path, monkeypatch, capsys):
    """No evidence + no --strict → exit 0 (legacy back-compat)."""
    import check_soak_evidence as mod

    fake_full = "deadbeef" + ("0" * 32)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)  # tmp_path is empty
    monkeypatch.setattr(mod, "_repo_head", lambda: fake_full)
    monkeypatch.setattr(sys, "argv", ["check_soak_evidence.py", "--json"])
    rc = mod.main()
    assert rc == 0, "missing evidence without --strict should exit 0 (back-compat)"
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "deferred"
    assert data["strict"] is False


def test_without_evidence_strict_exits_1(tmp_path, monkeypatch, capsys):
    """No evidence + --strict → exit 1 (FAIL). The W31-L L-1' fix."""
    import check_soak_evidence as mod

    fake_full = "cafef00d" + ("0" * 32)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)  # tmp_path is empty
    monkeypatch.setattr(mod, "_repo_head", lambda: fake_full)
    monkeypatch.setattr(sys, "argv", ["check_soak_evidence.py", "--json", "--strict"])
    rc = mod.main()
    assert rc == 1, "missing evidence + --strict must exit 1 (FAIL)"
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "fail"
    assert data["strict"] is True
    # Reason still tells the operator what to do.
    assert "run scripts/run_arch_7x24.py" in data["reason"]


def test_with_failing_assertions_always_exits_1(tmp_path, monkeypatch, capsys):
    """Evidence with one FAIL assertion always exits 1, --strict or not."""
    import check_soak_evidence as mod

    fake_full = "12345678" + ("0" * 32)
    fake_short = fake_full[:8]
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path)
    monkeypatch.setattr(mod, "_repo_head", lambda: fake_full)
    _write_arch_evidence(tmp_path, fake_short, all_pass=False)

    monkeypatch.setattr(sys, "argv", ["check_soak_evidence.py", "--json"])
    rc = mod.main()
    assert rc == 1, "FAIL assertions always exit 1 regardless of --strict"
