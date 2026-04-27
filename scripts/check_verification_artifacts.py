#!/usr/bin/env python3
"""CI gate: fail if verification artifacts are stale vs current HEAD.

Walks docs/verification/*.json and docs/delivery/*.json.
For each file, checks if its 'release_head' or 'verified_head' field matches
the current git HEAD. Emits 'verification_artifacts.has_stale' flag.

Exit 0: all artifacts current (or no artifacts found).
Exit 1: one or more stale artifacts detected.
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


def _check_artifacts() -> tuple[list[str], list[str]]:
    """Return (stale_files, checked_files)."""
    head = _git_head()
    stale: list[str] = []
    checked: list[str] = []

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
                or ""
            )
            if not artifact_head:
                continue
            checked.append(str(f.relative_to(ROOT)))
            # Compare: artifact_head must start with head or vice versa (short/long SHA comparison)
            if head != "unknown" and artifact_head and not (
                head.startswith(artifact_head[: len(head)])
                or artifact_head.startswith(head[: len(artifact_head)])
            ):
                stale.append(str(f.relative_to(ROOT)))

    return stale, checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    stale, checked = _check_artifacts()
    has_stale = bool(stale)

    if args.json_output:
        print(
            json.dumps(
                {
                    "check": "verification_artifacts",
                    "status": "fail" if has_stale else "pass",
                    "has_stale": has_stale,
                    "stale_files": stale,
                    "checked_count": len(checked),
                },
                indent=2,
            )
        )
        return 1 if has_stale else 0

    if has_stale:
        print(f"FAIL verification_artifacts: {len(stale)} stale artifact(s): {stale}")
        return 1

    print(f"OK verification_artifacts: {len(checked)} artifact(s) checked, all current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
