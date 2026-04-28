"""Tests for scripts/check_untracked_release_artifacts.py.

Covers the new W17 anti-loop gate that detects uncommitted manifests/
verification artifacts outside the archive/ subdirectory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_no_untracked_returns_pass(monkeypatch, capsys):
    import check_untracked_release_artifacts as mod

    monkeypatch.setattr(mod, "_git_status_porcelain", lambda: [])
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["status"] == "pass"
    assert data["untracked_total"] == 0


def test_untracked_manifest_fails(monkeypatch, capsys):
    import check_untracked_release_artifacts as mod

    monkeypatch.setattr(
        mod,
        "_git_status_porcelain",
        lambda: [("??", "docs/releases/platform-release-manifest-2026-04-29-deadbef.json")],
    )
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 1
    assert data["status"] == "fail"
    assert data["untracked_total"] == 1


def test_archive_subpath_exempt(monkeypatch, capsys):
    import check_untracked_release_artifacts as mod

    monkeypatch.setattr(
        mod,
        "_git_status_porcelain",
        lambda: [
            ("??", "docs/releases/archive/W17/platform-release-manifest-2026-04-28-old.json"),
            ("??", "docs/verification/archive/W17/old-spine.json"),
        ],
    )
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["status"] == "pass"


def test_modified_tracked_files_ignored(monkeypatch, capsys):
    """Modified-but-tracked files (status M, AM, etc.) are not the gate's concern."""
    import check_untracked_release_artifacts as mod

    monkeypatch.setattr(
        mod,
        "_git_status_porcelain",
        lambda: [
            (" M", "docs/releases/platform-release-manifest-2026-04-28-x.json"),
            ("AM", "docs/verification/y-spine.json"),
        ],
    )
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["untracked_total"] == 0


def test_mixed_tracked_and_untracked_isolates_untracked(monkeypatch, capsys):
    import check_untracked_release_artifacts as mod

    monkeypatch.setattr(
        mod,
        "_git_status_porcelain",
        lambda: [
            ("??", "docs/releases/platform-release-manifest-2026-04-29-NEW.json"),
            (" M", "docs/releases/README.md"),
            ("??", "docs/verification/archive/W17/old.json"),  # exempt
        ],
    )
    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 1
    assert data["untracked_total"] == 1
    assert data["untracked_paths"] == [
        "docs/releases/platform-release-manifest-2026-04-29-NEW.json"
    ]
