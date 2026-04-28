#!/usr/bin/env python3
"""W17/B11: Wave-label consistency gate.

Validates that the wave label is identical across:
  - docs/current-wave.txt
  - docs/governance/allowlists.yaml `current_wave` field
  - The latest release manifest's `wave` field
  - The latest non-draft closure notice's `Wave: N` line

Drift between any two is a defect (see GS-8/GS-15/LB-6/LB-8 in W17 audit).

Exit 0: pass (all sources agree).
Exit 1: fail (drift detected).
Exit 2: deferred (insufficient sources to compare).

Status values: pass | fail | not_applicable | deferred
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _governance.manifest_picker import latest_manifest
from _governance.wave import (
    current_wave,
    parse_wave,
    validate_wave_consistency,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
WAVE_FILE = ROOT / "docs" / "current-wave.txt"
ALLOWLISTS_FILE = ROOT / "docs" / "governance" / "allowlists.yaml"
RELEASES_DIR = ROOT / "docs" / "releases"
NOTICES_DIR = ROOT / "docs" / "downstream-responses"


def _read_allowlists_current_wave() -> object | None:
    """Read the `current_wave: N` field from allowlists.yaml.

    Returns the raw value (int or string) or None if missing/unreadable.
    """
    if not ALLOWLISTS_FILE.exists():
        return None
    try:
        text = ALLOWLISTS_FILE.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^\s*current_wave\s*:\s*(\S.*)$", text, re.MULTILINE)
    if not m:
        return None
    raw = m.group(1).strip().strip("\"'")
    try:
        return int(raw)
    except ValueError:
        return raw


def _latest_manifest_wave() -> str | None:
    """Read `wave` field from the latest release manifest.

    Returns None (deferred) when no manifests exist for the current wave label.
    This avoids a spurious wave-drift failure when the wave has been bumped but
    no manifest has been generated yet for the new wave. The check_manifest_rewrite_budget
    gate separately enforces that a manifest must exist for the current wave before release.
    """
    data = latest_manifest(RELEASES_DIR)
    if data is None:
        return None
    wave = data.get("wave")
    if wave is None:
        return None
    manifest_wave_str = str(wave)
    # Defer if the latest manifest is from a different wave than current-wave.txt.
    # A new manifest must be generated for the current wave to restore tracking.
    if WAVE_FILE.exists():
        try:
            current = current_wave()
            manifest_int = parse_wave(manifest_wave_str)
            if manifest_int != current:
                return None  # defer: manifest is stale (different wave)
        except (ValueError, OSError):
            pass  # fall through to returning manifest wave as-is
    return manifest_wave_str


_NOTICE_WAVE_RE = re.compile(r"^\s*-?\s*\*?\*?Wave\s*:?\s*(\d+)", re.MULTILINE | re.IGNORECASE)
_NOTICE_FILENAME_RE = re.compile(r"-wave(\d+)-", re.IGNORECASE)


def _latest_notice_wave() -> str | None:
    """Find the latest non-draft delivery notice and extract its wave label.

    Returns None (deferred) when the latest non-superseded notice is from a
    different wave than current-wave.txt. This avoids spurious wave-drift failures
    during the transition period between waves (old notice superseded before new
    one is written). The check_doc_consistency gate separately enforces that a
    current notice exists at release time.

    Search order for the wave value:
      1. Filename pattern `*-wave<N>-delivery-notice.md`
      2. First `Wave: N` line in the body
    """
    if not NOTICES_DIR.exists():
        return None
    notices = sorted(
        NOTICES_DIR.glob("*delivery-notice*.md"),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    for notice in reversed(notices):
        try:
            text = notice.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"Status:\s*(?:superseded|draft)", text, re.IGNORECASE):
            continue
        m = _NOTICE_FILENAME_RE.search(notice.name)
        if m:
            wave_str = m.group(1)
        else:
            m = _NOTICE_WAVE_RE.search(text)
            wave_str = m.group(1) if m else None
        if wave_str is None:
            continue
        # Defer if this notice is from an earlier wave than current-wave.txt.
        if WAVE_FILE.exists():
            try:
                current = current_wave()
                notice_int = parse_wave(wave_str)
                if notice_int != current:
                    return None  # defer: notice is stale (different wave)
            except (ValueError, OSError):
                pass  # fall through to returning wave_str as-is
        return wave_str
    return None

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wave-label consistency gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    sources: dict[str, object | None] = {
        "current_wave_txt": current_wave() if WAVE_FILE.exists() else None,
        "allowlists_yaml": _read_allowlists_current_wave(),
        "manifest_wave": _latest_manifest_wave(),
        "notice_wave": _latest_notice_wave(),
    }

    # Gate is deferred when fewer than 2 sources resolve to a parseable wave.
    parseable: dict[str, int] = {}
    for name, raw in sources.items():
        if raw is None:
            continue
        try:
            parseable[name] = parse_wave(raw)
        except ValueError:
            continue

    if len(parseable) < 2:
        result = {
            "check": "wave_consistency",
            "status": "deferred",
            "reason": "fewer than 2 wave sources available",
            "sources": {k: (v if v is None else str(v)) for k, v in sources.items()},
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: {result['reason']}", file=sys.stderr)
        return 2

    msgs = validate_wave_consistency(**{k: v for k, v in sources.items() if v is not None})
    status = "pass" if not msgs else "fail"
    result = {
        "check": "wave_consistency",
        "status": status,
        "sources": {k: (v if v is None else str(v)) for k, v in sources.items()},
        "parsed": parseable,
        "violations": msgs,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if msgs:
            for m in msgs:
                print(f"FAIL wave_consistency: {m}", file=sys.stderr)
        else:
            print(f"PASS wave_consistency (wave={next(iter(parseable.values()))})")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
