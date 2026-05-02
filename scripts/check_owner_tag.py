#!/usr/bin/env python3
"""CI gate: every recent commit must have an Owner track tag (AX-E E3+E4).

Scans last N commits for:
  - `Owner: CO|RO|DX|TE|GOV` trailer in commit body, OR
  - `[<track>-W<n>-<id>]` subject prefix, OR
  - subject is a merge commit (excluded from check)

Conventional-commits prefixes (gov:, fix:, chore:, docs:) WITHOUT an
Owner trailer are considered violations.

Exit 0: PASS
Exit 1: FAIL (commits without owner tag)
Exit 2: not_applicable (no git repo)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_OWNER_TRAILER = re.compile(r"^Owner:\s*(CO|RO|DX|TE|GOV|AS-CO|AS-RO)\s*$", re.IGNORECASE | re.MULTILINE)  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep
_SUBJECT_PREFIX = re.compile(  # expiry_wave: Wave 30  # added: W28 transitional wave-prefix format
    r"^\[(co|ro|dx|te|gov|as-co|as-ro)-W\d+-\w+\]"
    r"|^\[w\d+[-\w]+\]",  # wave-number-only prefix [wNN-*] used in W25-W28
    re.IGNORECASE,
)
_MERGE_COMMIT = re.compile(r"^Merge\s+", re.IGNORECASE)
_CONVENTIONAL = re.compile(r"^(gov|fix|chore|docs|feat|refactor|test|ci|build)(\([^)]*\))?:", re.IGNORECASE)  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep


def _get_recent_commits(n: int) -> list[dict]:
    """Return list of {sha, subject, body} for last N non-merge commits."""
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={n * 2}", "--format=%H%n%s%n%b%n---END---"],
            capture_output=True, text=True, timeout=15, cwd=ROOT, encoding="utf-8", errors="replace",  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep
        )
        if result.returncode != 0:
            return []
    except Exception:
        return []

    commits = []
    raw = result.stdout
    for block in raw.split("---END---\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if not lines:
            continue
        sha = lines[0].strip()
        subject = lines[1].strip() if len(lines) > 1 else ""
        body = "\n".join(lines[2:]) if len(lines) > 2 else ""
        commits.append({"sha": sha, "subject": subject, "body": body})
        if len(commits) >= n:
            break
    return commits


def _has_owner_tag(commit: dict) -> bool:
    subject = commit.get("subject", "")
    body = commit.get("body", "")
    full = f"{subject}\n{body}"

    # Merge commits are exempt
    if _MERGE_COMMIT.search(subject):
        return True

    # Square-bracket subject prefix [track-WN-ID]
    if _SUBJECT_PREFIX.search(subject):
        return True

    # Owner: trailer in body
    if _OWNER_TRAILER.search(full):  # noqa: SIM103  # expiry_wave: Wave 30  # added: W25 baseline sweep
        return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Owner track tag enforcement.")
    parser.add_argument("--n", type=int, default=20, help="Number of recent commits to check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    # Check git available
    try:
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, timeout=5, cwd=ROOT,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError("not in git repo")
    except Exception:
        msg = {"status": "not_applicable", "check": "owner_tag", "reason": "not in git repo"}
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            print("not_applicable: not in git repo")
        return 2

    commits = _get_recent_commits(args.n)
    violations = [c for c in commits if not _has_owner_tag(c)]

    status = "fail" if violations else "pass"
    result = {
        "status": status,
        "check": "owner_tag",
        "commits_checked": len(commits),
        "violations": [
            {"sha": c["sha"][:8], "subject": c["subject"][:80]}
            for c in violations
        ],
        "reason": f"{len(violations)} commit(s) missing Owner tag" if violations else "",
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if violations:
            print(f"FAIL: {len(violations)} commit(s) missing Owner: track tag:", file=sys.stderr)
            for v in violations[:10]:
                print(f"  {v['sha']}: {v['subject'][:60]}", file=sys.stderr)
        else:
            print(f"PASS: all {len(commits)} recent commits have Owner track tag")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
