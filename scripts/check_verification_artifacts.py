#!/usr/bin/env python3
"""CI gate: verify that current HEAD has at least one verification artifact.

Walks docs/verification/*.json and docs/delivery/*.json.
Passes when at least one artifact's 'release_head' or 'verified_head' matches
the current git HEAD (short or full SHA prefix).

Historical artifacts from prior HEADs are normal record-keeping — they are NOT
treated as "stale". The gate only fails when NO fresh artifact exists for the
current HEAD.

Exit 0: at least one current artifact found.
Exit 1: no artifact for current HEAD found (or checked_count==0).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(ROOT)
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _sha_matches(artifact_head: str, head: str) -> bool:
    if not artifact_head or not head or head == "unknown":
        return False
    min_len = min(len(artifact_head), len(head))
    return artifact_head[:min_len] == head[:min_len]


def _check_artifacts() -> tuple[list[str], list[str], bool]:
    """Return (checked_files, current_files, has_current_head).

    checked_files: all artifact files that have a SHA field.
    current_files: artifacts whose SHA matches current HEAD.
    has_current_head: True when at least one current artifact exists.
    """
    head = _git_head()
    checked: list[str] = []
    current: list[str] = []

    dirs = [
        ROOT / "docs" / "verification",
        ROOT / "docs" / "delivery",
    ]
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            artifact_head = (
                data.get("release_head")
                or data.get("verified_head")
                or data.get("head_sha")
                or data.get("sha")
                or ""
            )
            if not artifact_head:
                continue
            rel = str(f.relative_to(ROOT))
            checked.append(rel)
            if _sha_matches(artifact_head, head):
                current.append(rel)

    return checked, current, bool(current)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    checked, current, has_current = _check_artifacts()
    status = "pass" if has_current else "fail"

    if args.json_output:
        print(
            json.dumps(
                {
                    "check": "verification_artifacts",
                    "status": status,
                    "has_current_head": has_current,
                    "current_files": current,
                    "checked_count": len(checked),
                },
                indent=2,
            )
        )
        return 0 if has_current else 1

    if has_current:
        print(
            f"OK verification_artifacts: {len(current)} current artifact(s) "
            f"({len(checked)} total checked)"
        )
        return 0

    print(
        f"FAIL verification_artifacts: no artifact for current HEAD "
        f"({len(checked)} total checked, none match HEAD)"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
