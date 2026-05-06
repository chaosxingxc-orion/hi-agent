"""W35 §5.1 (W32-D-recurrence): Regression test for ledger drift detection.

Asserts that scripts/check_wave_consistency.py treats recurrence-ledger.yaml's
top-level `current_wave` as a tracked source and fails when that field drifts
from the other wave labels (current-wave.txt, allowlists.yaml, manifest, notice).

The W35 audit found ledger.current_wave=33 while current-wave.txt said 35;
the prior gate read 4 sources but not the ledger itself, so the drift the gate
was meant to police went undetected for two waves. This test is the regression
guarantee that the fix in check_wave_consistency.py stays in place.

Driven via subprocess from a fixture repository copied into tmp_path so the
gate runs against an isolated layout (independent of the live repo's drift state).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "check_wave_consistency.py"
GOVERNANCE_PKG = REPO_ROOT / "scripts" / "_governance"


def _build_fixture_repo(
    tmp_path: Path,
    *,
    current_wave_label: str,
    allowlists_wave: int,
    ledger_wave: int,
) -> Path:
    """Copy the gate + _governance package + write minimal fixture wave files.

    Returns the fixture repo root. The gate's ROOT is computed from the script's
    location (Path(__file__).resolve().parent.parent), so placing the gate at
    <fixture>/scripts/check_wave_consistency.py makes <fixture> the effective ROOT.
    """
    fixture_root = tmp_path / "fixture-repo"
    scripts_dir = fixture_root / "scripts"
    docs_dir = fixture_root / "docs"
    governance_dir = docs_dir / "governance"
    releases_dir = docs_dir / "releases"
    notices_dir = docs_dir / "downstream-responses"

    scripts_dir.mkdir(parents=True)
    governance_dir.mkdir(parents=True)
    releases_dir.mkdir(parents=True)
    notices_dir.mkdir(parents=True)

    # Copy the gate script and the _governance package it depends on.
    shutil.copy2(GATE_SCRIPT, scripts_dir / "check_wave_consistency.py")
    shutil.copytree(GOVERNANCE_PKG, scripts_dir / "_governance")

    # docs/current-wave.txt — authoritative source of truth.
    (docs_dir / "current-wave.txt").write_text(current_wave_label + "\n", encoding="utf-8")

    # docs/governance/allowlists.yaml.
    (governance_dir / "allowlists.yaml").write_text(
        'schema_version: "1"\n'
        f"current_wave: {allowlists_wave}\n"
        "entries: []\n",
        encoding="utf-8",
    )

    # docs/governance/recurrence-ledger.yaml — the new tracked source.
    (governance_dir / "recurrence-ledger.yaml").write_text(
        'schema_version: "1"\n'
        f"current_wave: {ledger_wave}\n"
        "entries: []\n",
        encoding="utf-8",
    )

    return fixture_root


def _run_gate(fixture_root: Path) -> tuple[int, dict]:
    """Invoke the gate script against the fixture repo. Returns (rc, parsed_json)."""
    gate_path = fixture_root / "scripts" / "check_wave_consistency.py"
    proc = subprocess.run(
        [sys.executable, str(gate_path), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload: dict
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"_raw_stdout": proc.stdout, "_raw_stderr": proc.stderr}
    return proc.returncode, payload


def test_ledger_drift_fails_gate(tmp_path):
    """Negative control: ledger drifted to 33 while everything else says 35.

    This is exactly the W35-audit observation the §5.1 fix is meant to catch.
    Without the gate extension, the gate would PASS because it didn't read
    the ledger. With the extension, the gate must FAIL with a drift message
    naming the recurrence_ledger_yaml source.
    """
    fixture_root = _build_fixture_repo(
        tmp_path,
        current_wave_label="Wave 35",
        allowlists_wave=35,
        ledger_wave=33,  # DRIFT
    )

    rc, payload = _run_gate(fixture_root)

    assert rc == 1, f"expected fail (rc=1) on ledger drift; got rc={rc}, payload={payload}"
    assert payload.get("status") == "fail", payload
    violations = payload.get("violations", [])
    assert any("drift" in v for v in violations), (
        f"expected a drift violation in output; got {violations}"
    )
    # The drift message must mention recurrence_ledger_yaml so operators can find it.
    assert any("recurrence_ledger_yaml" in v for v in violations), (
        f"expected recurrence_ledger_yaml to be named in drift violation; got {violations}"
    )
    sources = payload.get("sources", {})
    assert sources.get("recurrence_ledger_yaml") == "33", sources


def test_ledger_agrees_passes_gate(tmp_path):
    """Positive control: when every source (including the ledger) agrees on 35,
    the gate PASSes."""
    fixture_root = _build_fixture_repo(
        tmp_path,
        current_wave_label="Wave 35",
        allowlists_wave=35,
        ledger_wave=35,  # AGREES
    )

    rc, payload = _run_gate(fixture_root)

    assert rc == 0, f"expected pass (rc=0) when all sources agree; got rc={rc}, payload={payload}"
    assert payload.get("status") == "pass", payload
    sources = payload.get("sources", {})
    assert sources.get("recurrence_ledger_yaml") == "35", sources


def test_missing_ledger_does_not_block(tmp_path):
    """Defense-in-depth: a fixture without recurrence-ledger.yaml at all must not
    crash or fail the gate; the source is reported as None and the remaining
    sources still drive the comparison."""
    fixture_root = _build_fixture_repo(
        tmp_path,
        current_wave_label="Wave 35",
        allowlists_wave=35,
        ledger_wave=35,
    )
    # Remove the ledger file we wrote above.
    (fixture_root / "docs" / "governance" / "recurrence-ledger.yaml").unlink()

    rc, payload = _run_gate(fixture_root)

    # current-wave.txt and allowlists.yaml still agree -> pass.
    assert rc == 0, payload
    assert payload.get("status") == "pass", payload
    sources = payload.get("sources", {})
    assert sources.get("recurrence_ledger_yaml") is None, sources


if __name__ == "__main__":
    pytest.main([__file__, "-x", "-v"])
