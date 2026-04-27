"""Tests for check_verification_artifacts.py.

Covers:
- No docs/verification/ directory → pass (0 artifacts checked)
- Artifact with matching HEAD → pass
- Artifact with mismatching HEAD → fail, has_stale=True
- JSON output format
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.check_verification_artifacts as cva
from scripts.check_verification_artifacts import main


def _write_artifact(directory: Path, filename: str, head_field: str, head_value: str) -> Path:
    """Write a minimal JSON artifact file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / filename
    artifact.write_text(json.dumps({head_field: head_value}), encoding="utf-8")
    return artifact


class TestNoArtifactsDirectory:
    def test_no_verification_dir_passes(self, tmp_path, monkeypatch):
        """When docs/verification and docs/delivery don't exist, result is pass (0 checked)."""
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        result = main(["--json"])
        assert result == 0

    def test_no_verification_dir_json_output(self, tmp_path, monkeypatch, capsys):
        """JSON output shows 0 checked and not_applicable status when no dirs exist."""
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        main(["--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "not_applicable"
        assert data["checked_count"] == 0


class TestMatchingHead:
    def test_artifact_with_matching_head_passes(self, tmp_path, monkeypatch):
        """An artifact whose release_head matches current HEAD → pass."""
        fixed_head = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        monkeypatch.setattr(cva, "_git_head", lambda: fixed_head)
        _write_artifact(
            tmp_path / "docs" / "verification",
            "gate-2026-01-01.json",
            "release_head",
            fixed_head,
        )
        assert main(["--json"]) == 0

    def test_artifact_verified_head_field_passes(self, tmp_path, monkeypatch):
        """verified_head field (not release_head) is also checked."""
        fixed_head = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        monkeypatch.setattr(cva, "_git_head", lambda: fixed_head)
        _write_artifact(
            tmp_path / "docs" / "delivery",
            "delivery-2026-01-01.json",
            "verified_head",
            fixed_head,
        )
        assert main(["--json"]) == 0

    def test_short_sha_prefix_matches(self, tmp_path, monkeypatch):
        """A short SHA prefix that is a prefix of the full HEAD SHA counts as matching."""
        fixed_head = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        monkeypatch.setattr(cva, "_git_head", lambda: fixed_head)
        short = fixed_head[:7]
        _write_artifact(
            tmp_path / "docs" / "verification",
            "gate-short.json",
            "release_head",
            short,
        )
        assert main(["--json"]) == 0


class TestMismatchingHead:
    def test_stale_artifact_fails(self, tmp_path, monkeypatch):
        """An artifact whose head SHA does not match current HEAD → exit 1."""
        # Mock _git_head to return a known value so the stale comparison runs.
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        monkeypatch.setattr(cva, "_git_head", lambda: "aaaa1111bbbb2222cccc3333dddd4444eeee5555")
        _write_artifact(
            tmp_path / "docs" / "verification",
            "gate-stale.json",
            "release_head",
            "deadbeef1234",
        )
        result = main(["--json"])
        assert result == 1

    def test_stale_artifact_fails(self, tmp_path, monkeypatch, capsys):
        """JSON output must show fail status when no current artifact exists."""
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        monkeypatch.setattr(cva, "_git_head", lambda: "aaaa1111bbbb2222cccc3333dddd4444eeee5555")
        _write_artifact(
            tmp_path / "docs" / "delivery",
            "delivery-stale.json",
            "release_head",
            "0000000000000000000000000000000000000000",
        )
        main(["--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "fail"
        assert data["has_current_head"] is False

    def test_mixed_artifacts_passes_when_current_exists(self, tmp_path, monkeypatch):
        """A current artifact exists alongside historical ones — gate passes."""
        real_head = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        monkeypatch.setattr(cva, "_git_head", lambda: real_head)
        _write_artifact(
            tmp_path / "docs" / "verification",
            "gate-current.json",
            "release_head",
            real_head,
        )
        _write_artifact(
            tmp_path / "docs" / "verification",
            "gate-historical.json",
            "release_head",
            "cafebabe9876",
        )
        assert main(["--json"]) == 0


class TestJsonOutputFormat:
    def test_json_output_has_required_keys(self, tmp_path, monkeypatch, capsys):
        """JSON output must always contain check, status, has_current_head, current_files, checked_count."""
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        main(["--json"])
        data = json.loads(capsys.readouterr().out)
        for key in ("check", "status", "has_current_head", "current_files", "checked_count"):
            assert key in data, f"missing key: {key}"

    def test_json_check_field_value(self, tmp_path, monkeypatch, capsys):
        """check field must equal 'verification_artifacts'."""
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        main(["--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["check"] == "verification_artifacts"

    def test_artifact_without_head_field_is_skipped(self, tmp_path, monkeypatch, capsys):
        """Artifacts that have no release_head / verified_head / head_sha field are skipped."""
        monkeypatch.setattr(cva, "ROOT", tmp_path)
        (tmp_path / "docs" / "verification").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "verification" / "no-head.json").write_text(
            json.dumps({"some_other_field": "value"}), encoding="utf-8"
        )
        main(["--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["checked_count"] == 0
        assert data["status"] in ("pass", "not_applicable")
