from __future__ import annotations

import json
from pathlib import Path

from scripts.check_t3_freshness import _extract_sha_from_evidence


def test_freshness_accepts_new_filename_pattern(tmp_path: Path) -> None:
    """check_t3_freshness.py should accept *-t3-*.json filenames."""
    evidence = {"status": "pass", "verified_head": "abc1234", "provider": "volces"}
    f = tmp_path / "2026-04-27-abc1234-t3-volces.json"
    f.write_text(json.dumps(evidence))
    sha = _extract_sha_from_evidence(f, evidence)
    assert sha == "abc1234", f"Expected abc1234, got {sha!r}"


def test_freshness_prefers_verified_head_over_filename(tmp_path: Path) -> None:
    """verified_head field should take precedence over filename SHA."""
    evidence = {"verified_head": "deadbeef12345678", "status": "pass"}
    f = tmp_path / "2026-04-27-aabbccdd-rule15-volces.json"
    f.write_text(json.dumps(evidence))
    sha = _extract_sha_from_evidence(f, evidence)
    assert sha == "deadbeef12345678"


def test_freshness_falls_back_to_filename_sha_for_legacy(tmp_path: Path) -> None:
    """For legacy files without verified_head, parse SHA from filename."""
    evidence = {"status": "pass"}  # no verified_head
    f = tmp_path / "2026-04-25-fa98c7b-rule15-volces-v4.json"
    f.write_text(json.dumps(evidence))
    sha = _extract_sha_from_evidence(f, evidence)
    assert sha == "fa98c7b", f"Expected fa98c7b, got {sha!r}"


def test_freshness_falls_back_to_legacy_sha_field(tmp_path: Path) -> None:
    """Legacy ``sha`` field is used when verified_head is absent."""
    evidence = {"sha": "a1b2c3d", "status": "pass"}
    f = tmp_path / "2026-04-25-00000000-rule15-volces.json"
    f.write_text(json.dumps(evidence))
    sha = _extract_sha_from_evidence(f, evidence)
    assert sha == "a1b2c3d"


def test_freshness_returns_empty_when_no_sha_available(tmp_path: Path) -> None:
    """Returns empty string when neither field nor filename yields a SHA."""
    evidence = {"status": "pass"}
    f = tmp_path / "no-sha-here.json"
    f.write_text(json.dumps(evidence))
    sha = _extract_sha_from_evidence(f, evidence)
    assert sha == ""


def test_freshness_t3_filename_fallback_when_no_field(tmp_path: Path) -> None:
    """Modern *-t3-*.json filename is parsed when verified_head field is absent."""
    evidence = {"status": "pass"}  # no verified_head
    f = tmp_path / "2026-04-27-beef123-t3-anthropic.json"
    f.write_text(json.dumps(evidence))
    sha = _extract_sha_from_evidence(f, evidence)
    assert sha == "beef123", f"Expected beef123, got {sha!r}"
