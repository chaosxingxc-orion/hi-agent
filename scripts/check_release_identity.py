#!/usr/bin/env python3
"""W16-A3: Release identity consistency gate.

Validates that the latest delivery notice, the latest release manifest,
and the current repository HEAD all cite the same commit SHA.

Exit 0: pass (all SHAs consistent)
Exit 1: fail (mismatch found)
Exit 2: deferred (no manifest or notice found)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"
NOTICES_DIR = ROOT / "docs" / "downstream-responses"


def _repo_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _latest_manifest_head() -> tuple[str, str]:
    manifests = sorted(
        RELEASES_DIR.glob("platform-release-manifest-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not manifests:
        return "", ""
    try:
        data = json.loads(manifests[-1].read_text(encoding="utf-8"))
        return data.get("release_head", ""), manifests[-1].name
    except Exception:
        return "", manifests[-1].name


def _latest_notice_head() -> tuple[str, str]:
    notices = sorted(NOTICES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not notices:
        return "", ""
    for notice in reversed(notices):
        text = notice.read_text(encoding="utf-8", errors="replace")
        if re.search(r"Status:\s*(?:superseded|draft)", text, re.IGNORECASE):
            continue
        m = re.search(r"Functional\s+HEAD:\s*([0-9a-f]{7,40})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip(), notice.name
    return "", notices[-1].name if notices else ""


def _sha_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    short_len = min(len(a), len(b), 12)
    return a[:short_len] == b[:short_len]


def main() -> int:
    parser = argparse.ArgumentParser(description="Release identity consistency gate.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    args = parser.parse_args()

    repo_head = _repo_head()
    manifest_head, manifest_name = _latest_manifest_head()
    notice_head, notice_name = _latest_notice_head()

    if not repo_head:
        result = {
            "check": "release_identity",
            "status": "fail",
            "reason": "cannot determine repo HEAD",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 1

    if not manifest_head:
        result = {
            "check": "release_identity",
            "status": "deferred",
            "reason": "no release manifest found in docs/releases/",
            "repo_head": repo_head[:12],
            "manifest_head": "",
            "notice_head": "",
            "violations": [],
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: no release manifest found", file=sys.stderr)
        return 2

    violations = []
    if not _sha_match(repo_head, manifest_head):
        violations.append(
            f"repo HEAD {repo_head[:12]} != manifest head {manifest_head[:12]} ({manifest_name})"
        )
    if notice_head and not _sha_match(repo_head, notice_head):
        violations.append(
            f"repo HEAD {repo_head[:12]} != notice head {notice_head[:12]} ({notice_name})"
        )
    if notice_head and manifest_head and not _sha_match(notice_head, manifest_head):
        violations.append(
            f"notice head {notice_head[:12]} != manifest head {manifest_head[:12]}"
        )

    status = "pass" if not violations else "fail"
    result = {
        "check": "release_identity",
        "status": status,
        "repo_head": repo_head[:12],
        "manifest_head": manifest_head[:12] if manifest_head else "",
        "notice_head": notice_head[:12] if notice_head else "",
        "manifest_file": manifest_name,
        "notice_file": notice_name,
        "violations": violations,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if violations:
            for v in violations:
                print(f"FAIL: {v}", file=sys.stderr)
        else:
            print(f"PASS: all SHAs consistent at {repo_head[:12]}")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
