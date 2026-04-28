"""Unit tests: check_operator_drill.py main() logic.

Tests:
- No evidence file => exit 2 (deferred)
- Valid evidence with matching head => exit 0
- Evidence head mismatches current HEAD => exit 1
- provenance != 'real' => exit 1
- all_passed == False => exit 1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_operator_drill as mod


def _make_evidence(tmp_path: Path, head: str, **overrides: object) -> Path:
    verif = tmp_path / "docs" / "verification"
    verif.mkdir(parents=True)
    data = {
        "provenance": "real",
        "all_passed": True,
        "head": head,
        "actions": [{"name": "cancel_live_run", "passed": True}],
    }
    data.update(overrides)
    ev = verif / "abc1234-operator-drill.json"
    ev.write_text(json.dumps(data), encoding="utf-8")
    return ev


def test_no_evidence_returns_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no operator-drill evidence exists, exit code must be 2."""
    verif = tmp_path / "docs" / "verification"
    verif.mkdir(parents=True)
    monkeypatch.setattr(mod, "VERIF_DIR", verif)
    monkeypatch.setattr(sys, "argv", ["check_operator_drill"])
    result = mod.main()
    assert result == 2


def test_matching_head_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid evidence with matching HEAD must exit 0."""
    sha = "abc1234"
    _make_evidence(tmp_path, sha)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "docs" / "verification")
    monkeypatch.setattr(mod, "_git_head", lambda: sha)
    monkeypatch.setattr(sys, "argv", ["check_operator_drill"])
    result = mod.main()
    assert result == 0


def test_mismatched_head_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evidence head != current HEAD must exit 1."""
    evidence_sha = "abc1234"
    current_sha = "deadbeef"
    _make_evidence(tmp_path, evidence_sha)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "docs" / "verification")
    monkeypatch.setattr(mod, "_git_head", lambda: current_sha)
    monkeypatch.setattr(sys, "argv", ["check_operator_drill"])
    result = mod.main()
    assert result == 1


def test_non_real_provenance_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provenance != 'real' must exit 1."""
    sha = "abc1234"
    _make_evidence(tmp_path, sha, provenance="mock")
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "docs" / "verification")
    monkeypatch.setattr(mod, "_git_head", lambda: sha)
    monkeypatch.setattr(sys, "argv", ["check_operator_drill"])
    result = mod.main()
    assert result == 1


def test_all_passed_false_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """all_passed=False must exit 1."""
    sha = "abc1234"
    _make_evidence(
        tmp_path,
        sha,
        all_passed=False,
        actions=[{"name": "cancel_live_run", "passed": False}],
    )
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "docs" / "verification")
    monkeypatch.setattr(mod, "_git_head", lambda: sha)
    monkeypatch.setattr(sys, "argv", ["check_operator_drill"])
    result = mod.main()
    assert result == 1


def test_json_output_on_head_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--json flag must emit parseable JSON with status=fail on head mismatch."""
    evidence_sha = "abc1234"
    current_sha = "deadbeef"
    _make_evidence(tmp_path, evidence_sha)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "docs" / "verification")
    monkeypatch.setattr(mod, "_git_head", lambda: current_sha)
    monkeypatch.setattr(sys, "argv", ["check_operator_drill", "--json"])

    result = mod.main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert result == 1
    assert data["status"] == "fail"
    assert any("head" in issue for issue in data["issues"])
