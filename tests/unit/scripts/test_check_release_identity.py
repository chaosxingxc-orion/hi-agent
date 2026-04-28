"""Unit tests: check_release_identity.py main() logic.

Tests:
- No manifest => exit 2 (deferred)
- Manifest head matches repo HEAD => exit 0
- Manifest head mismatches repo HEAD => exit 1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_release_identity as mod


def _make_manifest(tmp_path: Path, head: str) -> Path:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    manifest = releases / "platform-release-manifest-test.json"
    manifest.write_text(
        json.dumps({"release_head": head, "git": {"is_dirty": False}}),
        encoding="utf-8",
    )
    return manifest


def test_no_manifest_returns_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When docs/releases/ has no manifests, exit code must be 2 (deferred)."""
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    monkeypatch.setattr(mod, "RELEASES_DIR", releases)
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "docs" / "downstream-responses")
    monkeypatch.setattr(sys, "argv", ["check_release_identity"])

    result = mod.main()
    assert result == 2, "Expected exit 2 (deferred) when no manifest present"


def test_matching_heads_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When manifest head matches repo HEAD, exit code must be 0."""
    sha = "aabbccddee11"
    _make_manifest(tmp_path, sha)

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path / "docs" / "releases")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "docs" / "downstream-responses")
    (tmp_path / "docs" / "downstream-responses").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "_repo_head", lambda: sha)
    monkeypatch.setattr(sys, "argv", ["check_release_identity"])

    result = mod.main()
    assert result == 0, "Expected exit 0 when manifest head == repo HEAD"


def test_mismatched_heads_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When manifest head differs from repo HEAD, exit code must be 1."""
    manifest_sha = "aabbccddee11"
    repo_sha = "ff0011223344"
    _make_manifest(tmp_path, manifest_sha)

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path / "docs" / "releases")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "docs" / "downstream-responses")
    (tmp_path / "docs" / "downstream-responses").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "_repo_head", lambda: repo_sha)
    monkeypatch.setattr(sys, "argv", ["check_release_identity"])

    result = mod.main()
    assert result == 1, "Expected exit 1 when manifest head != repo HEAD"


def test_json_output_on_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--json flag must emit parseable JSON with status=fail on mismatch."""
    manifest_sha = "aabbccddee11"
    repo_sha = "ff0011223344"
    _make_manifest(tmp_path, manifest_sha)

    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path / "docs" / "releases")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "docs" / "downstream-responses")
    (tmp_path / "docs" / "downstream-responses").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "_repo_head", lambda: repo_sha)
    monkeypatch.setattr(sys, "argv", ["check_release_identity", "--json"])

    result = mod.main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert result == 1
    assert data["status"] == "fail"
    assert len(data["violations"]) > 0
