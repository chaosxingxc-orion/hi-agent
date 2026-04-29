"""W22-A10: Score artifact self-consistency hard gate tests.

Validates that check_score_artifact_consistency.py correctly enforces
the three-way SHA agreement between filename, manifest_id, and release_head.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"


def _run_gate(manifest_path: str) -> tuple[int, str]:
    """Run check_score_artifact_consistency.py against a manifest file."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "check_score_artifact_consistency.py"),
            manifest_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode, result.stdout + result.stderr


def test_consistent_manifest_passes(tmp_path):
    """A manifest whose filename SHA matches release_head and manifest_id must pass."""
    sha = "abc1234def5678901234567890123456789012345"
    short = sha[:7]
    manifest = {
        "manifest_id": f"2026-01-01-{short}-w22",
        "release_head": sha,
        "wave": "W22",
        "current_verified_readiness": 90.0,
    }
    manifest_file = tmp_path / f"platform-release-manifest-2026-01-01-{short}.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    code, out = _run_gate(str(manifest_file))
    assert code == 0, f"Expected PASS (exit 0), got exit {code}:\n{out}"


def test_filename_sha_mismatch_fails(tmp_path):
    """Filename SHA prefix != release_head prefix must cause gate to exit 1."""
    sha = "abc1234def5678901234567890123456789012345"
    wrong_sha = "xyz9999000000000000000000000000000000000"
    # manifest_id and release_head agree on sha, but filename uses wrong_sha
    manifest = {
        "manifest_id": f"2026-01-01-{sha[:7]}-w22",
        "release_head": sha,
        "wave": "W22",
        "current_verified_readiness": 90.0,
    }
    # Filename uses wrong_sha prefix
    manifest_file = (
        tmp_path / f"platform-release-manifest-2026-01-01-{wrong_sha[:7]}.json"
    )
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    code, out = _run_gate(str(manifest_file))
    assert code != 0, f"Expected FAIL (non-zero exit), got exit {code}:\n{out}"


def test_manifest_id_sha_mismatch_fails(tmp_path):
    """manifest_id SHA prefix != release_head prefix must cause gate to exit 1."""
    sha = "abc1234def5678901234567890123456789012345"
    other_sha = "xyz9999000000000000000000000000000000000"
    # manifest_id uses other_sha but release_head uses sha; filename uses other_sha
    manifest = {
        "manifest_id": f"2026-01-01-{other_sha[:7]}-w22",
        "release_head": sha,
        "wave": "W22",
        "current_verified_readiness": 90.0,
    }
    manifest_file = (
        tmp_path / f"platform-release-manifest-2026-01-01-{other_sha[:7]}.json"
    )
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    code, out = _run_gate(str(manifest_file))
    assert code != 0, f"Expected FAIL (non-zero exit), got exit {code}:\n{out}"


def test_missing_release_head_fails(tmp_path):
    """A manifest without release_head must cause gate to exit 1."""
    sha = "abc1234def5678901234567890123456789012345"
    short = sha[:7]
    manifest = {
        "manifest_id": f"2026-01-01-{short}-w22",
        "wave": "W22",
        "current_verified_readiness": 90.0,
        # release_head intentionally absent
    }
    manifest_file = tmp_path / f"platform-release-manifest-2026-01-01-{short}.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    code, out = _run_gate(str(manifest_file))
    assert code != 0, f"Expected FAIL (non-zero exit), got exit {code}:\n{out}"


def test_missing_manifest_id_fails(tmp_path):
    """A manifest without manifest_id must cause gate to exit 1."""
    sha = "abc1234def5678901234567890123456789012345"
    short = sha[:7]
    manifest = {
        "release_head": sha,
        "wave": "W22",
        "current_verified_readiness": 90.0,
        # manifest_id intentionally absent
    }
    manifest_file = tmp_path / f"platform-release-manifest-2026-01-01-{short}.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    code, out = _run_gate(str(manifest_file))
    assert code != 0, f"Expected FAIL (non-zero exit), got exit {code}:\n{out}"


def test_all_releases_dir_passes():
    """Gate must pass (exit 0) when run against the actual docs/releases/ directory."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_score_artifact_consistency.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"Existing manifests in docs/releases/ failed consistency gate:\n"
        f"{result.stdout}\n{result.stderr}"
    )
