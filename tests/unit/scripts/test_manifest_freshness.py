"""Tests for check_manifest_freshness.py.

Covers:
- Strict mode (default): any head mismatch → FAIL
- --allow-docs-only-gap mode: docs-only diff → PASS
- Strict mode with exact HEAD match → PASS
"""
import json

import pytest
import scripts.check_manifest_freshness as mf
from scripts.check_manifest_freshness import main


def _write_manifest(tmp_path, release_head: str, is_dirty: bool = False) -> None:
    manifest = {"release_head": release_head, "git": {"is_dirty": is_dirty}}
    manifest_file = tmp_path / "platform-release-manifest-2026-01-01-abc1234.json"
    manifest_file.write_text(json.dumps(manifest))


def test_no_manifest_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    assert main(["--json"]) == 1


def test_ok_returns_zero(tmp_path, monkeypatch):
    head = mf._git_head()
    if head == "unknown":
        pytest.skip("git not available")
    _write_manifest(tmp_path, head, is_dirty=False)
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    assert main(["--json"]) == 0


def test_strict_mode_head_mismatch_fails(tmp_path, monkeypatch):
    """Without --allow-docs-only-gap, any head mismatch must → FAIL (exit 1)."""
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    # Write a manifest pointing at a clearly wrong SHA
    _write_manifest(tmp_path, "aaaaaaaaaaaa", is_dirty=False)
    result = main(["--json"])
    assert result == 1, "strict mode must fail when manifest HEAD != current HEAD"


def test_strict_mode_head_mismatch_json_has_reason(tmp_path, monkeypatch, capsys):
    """Strict mode mismatch must emit head_mismatch reason in JSON output."""
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    _write_manifest(tmp_path, "aaaaaaaaaaaa", is_dirty=False)
    main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "fail"
    assert any("head_mismatch" in r for r in data["reasons"])
    assert data["allow_docs_only_gap"] is False


def test_allow_docs_only_gap_flag_present_in_json(tmp_path, monkeypatch, capsys):
    """--allow-docs-only-gap flag value must appear in JSON output."""
    head = mf._git_head()
    if head == "unknown":
        pytest.skip("git not available")
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    _write_manifest(tmp_path, head, is_dirty=False)
    main(["--json", "--allow-docs-only-gap"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["allow_docs_only_gap"] is True


def test_strict_mode_exact_head_match_passes(tmp_path, monkeypatch):
    """Strict mode with exact HEAD match must return 0."""
    head = mf._git_head()
    if head == "unknown":
        pytest.skip("git not available")
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    _write_manifest(tmp_path, head, is_dirty=False)
    assert main([]) == 0


def test_allow_docs_only_gap_mismatch_without_gap_function_fails(tmp_path, monkeypatch):
    """--allow-docs-only-gap still fails when gap detection shows non-docs files changed."""
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    # Write manifest with wrong head; patch _manifest_commit_gap to return False (non-docs gap)
    _write_manifest(tmp_path, "aaaaaaaaaaaa", is_dirty=False)
    monkeypatch.setattr(mf, "_manifest_commit_gap", lambda a, b: False)
    result = main(["--json", "--allow-docs-only-gap"])
    assert result == 1


def test_allow_docs_only_gap_docs_only_diff_passes(tmp_path, monkeypatch):
    """--allow-docs-only-gap passes when gap detection confirms only docs/ files changed."""
    monkeypatch.setattr(mf, "RELEASES_DIR", tmp_path)
    _write_manifest(tmp_path, "aaaaaaaaaaaa", is_dirty=False)
    # Patch gap function to simulate docs-only diff
    monkeypatch.setattr(mf, "_manifest_commit_gap", lambda a, b: True)
    result = main(["--json", "--allow-docs-only-gap"])
    assert result == 0
