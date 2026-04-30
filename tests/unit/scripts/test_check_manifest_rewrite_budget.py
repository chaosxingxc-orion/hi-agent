"""Tests for scripts/check_manifest_rewrite_budget.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_manifest(dir_path: Path, sha: str, wave_label: str = "Wave 17") -> Path:
    name = f"platform-release-manifest-2026-04-28-{sha}.json"
    payload = {
        "manifest_id": f"2026-04-28-{sha}",
        "release_head": sha + ("0" * (40 - len(sha))),
        "generated_at": f"2026-04-28T{int(sha[0], 16):02d}:00:00+00:00",
        "wave": wave_label,
        "git": {"head_sha": sha + ("0" * (40 - len(sha))), "short_sha": sha, "is_dirty": False},
    }
    p = dir_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_no_manifests_returns_deferred(tmp_path, monkeypatch, capsys):
    import check_manifest_rewrite_budget as mod

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "BUDGET_FILE", tmp_path / ".budget.json")
    monkeypatch.setattr(mod, "current_wave_number", lambda: 17)
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 2
    assert data["status"] == "deferred"


def test_under_budget_passes(tmp_path, monkeypatch, capsys):
    import check_manifest_rewrite_budget as mod

    for sha in ("aaa1111", "bbb2222"):
        _write_manifest(tmp_path, sha)
    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "BUDGET_FILE", tmp_path / ".budget.json")
    monkeypatch.setattr(mod, "current_wave_number", lambda: 17)
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["status"] == "pass"
    assert data["manifest_count"] == 2


def test_at_budget_passes(tmp_path, monkeypatch, capsys):
    import check_manifest_rewrite_budget as mod

    for sha in ("aaa1111", "bbb2222", "ccc3333"):
        _write_manifest(tmp_path, sha)
    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "BUDGET_FILE", tmp_path / ".budget.json")
    monkeypatch.setattr(mod, "current_wave_number", lambda: 17)
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["status"] == "pass"


def test_over_budget_no_override_fails(tmp_path, monkeypatch, capsys):
    import check_manifest_rewrite_budget as mod

    for sha in ("aaa1111", "bbb2222", "ccc3333", "ddd4444"):
        _write_manifest(tmp_path, sha)
    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "BUDGET_FILE", tmp_path / ".budget.json")
    monkeypatch.setattr(mod, "current_wave_number", lambda: 17)
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 1
    assert data["status"] == "fail"
    assert data["manifest_count"] == 4
    assert "remediation" in data
    assert "archive/W17" in data["remediation"]


def test_over_budget_with_valid_override_passes(tmp_path, monkeypatch, capsys):
    import check_manifest_rewrite_budget as mod

    for sha in ("aaa1111", "bbb2222", "ccc3333", "ddd4444"):
        _write_manifest(tmp_path, sha)
    head_sha = "abc12345" + ("0" * 32)
    override = {
        "wave": 17,
        "captain_sha": head_sha[:12],
        "ledger_entry_id": "RL-2026-04-29-1",
        "reason": "fourth manifest needed for emergency rollback",
        "approved_at": "2026-04-29T12:00:00+00:00",
    }
    budget_file = tmp_path / ".budget.json"
    budget_file.write_text(json.dumps(override), encoding="utf-8")

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "BUDGET_FILE", budget_file)
    monkeypatch.setattr(mod, "current_wave_number", lambda: 17)
    monkeypatch.setattr(mod, "_git_head", lambda: head_sha)

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["status"] == "pass"
    assert data["override_used"] is True


def test_over_budget_with_wrong_wave_override_fails(tmp_path, monkeypatch, capsys):
    import check_manifest_rewrite_budget as mod

    for sha in ("aaa1111", "bbb2222", "ccc3333", "ddd4444"):
        _write_manifest(tmp_path, sha)
    override = {
        "wave": 16,  # WRONG — current is 17
        "captain_sha": "abc12345",
        "ledger_entry_id": "RL-1",
        "reason": "x",
        "approved_at": "2026-04-29T12:00:00+00:00",
    }
    budget_file = tmp_path / ".budget.json"
    budget_file.write_text(json.dumps(override), encoding="utf-8")

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "BUDGET_FILE", budget_file)
    monkeypatch.setattr(mod, "current_wave_number", lambda: 17)
    monkeypatch.setattr(mod, "_git_head", lambda: "abc12345" + ("0" * 32))

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 1
    assert "wave=16" in data["override_invalid_reason"]


def test_other_wave_manifests_not_counted(tmp_path, monkeypatch, capsys):
    """Archived prior-wave manifests should not count against current wave's budget."""
    import check_manifest_rewrite_budget as mod

    # 4 manifests for Wave 16 — archived under archive/W16/ (per CL6/Rule 14)
    archive_dir = tmp_path / "archive" / "W16"
    archive_dir.mkdir(parents=True)
    for sha in ("aaa1111", "bbb2222", "ccc3333", "ddd4444"):
        _write_manifest(archive_dir, sha, wave_label="Wave 16")
    # 2 manifests for Wave 17 — in root, under budget
    for sha in ("eee5555", "fff6666"):
        _write_manifest(tmp_path, sha, wave_label="Wave 17")

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path)
    monkeypatch.setattr(mod, "BUDGET_FILE", tmp_path / ".budget.json")
    monkeypatch.setattr(mod, "current_wave_number", lambda: 17)
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["manifest_count"] == 2
