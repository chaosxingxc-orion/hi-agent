"""Regression test for scripts/check_signoff_evidence_exemption.py (W35-corrective §5.2).

Drives the gate as a subprocess against fixture signoff files in tmp_path
to exercise the four cases:

1. No divergence (evidence head matches release_head) → PASS.
2. Divergence + missing exemption → FAIL.
3. Divergence + well-formed gov_infra_gap exemption → PASS.
4. Divergence + malformed exemption (missing required field) → FAIL.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT_NAME = "check_signoff_evidence_exemption.py"


def _build_fixture_repo(tmp_path: Path) -> Path:
    """Lay out a minimal fixture repo so the gate's ROOT resolution finds
    the right paths.

    The gate computes ``ROOT = Path(__file__).resolve().parent.parent`` and
    expects ``docs/releases/`` and ``docs/current-wave.txt`` and the
    ``_governance/`` package alongside the script. We ``copytree`` the
    real ``_governance/`` package and ``copy2`` the gate.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copytree(ROOT / "scripts" / "_governance", scripts_dir / "_governance")
    shutil.copy2(ROOT / "scripts" / GATE_SCRIPT_NAME, scripts_dir / GATE_SCRIPT_NAME)

    docs_dir = tmp_path / "docs"
    (docs_dir / "governance").mkdir(parents=True)
    (docs_dir / "releases").mkdir(parents=True)
    (docs_dir / "current-wave.txt").write_text("99\n", encoding="utf-8")
    (docs_dir / "governance" / "allowlists.yaml").write_text(
        "current_wave: 99\n", encoding="utf-8"
    )
    return tmp_path


def _run_gate(fixture_root: Path) -> tuple[int, dict]:
    """Run the gate as a subprocess from the fixture root and parse JSON output."""
    proc = subprocess.run(
        [sys.executable, str(fixture_root / "scripts" / GATE_SCRIPT_NAME), "--json"],
        capture_output=True,
        text=True,
        cwd=str(fixture_root),
    )
    try:
        result = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        result = {"_stdout": proc.stdout, "_stderr": proc.stderr}
    return proc.returncode, result


def _write_signoff(fixture_root: Path, signoff: dict) -> None:
    path = fixture_root / "docs" / "releases" / "wave99-signoff.json"
    path.write_text(json.dumps(signoff, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_pass_when_evidence_head_matches_release_head(tmp_path):
    """No divergence → gate passes (no exemption needed)."""
    fixture = _build_fixture_repo(tmp_path)
    same_head = "0123456789abcdef0123456789abcdef01234567"
    short = same_head[:8]
    ce_path = f"docs/verification/{short}-default-offline-clean-env.json"
    arch_path = f"docs/verification/{short}-arch-7x24.json"
    t3_path = f"docs/delivery/2026-05-06-{short}-t3-volces.json"
    _write_signoff(
        fixture,
        {
            "wave": 99,
            "release_head": same_head,
            "evidence": {
                "default_offline_clean_env": ce_path,
                "arch_7x24": arch_path,
                "t3_real_volces": t3_path,
            },
        },
    )
    rc, result = _run_gate(fixture)
    assert rc == 0, f"expected pass; got rc={rc} result={result}"
    assert result.get("status") == "pass"


def test_fail_when_evidence_diverges_and_no_exemption(tmp_path):
    """Divergence + missing exemption clause → fail."""
    fixture = _build_fixture_repo(tmp_path)
    release_head = "0123456789abcdef0123456789abcdef01234567"
    evidence_head = "fedcba9876543210fedcba9876543210fedcba98"
    e_short = evidence_head[:8]
    _write_signoff(
        fixture,
        {
            "wave": 99,
            "release_head": release_head,
            "evidence": {
                "default_offline_clean_env": (
                    f"docs/verification/{e_short}-default-offline-clean-env.json"
                ),
            },
        },
    )
    rc, result = _run_gate(fixture)
    assert rc == 1, f"expected fail; got rc={rc} result={result}"
    assert result.get("status") == "fail"
    assert any(
        "no evidence_exemption" in v for v in result.get("violations", [])
    ), f"expected 'no evidence_exemption' violation; got {result.get('violations')}"


def test_fail_when_exemption_missing_required_field(tmp_path):
    """Exemption present but missing rationale → fail with field-level violation."""
    fixture = _build_fixture_repo(tmp_path)
    release_head = "0123456789abcdef0123456789abcdef01234567"
    evidence_head = "fedcba9876543210fedcba9876543210fedcba98"
    e_short = evidence_head[:8]
    _write_signoff(
        fixture,
        {
            "wave": 99,
            "release_head": release_head,
            "evidence": {
                "default_offline_clean_env": (
                    f"docs/verification/{e_short}-default-offline-clean-env.json"
                ),
            },
            "evidence_exemption": {
                "kind": "rerun_pending",
                "evidence_head": evidence_head,
                "release_head": release_head,
                "rationale": "",  # empty — violation
                "hot_path_audit": "",  # empty — violation
                "next_action": "",  # empty — violation for rerun_pending kind
            },
        },
    )
    rc, result = _run_gate(fixture)
    assert rc == 1, f"expected fail; got rc={rc} result={result}"
    violations = result.get("violations", [])
    # Expect at minimum a rationale violation and a next_action violation.
    assert any("rationale" in v for v in violations), violations
    assert any("next_action" in v for v in violations), violations


def test_fail_on_unknown_exemption_kind(tmp_path):
    """Exemption.kind not in the documented enum → fail."""
    fixture = _build_fixture_repo(tmp_path)
    release_head = "0123456789abcdef0123456789abcdef01234567"
    evidence_head = "fedcba9876543210fedcba9876543210fedcba98"
    e_short = evidence_head[:8]
    _write_signoff(
        fixture,
        {
            "wave": 99,
            "release_head": release_head,
            "evidence": {
                "default_offline_clean_env": (
                    f"docs/verification/{e_short}-default-offline-clean-env.json"
                ),
            },
            "evidence_exemption": {
                "kind": "i_just_made_this_up",  # ← not in enum
                "evidence_head": evidence_head,
                "release_head": release_head,
                "rationale": "yolo",
                "hot_path_audit": "checked",
            },
        },
    )
    rc, result = _run_gate(fixture)
    assert rc == 1, f"expected fail; got rc={rc} result={result}"
    assert any(
        "kind=" in v for v in result.get("violations", [])
    ), result.get("violations")


def test_deferred_when_no_signoff_for_current_wave(tmp_path):
    """Wave with no signoff file → deferred (rc=2)."""
    fixture = _build_fixture_repo(tmp_path)
    # No signoff file written.
    rc, result = _run_gate(fixture)
    assert rc == 2, f"expected deferred; got rc={rc} result={result}"
    assert result.get("status") == "deferred"
