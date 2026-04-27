"""Tests for check_manifest_freshness.py."""
import pytest
from scripts.check_manifest_freshness import main


def test_no_manifest_fails(tmp_path, monkeypatch):
    import scripts.check_manifest_freshness as mf
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    assert main(["--json"]) == 1


def test_ok_returns_zero(tmp_path, monkeypatch):
    import json

    import scripts.check_manifest_freshness as mf
    head = mf._git_head()
    if head == "unknown":
        pytest.skip("git not available")
    manifest = {"release_head": head, "git": {"is_dirty": False}}
    manifest_file = tmp_path / "platform-release-manifest-2026-01-01-abc1234.json"
    manifest_file.write_text(json.dumps(manifest))
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    assert main(["--json"]) == 0
