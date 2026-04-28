"""Single source of truth for selecting the latest verification artifact.

Used by check_soak_evidence, check_chaos_runtime_coupling,
check_observability_spine_completeness, check_operator_drill, and
check_release_identity (notice sort).

Sort key parallels manifest_picker:
  (generated_at-field-or-empty, mtime, name)

Replaces the GS-6 anti-pattern of looking up commit timestamps via
``git log -1 --format=%ct <short-sha>`` which fails silently on shallow
CI clones and ambiguous short SHAs.

For SHA-keyed lookups (operator-drill style), we read the ``head`` field
inside each JSON file rather than relying on filename or git.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _sort_key(path: Path) -> tuple[str, float, str]:
    data = _read_json(path) or {}
    generated_at = str(data.get("generated_at", ""))
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (generated_at, mtime, path.name)


def all_evidence(verif_dir: Path, pattern: str) -> list[Path]:
    """All evidence files matching pattern, sorted ascending by (generated_at, mtime, name).

    Last element is the latest. Empty list if directory has none or directory missing.
    """
    try:
        files = list(Path(verif_dir).glob(pattern))
    except OSError:
        return []
    files.sort(key=_sort_key)
    return files


def latest_evidence(verif_dir: Path, pattern: str) -> Path | None:
    """Return the latest matching evidence file, or None."""
    files = all_evidence(verif_dir, pattern)
    return files[-1] if files else None


def evidence_for_sha(sha: str, verif_dir: Path, pattern: str) -> Path | None:
    """Find an evidence file whose 'head' field (or filename prefix) matches sha.

    Match rules (in order):
      1. JSON 'head' field equals or shares prefix with sha
      2. Filename starts with sha (handles cases where 'head' field absent)

    If multiple match, returns the one with the latest sort key.
    Does NOT call git (unlike the legacy operator_drill implementation).
    """
    if not sha:
        return None
    matches: list[Path] = []
    for p in all_evidence(verif_dir, pattern):
        data = _read_json(p) or {}
        head = str(data.get("head", ""))
        if head and (head == sha or head.startswith(sha) or sha.startswith(head)):
            matches.append(p)
            continue
        if p.name.startswith(sha):
            matches.append(p)
    return matches[-1] if matches else None
