"""Tests for scripts/check_score_cap.py.

Covers the CP-6 fix (--strict-head behavior) and the manifest_picker
delegation that prevents the W17 score-cap circular dependency.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_manifest(dir_path: Path, sha: str, generated_at: str, *, verified: float = 75.0) -> Path:
    name = f"platform-release-manifest-2026-04-28-{sha}.json"
    payload = {
        "manifest_id": f"2026-04-28-{sha}",
        "release_head": sha + ("0" * (40 - len(sha))),
        "generated_at": generated_at,
        "git": {"head_sha": sha + ("0" * (40 - len(sha))), "short_sha": sha, "is_dirty": False},
        "scorecard": {
            "current_verified_readiness": verified,
            "verified": verified,
            "cap": verified,
            "cap_reason": "test",
            "cap_factors": [],
        },
    }
    p = dir_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_no_manifest_returns_deferred(tmp_path, monkeypatch, capsys):
    import check_score_cap as mod

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "verif")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "notices")
    rc = mod.main([])
    assert rc == 2
    captured = capsys.readouterr()
    assert "no manifest" in captured.err.lower()


def test_strict_head_defers_when_no_current_head_manifest(tmp_path, monkeypatch, capsys):
    import check_score_cap as mod

    _write_manifest(tmp_path, "stale01", "2026-04-28T10:00:00+00:00")
    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "verif")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "notices")
    monkeypatch.setattr(mod, "_git_head_full", lambda: "currnt0" + ("0" * 33))
    rc = mod.main(["--strict-head", "--json"])
    assert rc == 2
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "deferred"
    assert "current HEAD" in data["reason"]


def test_loose_mode_falls_back_to_latest_when_no_current_head_manifest(tmp_path, monkeypatch, capsys):
    import check_score_cap as mod

    _write_manifest(tmp_path, "stale01", "2026-04-28T10:00:00+00:00", verified=75.0)
    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "verif")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "notices")
    monkeypatch.setattr(mod, "_git_head_full", lambda: "currnt0" + ("0" * 33))
    rc = mod.main(["--json"])  # no --strict-head
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "pass"
    assert data["manifest_id"].endswith("stale01")


def test_picks_manifest_for_current_head_when_available(tmp_path, monkeypatch, capsys):
    import check_score_cap as mod

    _write_manifest(tmp_path, "older01", "2026-04-28T10:00:00+00:00", verified=70.0)
    _write_manifest(tmp_path, "currnt0", "2026-04-28T11:00:00+00:00", verified=80.0)
    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "VERIF_DIR", tmp_path / "verif")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "notices")
    monkeypatch.setattr(mod, "_git_head_full", lambda: "currnt0" + ("0" * 33))
    rc = mod.main(["--strict-head", "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "pass"
    assert data["current_verified_readiness"] == 80.0
    assert data["manifest_id"].endswith("currnt0")
