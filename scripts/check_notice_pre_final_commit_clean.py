#!/usr/bin/env python3
"""W29: Notice pre-final-commit cleanliness gate.

Per Rule 14, the closure notice is published in the LAST atomic commit
alongside the manifest and signoff. A notice marked
`notice-pre-final-commit: true` was published BEFORE the final commit
existed -- the exact root cause of the W28 release-identity break, where
the manifest's `release_head` and the actual `git rev-parse HEAD` diverged.

This gate fails when the latest ACTIVE delivery notice (the one
`check_release_identity.py` would treat as authoritative) carries the
`notice-pre-final-commit: true` marker. Historical notices that have been
marked `Status: superseded` or `Status: draft` are skipped, preserving the
audit trail without permitting the escape hatch to fire on the current
release.

Exit 0: pass (latest active notice does not carry the marker)
Exit 1: fail (latest active notice carries the marker)
Exit 2: deferred (no active notices found)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTICES_DIR = ROOT / "docs" / "downstream-responses"

_SUPERSEDED_RE = re.compile(r"Status:\s*(?:superseded|draft)", re.IGNORECASE)
_MARKER_RE = re.compile(r"^notice-pre-final-commit:\s*true\b", re.MULTILINE)


def _latest_active_notice() -> tuple[pathlib.Path, str] | None:
    if not NOTICES_DIR.is_dir():
        return None
    notices = sorted(
        NOTICES_DIR.glob("*.md"),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    for notice in reversed(notices):
        text = notice.read_text(encoding="utf-8", errors="replace")
        if _SUPERSEDED_RE.search(text):
            continue
        return notice, text
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Notice pre-final-commit gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    latest = _latest_active_notice()
    if latest is None:
        result = {
            "check": "notice_pre_final_commit_clean",
            "status": "deferred",
            "reason": "no active delivery notice found",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: no active delivery notice", file=sys.stderr)
        return 2

    notice, text = latest
    violations: list[str] = []
    if _MARKER_RE.search(text):
        violations.append(notice.name)

    status = "pass" if not violations else "fail"
    result = {
        "check": "notice_pre_final_commit_clean",
        "status": status,
        "latest_active_notice": notice.name,
        "violations": violations,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if violations:
            print(
                f"FAIL: {notice.name} carries 'notice-pre-final-commit: true'.",
                file=sys.stderr,
            )
            print(
                "Per Rule 14, the closure notice ships in the final atomic commit "
                "(manifest + notice + signoff). Either:",
                file=sys.stderr,
            )
            print(
                "  - Mark this notice 'Status: superseded' if no longer authoritative,",
                file=sys.stderr,
            )
            print(
                "  - Or remove the 'notice-pre-final-commit: true' field and re-publish at HEAD.",
                file=sys.stderr,
            )
        else:
            print(f"PASS: {notice.name} does not carry the pre-final-commit marker")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
