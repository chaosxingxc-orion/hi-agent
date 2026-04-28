"""Single source of truth for selecting the "latest" release manifest.

Sort key: (generated_at, mtime, name)
  - generated_at is the JSON field set by build_release_manifest at write time;
    primary because it reflects causality, not filesystem accidents.
  - mtime is the filesystem modification time; secondary to handle the rare
    case where two manifests share an identical generated_at string.
  - name is the filename; deterministic tertiary tiebreaker.

Why this matters: at least 7 callers historically used divergent sort keys,
producing inconsistent "latest" selections (e.g. check_score_cap saw one
manifest while render_doc_metadata saw another). All callers must import from
here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MANIFEST_GLOB = "platform-release-manifest-*.json"


def all_manifests(releases_dir: Path) -> list[dict[str, Any]]:
    """Return all manifests under releases_dir, sorted ascending by (generated_at, mtime, name).

    Last element is the latest. Each dict has an injected "_path" field.
    Malformed JSON files are skipped silently.
    """
    candidates: list[tuple[str, float, str, Path, dict[str, Any]]] = []
    for p in Path(releases_dir).glob(MANIFEST_GLOB):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        generated_at = str(data.get("generated_at", ""))
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((generated_at, mtime, p.name, p, data))
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    out: list[dict[str, Any]] = []
    for _, _, _, path, data in candidates:
        data["_path"] = str(path)
        out.append(data)
    return out


def latest_manifest(releases_dir: Path) -> dict[str, Any] | None:
    """Return the latest manifest dict, or None if directory has none."""
    items = all_manifests(releases_dir)
    return items[-1] if items else None


def latest_manifest_path(releases_dir: Path) -> Path | None:
    """Return the path of the latest manifest, or None if directory has none."""
    latest = latest_manifest(releases_dir)
    return Path(latest["_path"]) if latest else None


def manifest_for_sha(sha: str, releases_dir: Path) -> dict[str, Any] | None:
    """Find the manifest whose release_head matches sha (full or prefix).

    Match rules:
      - sha equal to release_head exactly, OR
      - release_head starts with sha (sha is a short prefix), OR
      - sha starts with release_head[:len(sha)] (release_head is shorter than sha).

    If multiple match, returns the latest (by sort key).
    """
    if not sha:
        return None
    matches: list[dict[str, Any]] = []
    for m in all_manifests(releases_dir):
        head = str(m.get("release_head") or m.get("git", {}).get("head_sha", ""))
        if not head:
            continue
        if head == sha or head.startswith(sha) or sha.startswith(head[: len(sha)]):
            matches.append(m)
    return matches[-1] if matches else None
