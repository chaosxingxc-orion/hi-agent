#!/usr/bin/env python3
"""W17-B19 extension / GOV-C: Manifest budget gate.

Fails when the number of active manifests for the current wave exceeds 3.
'Active' means: manifest JSON in docs/releases/ (NOT in archive/) whose
'wave' field matches the current wave (from docs/current-wave.txt).

The existing check_manifest_rewrite_budget.py counts manifest JSON files in
docs/releases/ by wave; this gate enforces the same ≤3 cap from the opposite
direction (counting active manifests, not rewrites).

Exit 0: pass (≤3 active manifests for current wave)
Exit 1: fail (>3 active manifests)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"
CURRENT_WAVE_FILE = ROOT / "docs" / "current-wave.txt"
_MAX_MANIFESTS = 3


def _current_wave() -> str:
    try:
        return CURRENT_WAVE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Manifest budget gate (≤3 per wave).")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    wave = _current_wave()
    if not wave:
        result = {
            "check": "manifest_budget",
            "status": "not_applicable",
            "reason": "current-wave.txt unreadable",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 0

    if not RELEASES_DIR.exists():
        result = {
            "check": "manifest_budget",
            "status": "not_applicable",
            "reason": "docs/releases/ not found",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 0

    active: list[str] = []
    # Only scan direct children of docs/releases/ — not archive/
    for f in RELEASES_DIR.glob("platform-release-manifest-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if str(data.get("wave", "")).strip() == wave:
            active.append(f.name)

    status = "pass" if len(active) <= _MAX_MANIFESTS else "fail"
    result = {
        "check": "manifest_budget",
        "status": status,
        "current_wave": wave,
        "active_count": len(active),
        "max_allowed": _MAX_MANIFESTS,
        "active_manifests": sorted(active),
        "reason": (
            f"{len(active)} active manifests for W{wave} (≤{_MAX_MANIFESTS} allowed)"
            if status == "fail"
            else f"{len(active)} active manifests for W{wave} — within budget"
        ),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if status == "fail":
            print(
                f"FAIL: {len(active)} active manifests for W{wave} (budget = {_MAX_MANIFESTS}): "
                f"{', '.join(sorted(active))}",
                file=sys.stderr,
            )
        else:
            print(f"PASS: {len(active)}/{_MAX_MANIFESTS} active manifests for W{wave}")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
