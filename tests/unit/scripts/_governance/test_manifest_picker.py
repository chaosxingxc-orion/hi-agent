"""TDD tests for scripts/_governance/manifest_picker.

Single source of truth for "latest manifest" selection. Tests cover:
- generated_at as primary sort key (NOT mtime alone, NOT name alone)
- mtime as secondary tiebreaker when generated_at is identical
- name as tertiary tiebreaker
- empty directory returns None
- malformed manifest files are skipped, not raised
- manifest_for_sha matches by release_head field, not filename
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from scripts._governance import manifest_picker


def _write_manifest(
    dir_path: Path,
    sha: str,
    generated_at: str,
    *,
    extra: dict | None = None,
) -> Path:
    name = f"platform-release-manifest-2026-04-28-{sha}.json"
    payload = {
        "manifest_id": f"2026-04-28-{sha}",
        "release_head": sha + ("0" * (40 - len(sha))),
        "generated_at": generated_at,
        "git": {"head_sha": sha + ("0" * (40 - len(sha))), "short_sha": sha, "is_dirty": False},
    }
    if extra:
        payload.update(extra)
    p = dir_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestLatestManifest:
    def test_returns_none_on_empty_dir(self, tmp_path: Path) -> None:
        assert manifest_picker.latest_manifest(tmp_path) is None
        assert manifest_picker.latest_manifest_path(tmp_path) is None

    def test_picks_by_generated_at_when_mtimes_equal(self, tmp_path: Path) -> None:
        a = _write_manifest(tmp_path, "aaaaaa1", "2026-04-28T10:00:00+00:00")
        b = _write_manifest(tmp_path, "bbbbbb2", "2026-04-28T11:00:00+00:00")
        c = _write_manifest(tmp_path, "ccccccc", "2026-04-28T12:00:00+00:00")
        # Force identical mtimes
        ts = time.time()
        for p in (a, b, c):
            os.utime(p, (ts, ts))
        latest = manifest_picker.latest_manifest(tmp_path)
        assert latest is not None
        assert latest["manifest_id"] == "2026-04-28-ccccccc"

    def test_picks_by_mtime_when_generated_at_equal(self, tmp_path: Path) -> None:
        a = _write_manifest(tmp_path, "aaaaaa1", "2026-04-28T10:00:00+00:00")
        b = _write_manifest(tmp_path, "bbbbbb2", "2026-04-28T10:00:00+00:00")
        # Force a older than b by mtime
        ts = time.time()
        os.utime(a, (ts - 100, ts - 100))
        os.utime(b, (ts, ts))
        latest = manifest_picker.latest_manifest(tmp_path)
        assert latest is not None
        assert latest["manifest_id"] == "2026-04-28-bbbbbb2"

    def test_picks_by_name_when_generated_at_and_mtime_equal(self, tmp_path: Path) -> None:
        a = _write_manifest(tmp_path, "aaaaaa1", "2026-04-28T10:00:00+00:00")
        b = _write_manifest(tmp_path, "bbbbbb2", "2026-04-28T10:00:00+00:00")
        ts = time.time()
        os.utime(a, (ts, ts))
        os.utime(b, (ts, ts))
        # Sort key (generated_at, mtime, name) — b > a by name
        latest = manifest_picker.latest_manifest(tmp_path)
        assert latest is not None
        assert latest["manifest_id"] == "2026-04-28-bbbbbb2"

    def test_skips_malformed_manifest(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "good001", "2026-04-28T10:00:00+00:00")
        bad = tmp_path / "platform-release-manifest-2026-04-28-bad.json"
        bad.write_text("not valid json {{{", encoding="utf-8")
        latest = manifest_picker.latest_manifest(tmp_path)
        assert latest is not None
        assert latest["manifest_id"] == "2026-04-28-good001"

    def test_attaches_path(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, "abc1234", "2026-04-28T10:00:00+00:00")
        latest = manifest_picker.latest_manifest(tmp_path)
        assert latest is not None
        assert Path(latest["_path"]) == p


class TestManifestForSha:
    def test_finds_by_release_head(self, tmp_path: Path) -> None:
        full_sha = "abc1234" + ("0" * 33)
        _write_manifest(tmp_path, "abc1234", "2026-04-28T10:00:00+00:00")
        result = manifest_picker.manifest_for_sha(full_sha, tmp_path)
        assert result is not None
        assert result["release_head"] == full_sha

    def test_finds_by_short_sha_prefix(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "abc1234", "2026-04-28T10:00:00+00:00")
        result = manifest_picker.manifest_for_sha("abc1234", tmp_path)
        assert result is not None

    def test_returns_none_on_no_match(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "abc1234", "2026-04-28T10:00:00+00:00")
        result = manifest_picker.manifest_for_sha("deadbeef", tmp_path)
        assert result is None


class TestAllManifests:
    def test_returns_sorted_list(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "aaa1111", "2026-04-28T10:00:00+00:00")
        _write_manifest(tmp_path, "bbb2222", "2026-04-28T12:00:00+00:00")
        _write_manifest(tmp_path, "ccc3333", "2026-04-28T11:00:00+00:00")
        all_m = manifest_picker.all_manifests(tmp_path)
        assert [m["manifest_id"] for m in all_m] == [
            "2026-04-28-aaa1111",
            "2026-04-28-ccc3333",
            "2026-04-28-bbb2222",
        ]

    def test_returns_empty_on_empty_dir(self, tmp_path: Path) -> None:
        assert manifest_picker.all_manifests(tmp_path) == []
