"""Tests for scripts/check_wave_consistency.py.

Covers the new W17 anti-loop gate that detects wave-label drift across
current-wave.txt, allowlists.yaml, latest manifest, and latest notice.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_wave(tmp_path: Path, label: str) -> Path:
    p = tmp_path / "current-wave.txt"
    p.write_text(label + "\n", encoding="utf-8")
    return p


def _write_allowlists(tmp_path: Path, current_wave: int) -> Path:
    p = tmp_path / "allowlists.yaml"
    p.write_text(
        f"schema_version: \"1\"\ncurrent_wave: {current_wave}\nentries: []\n",
        encoding="utf-8",
    )
    return p


def _write_manifest(dir_path: Path, sha: str, wave: str, generated_at: str) -> Path:
    name = f"platform-release-manifest-2026-04-28-{sha}.json"
    payload = {
        "manifest_id": f"2026-04-28-{sha}",
        "release_head": sha + ("0" * (40 - len(sha))),
        "generated_at": generated_at,
        "wave": wave,
        "git": {"head_sha": sha + ("0" * (40 - len(sha))), "short_sha": sha, "is_dirty": False},
    }
    p = dir_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _write_notice(dir_path: Path, name: str, wave_n: int, *, status: str | None = None) -> Path:
    parts = [f"# Wave {wave_n} delivery"]
    if status:
        parts.append(f"\nStatus: {status}\n")
    parts.append(f"\nWave: {wave_n}\n\nFunctional HEAD: abc1234\n")
    p = dir_path / name
    p.write_text("\n".join(parts), encoding="utf-8")
    return p


def test_all_sources_agree_returns_pass(tmp_path, monkeypatch, capsys):
    import check_wave_consistency as mod

    wave_file = _write_wave(tmp_path, "Wave 17")
    allowlists = _write_allowlists(tmp_path, 17)
    releases = tmp_path / "releases"
    releases.mkdir()
    _write_manifest(releases, "abc1234", "Wave 17", "2026-04-28T10:00:00+00:00")
    notices = tmp_path / "notices"
    notices.mkdir()
    _write_notice(notices, "2026-04-28-wave17-delivery-notice.md", 17)

    monkeypatch.setattr(mod, "WAVE_FILE", wave_file)
    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", allowlists)
    monkeypatch.setattr(mod, "RELEASES_DIR", releases)
    monkeypatch.setattr(mod, "NOTICES_DIR", notices)
    # Patch the wave helper's file pointer so current_wave() reads the tmp file
    from _governance import wave as wave_mod
    monkeypatch.setattr(wave_mod, "_WAVE_FILE", wave_file)

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["status"] == "pass"


def test_manifest_from_earlier_wave_is_deferred(tmp_path, monkeypatch, capsys):
    """When the only manifest is from an earlier wave, manifest_wave is deferred.

    W18-C1-d: Wave bumps happen before a new manifest is generated. This is
    an expected bootstrap gap — check_manifest_rewrite_budget tracks it separately.
    The wave_consistency check must not fail during this window.
    """
    import check_wave_consistency as mod

    wave_file = _write_wave(tmp_path, "Wave 17")
    allowlists = _write_allowlists(tmp_path, 17)
    releases = tmp_path / "releases"
    releases.mkdir()
    _write_manifest(releases, "abc1234", "Wave 14", "2026-04-28T10:00:00+00:00")  # stale wave
    notices = tmp_path / "notices"
    notices.mkdir()
    _write_notice(notices, "2026-04-28-wave17-delivery-notice.md", 17)

    monkeypatch.setattr(mod, "WAVE_FILE", wave_file)
    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", allowlists)
    monkeypatch.setattr(mod, "RELEASES_DIR", releases)
    monkeypatch.setattr(mod, "NOTICES_DIR", notices)
    from _governance import wave as wave_mod
    monkeypatch.setattr(wave_mod, "_WAVE_FILE", wave_file)

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # Manifest from earlier wave is excluded from comparison — remaining sources agree
    assert rc == 0
    assert data["status"] == "pass"
    # manifest_wave should appear as None (deferred) in sources
    assert data["sources"]["manifest_wave"] is None


def test_drift_detected_returns_fail(tmp_path, monkeypatch, capsys):
    """Wave drift among same-generation sources returns fail."""
    import check_wave_consistency as mod

    wave_file = _write_wave(tmp_path, "Wave 17")
    allowlists = _write_allowlists(tmp_path, 16)  # DRIFT: allowlists says 16, txt says 17
    releases = tmp_path / "releases"
    releases.mkdir()
    _write_manifest(releases, "abc1234", "Wave 17", "2026-04-28T10:00:00+00:00")  # matches current
    notices = tmp_path / "notices"
    notices.mkdir()
    _write_notice(notices, "2026-04-28-wave17-delivery-notice.md", 17)

    monkeypatch.setattr(mod, "WAVE_FILE", wave_file)
    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", allowlists)
    monkeypatch.setattr(mod, "RELEASES_DIR", releases)
    monkeypatch.setattr(mod, "NOTICES_DIR", notices)
    from _governance import wave as wave_mod
    monkeypatch.setattr(wave_mod, "_WAVE_FILE", wave_file)

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 1
    assert data["status"] == "fail"
    assert any("drift" in v for v in data["violations"])


def test_skips_draft_notice(tmp_path, monkeypatch, capsys):
    """Draft notices should not contribute to wave consistency."""
    import check_wave_consistency as mod

    wave_file = _write_wave(tmp_path, "Wave 17")
    allowlists = _write_allowlists(tmp_path, 17)
    releases = tmp_path / "releases"
    releases.mkdir()
    _write_manifest(releases, "abc1234", "Wave 17", "2026-04-28T10:00:00+00:00")
    notices = tmp_path / "notices"
    notices.mkdir()
    # Draft says wave 99 — must be ignored
    _write_notice(notices, "2026-04-28-wave99-delivery-notice.md", 99, status="draft")
    _write_notice(notices, "2026-04-28-wave17-delivery-notice.md", 17)

    monkeypatch.setattr(mod, "WAVE_FILE", wave_file)
    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", allowlists)
    monkeypatch.setattr(mod, "RELEASES_DIR", releases)
    monkeypatch.setattr(mod, "NOTICES_DIR", notices)
    from _governance import wave as wave_mod
    monkeypatch.setattr(wave_mod, "_WAVE_FILE", wave_file)

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["status"] == "pass"


def test_insufficient_sources_returns_deferred(tmp_path, monkeypatch, capsys):
    """When fewer than 2 sources resolve, the gate defers (not fails)."""
    import check_wave_consistency as mod

    wave_file = _write_wave(tmp_path, "Wave 17")
    # No allowlists, no manifests, no notices

    monkeypatch.setattr(mod, "WAVE_FILE", wave_file)
    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", tmp_path / "no-allowlists.yaml")
    monkeypatch.setattr(mod, "RELEASES_DIR", tmp_path / "no-releases")
    monkeypatch.setattr(mod, "NOTICES_DIR", tmp_path / "no-notices")
    from _governance import wave as wave_mod
    monkeypatch.setattr(wave_mod, "_WAVE_FILE", wave_file)

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 2
    assert data["status"] == "deferred"

def test_notice_from_earlier_wave_is_deferred(tmp_path, monkeypatch, capsys):
    """When the only non-superseded notice is from an earlier wave, notice_wave is deferred.

    W18-C1-d: Wave bumps happen before a new notice is written. This is
    an expected bootstrap gap — check_doc_consistency tracks it separately.
    """
    import check_wave_consistency as mod

    wave_file = _write_wave(tmp_path, "Wave 18")
    allowlists = _write_allowlists(tmp_path, 18)
    releases = tmp_path / "releases"
    releases.mkdir()
    _write_manifest(releases, "abc1234", "Wave 18", "2026-04-29T10:00:00+00:00")
    notices = tmp_path / "notices"
    notices.mkdir()
    # Wave 17 notice is superseded; no Wave 18 notice exists yet
    _write_notice(notices, "2026-04-28-wave17-delivery-notice.md", 17, status="superseded")

    monkeypatch.setattr(mod, "WAVE_FILE", wave_file)
    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", allowlists)
    monkeypatch.setattr(mod, "RELEASES_DIR", releases)
    monkeypatch.setattr(mod, "NOTICES_DIR", notices)
    from _governance import wave as wave_mod
    monkeypatch.setattr(wave_mod, "_WAVE_FILE", wave_file)

    rc = mod.main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # Only superseded notice exists; notice_wave is deferred — remaining sources agree
    assert rc == 0, f"Expected pass but got: {data}"
    assert data["status"] == "pass"
    assert data["sources"]["notice_wave"] is None
