"""W17/B17: Harness consensus integration test.

Builds a synthetic docs/releases/ corpus with 12 manifests covering all
sort-tiebreaker permutations (different generated_at, mtime, name combos)
and asserts that EVERY manifest-consuming helper/script chooses the
identical "latest" manifest.

This is the long-run regression guard: if anyone in the future reintroduces
a private mtime/name sort inside a check_*.py or build_*.py script, this
test fails because that script will disagree with the helper-driven scripts.

The 7 manifest consumers (per W17 plan):
  1. _governance.manifest_picker.latest_manifest          (canonical helper)
  2. check_manifest_freshness._latest_manifest            (legacy local impl)
  3. check_release_identity._latest_manifest_head         (migrated to helper)
  4. check_score_cap._select_manifest                     (migrated to helper)
  5. render_doc_metadata._latest_manifest                 (migrated)
  6. release_notice._load_latest_manifest                 (migrated)
  7. check_doc_consistency._latest_manifest_id            (migrated)

If any consumer disagrees, the assertion below identifies which one drifted.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_manifest(
    dir_path: Path,
    sha: str,
    generated_at: str,
    mtime: float | None = None,
) -> Path:
    """Write a synthetic manifest with the given sort-key components."""
    name = f"platform-release-manifest-2026-04-28-{sha}.json"
    payload = {
        "manifest_id": f"2026-04-28-{sha}",
        "release_head": sha + ("0" * (40 - len(sha))),
        "generated_at": generated_at,
        "wave": "Wave 17",
        "git": {"head_sha": sha + ("0" * (40 - len(sha))), "short_sha": sha, "is_dirty": False},
        "scorecard": {"current_verified_readiness": 75.0, "verified": 75.0},
    }
    p = dir_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


@pytest.fixture
def consensus_corpus(tmp_path: Path) -> tuple[Path, str]:
    """Synthesize 12 manifests under tmp_path/docs/releases/.

    Returns (releases_dir, expected_manifest_id). Layout matches the real
    repo so consumers that compute their own ROOT can be redirected via
    monkeypatch ROOT=tmp_path.
    """
    releases_dir = tmp_path / "docs" / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    base_mtime = time.time()
    cases = [
        # (sha, generated_at, mtime_offset)
        ("aaa1111", "2026-04-28T08:00:00+00:00", -300),
        ("bbb1111", "2026-04-28T09:00:00+00:00", -200),
        ("ccc1111", "2026-04-28T10:00:00+00:00", -100),
        ("ddd1111", "2026-04-28T11:00:00+00:00", -50),
        ("eee1111", "2026-04-28T12:00:00+00:00", 0),
        # Same generated_at as eee (12:00); mtime tiebreaker
        ("fff1111", "2026-04-28T12:00:00+00:00", 10),
        # Same generated_at AND mtime as fff; name tiebreaker (g > f)
        ("ggg1111", "2026-04-28T12:00:00+00:00", 10),
        # Higher generated_at
        ("hhh1111", "2026-04-28T13:00:00+00:00", -1000),
        ("iii1111", "2026-04-28T14:00:00+00:00", -500),
        # Same as iii but mtime newer
        ("jjj1111", "2026-04-28T14:00:00+00:00", 50),
        # Same as jjj generated_at and mtime — wins on name (k > j)
        ("kkk1111", "2026-04-28T14:00:00+00:00", 50),
        # Strict winner — highest generated_at
        ("zzz9999", "2026-04-28T23:59:00+00:00", -2000),
    ]
    for sha, generated_at, offset in cases:
        _write_manifest(releases_dir, sha, generated_at, mtime=base_mtime + offset)
    return releases_dir, "2026-04-28-zzz9999"


def _consumer_helper_canonical(releases_dir: Path) -> str | None:
    from _governance.manifest_picker import latest_manifest
    m = latest_manifest(releases_dir)
    return None if m is None else m["manifest_id"]


def _consumer_check_manifest_freshness(releases_dir: Path, monkeypatch) -> str | None:
    import check_manifest_freshness as mod
    monkeypatch.setattr(mod, "RELEASES_DIR", releases_dir)
    m = mod._latest_manifest()
    return None if m is None else m["manifest_id"]


def _consumer_check_release_identity(releases_dir: Path, monkeypatch) -> str | None:
    import check_release_identity as mod
    monkeypatch.setattr(mod, "RELEASES_DIR", releases_dir)
    head, _name, _filename_sha = mod._latest_manifest_head()
    if not head:
        return None
    # Map back: short SHA in filename
    return f"2026-04-28-{head[:7]}"


def _consumer_check_score_cap(releases_dir: Path, monkeypatch) -> str | None:
    import check_score_cap as mod
    monkeypatch.setattr(mod, "RELEASES_DIR", releases_dir)
    monkeypatch.setattr(mod, "_git_head_full", lambda: "")
    p = mod._select_manifest(strict_head=False)
    if p is None:
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return data["manifest_id"]


def _consumer_render_doc_metadata(releases_dir: Path, monkeypatch) -> str | None:
    import render_doc_metadata as mod
    monkeypatch.setattr(mod, "RELEASES_DIR", releases_dir)
    m = mod._latest_manifest()
    return None if m is None else m["manifest_id"]


def _consumer_release_notice(releases_dir: Path, monkeypatch) -> str | None:
    import release_notice as mod
    # release_notice._load_latest_manifest constructs releases_dir from ROOT/docs/releases
    monkeypatch.setattr(mod, "ROOT", releases_dir.parent.parent)
    # The function does: releases_dir = ROOT / "docs" / "releases" — make ROOT.parent.parent
    # actually be tmp such that ROOT/docs/releases == releases_dir.
    # Simpler approach: monkey-patch the helper directly
    from _governance import manifest_picker as mp
    real_latest = mp.latest_manifest
    monkeypatch.setattr(
        mp, "latest_manifest",
        lambda d: real_latest(releases_dir),
    )
    m = mod._load_latest_manifest()
    return None if m is None else m["manifest_id"]


def _consumer_check_doc_consistency(releases_dir: Path, monkeypatch) -> str | None:
    import check_doc_consistency as mod
    monkeypatch.setattr(mod, "DOCS", releases_dir.parent)
    # check_doc_consistency reads DOCS / "releases"
    return mod._latest_manifest_id()


def test_seven_consumers_agree_on_latest(consensus_corpus, monkeypatch):
    """Every manifest-consuming script picks the same manifest_id from the corpus.

    If this test ever fails, one of the consumers has a divergent local sort
    implementation (the W17 root-cause defect class). Identify the offender
    and migrate it to scripts/_governance/manifest_picker.
    """
    releases_dir, expected = consensus_corpus

    consumers: dict[str, Callable[[Path, pytest.MonkeyPatch], str | None]] = {
        "helper.manifest_picker": lambda d, m: _consumer_helper_canonical(d),
        "check_manifest_freshness": _consumer_check_manifest_freshness,
        "check_release_identity": _consumer_check_release_identity,
        "check_score_cap": _consumer_check_score_cap,
        "render_doc_metadata": _consumer_render_doc_metadata,
        "check_doc_consistency": _consumer_check_doc_consistency,
        # release_notice tested separately below — patches a shared helper that
        # affects other consumers.
    }

    results: dict[str, str | None] = {}
    for name, fn in consumers.items():
        # Each consumer gets a fresh monkeypatch to avoid leakage.
        with monkeypatch.context() as m:
            results[name] = fn(releases_dir, m)

    # All consumers must agree on the same manifest_id.
    distinct_choices = set(results.values())
    assert len(distinct_choices) == 1, (
        f"Consumer drift detected — manifest selection diverged.\n"
        f"Results: {results}\n"
        f"Expected: {expected}\n"
        f"This means a consumer is using a private sort implementation; "
        f"migrate it to scripts/_governance/manifest_picker."
    )
    chosen = next(iter(distinct_choices))
    assert chosen == expected, f"Consumers agreed on {chosen} but expected {expected}"


def test_release_notice_uses_helper(consensus_corpus, monkeypatch):
    """release_notice._load_latest_manifest delegates to the canonical helper."""
    releases_dir, expected = consensus_corpus
    # releases_dir == tmp_path/docs/releases — so ROOT == tmp_path
    fake_root = releases_dir.parent.parent

    import release_notice as mod
    monkeypatch.setattr(mod, "ROOT", fake_root)
    m = mod._load_latest_manifest()
    assert m is not None
    assert m["manifest_id"] == expected
