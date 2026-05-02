"""TDD tests for scripts/_governance/evidence_picker.

Selects the latest verification artifact (operator-drill, soak, observability
spine, chaos matrix). Sort key matches manifest_picker:
  (generated_at field if present, mtime, name)

Avoids the GS-6 anti-pattern of looking up commit timestamps via `git log -1`
which fails in shallow CI clones.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from scripts._governance import evidence_picker


def _write_evidence(
    dir_path: Path,
    sha: str,
    suffix: str,
    *,
    generated_at: str = "",
    head: str = "",
    extra: dict | None = None,
) -> Path:
    name = f"{sha}-{suffix}.json"
    payload: dict = {"sha_in_filename": sha}
    if generated_at:
        payload["generated_at"] = generated_at
    if head:
        payload["head"] = head
    if extra:
        payload.update(extra)
    p = dir_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestLatestEvidence:
    def test_returns_none_on_empty(self, tmp_path: Path) -> None:
        assert evidence_picker.latest_evidence(tmp_path, "*-soak-*.json") is None

    def test_picks_by_generated_at_when_present(self, tmp_path: Path) -> None:
        a = _write_evidence(tmp_path, "aaa1", "soak-60m", generated_at="2026-04-28T10:00:00+00:00")
        b = _write_evidence(tmp_path, "bbb2", "soak-60m", generated_at="2026-04-28T11:00:00+00:00")
        # Force identical mtimes
        ts = time.time()
        os.utime(a, (ts, ts))
        os.utime(b, (ts, ts))
        latest = evidence_picker.latest_evidence(tmp_path, "*-soak-*.json")
        assert latest is not None
        assert latest.name.startswith("bbb2-")

    def test_falls_back_to_mtime_when_no_generated_at(self, tmp_path: Path) -> None:
        a = _write_evidence(tmp_path, "aaa1", "soak-60m")
        b = _write_evidence(tmp_path, "bbb2", "soak-60m")
        ts = time.time()
        os.utime(a, (ts - 100, ts - 100))
        os.utime(b, (ts, ts))
        latest = evidence_picker.latest_evidence(tmp_path, "*-soak-*.json")
        assert latest is not None
        assert latest.name.startswith("bbb2-")

    def test_pattern_filters_correctly(self, tmp_path: Path) -> None:
        _write_evidence(tmp_path, "aaa1", "soak-60m", generated_at="2026-04-28T10:00:00+00:00")
        _write_evidence(tmp_path, "bbb2", "operator-drill", generated_at="2026-04-28T11:00:00+00:00")  # noqa: E501  # expiry_wave: Wave 30
        soak = evidence_picker.latest_evidence(tmp_path, "*-soak-*.json")
        drill = evidence_picker.latest_evidence(tmp_path, "*operator-drill*.json")
        assert soak is not None and soak.name.startswith("aaa1-")
        assert drill is not None and drill.name.startswith("bbb2-")

    def test_picks_by_name_when_all_else_equal(self, tmp_path: Path) -> None:
        a = _write_evidence(tmp_path, "aaaaaaa", "soak-60m")
        b = _write_evidence(tmp_path, "zzzzzzz", "soak-60m")
        ts = time.time()
        os.utime(a, (ts, ts))
        os.utime(b, (ts, ts))
        latest = evidence_picker.latest_evidence(tmp_path, "*-soak-*.json")
        assert latest is not None
        assert latest.name.startswith("zzzzzzz-")

    def test_skips_malformed_json_without_generated_at(self, tmp_path: Path) -> None:
        good = _write_evidence(tmp_path, "good", "soak-60m")
        bad = tmp_path / "bad-soak-60m.json"
        bad.write_text("not valid json", encoding="utf-8")
        # bad file still ranked by mtime/name; should not crash
        latest = evidence_picker.latest_evidence(tmp_path, "*-soak-*.json")
        assert latest is not None
        # Either bad or good wins by mtime/name; test it doesn't crash
        assert latest in {good, bad}


class TestEvidenceForSha:
    def test_finds_by_head_field(self, tmp_path: Path) -> None:
        _write_evidence(tmp_path, "abc123", "operator-drill", head="abc12345")
        result = evidence_picker.evidence_for_sha(
            "abc1234", tmp_path, "*operator-drill*.json"
        )
        assert result is not None
        assert result.name.startswith("abc123-")

    def test_falls_back_to_filename_sha(self, tmp_path: Path) -> None:
        _write_evidence(tmp_path, "abc1234", "operator-drill")  # no head field
        result = evidence_picker.evidence_for_sha(
            "abc1234", tmp_path, "*operator-drill*.json"
        )
        assert result is not None

    def test_returns_none_on_no_match(self, tmp_path: Path) -> None:
        _write_evidence(tmp_path, "abc1234", "operator-drill", head="abc12345")
        result = evidence_picker.evidence_for_sha(
            "deadbeef", tmp_path, "*operator-drill*.json"
        )
        assert result is None

    def test_does_not_call_git(self, tmp_path: Path, monkeypatch) -> None:
        """Critical: no git subprocess (avoids GS-6 short-sha lookup failures)."""
        import subprocess
        original_run = subprocess.run

        def reject_git(args, *a, **kw):
            if args and (args[0] == "git" or (isinstance(args[0], str) and "git" in args[0].lower())):  # noqa: E501  # expiry_wave: Wave 30
                raise AssertionError(f"evidence_picker must not call git: {args}")
            return original_run(args, *a, **kw)

        monkeypatch.setattr(subprocess, "run", reject_git)
        _write_evidence(tmp_path, "abc1234", "operator-drill", head="abc12345")
        result = evidence_picker.evidence_for_sha(
            "abc1234", tmp_path, "*operator-drill*.json"
        )
        assert result is not None


class TestAllEvidence:
    def test_returns_sorted_ascending(self, tmp_path: Path) -> None:
        a = _write_evidence(tmp_path, "aaa1", "soak-60m", generated_at="2026-04-28T10:00:00+00:00")
        b = _write_evidence(tmp_path, "bbb2", "soak-60m", generated_at="2026-04-28T12:00:00+00:00")
        c = _write_evidence(tmp_path, "ccc3", "soak-60m", generated_at="2026-04-28T11:00:00+00:00")
        ts = time.time()
        for p in (a, b, c):
            os.utime(p, (ts, ts))
        result = evidence_picker.all_evidence(tmp_path, "*-soak-*.json")
        assert [p.name.split("-")[0] for p in result] == ["aaa1", "ccc3", "bbb2"]
