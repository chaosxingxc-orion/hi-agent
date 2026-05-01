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

from _governance.governance_gap import is_gov_only_gap
from _governance.manifest_picker import latest_manifest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"
NOTICES_DIR = ROOT / "docs" / "downstream-responses"

# Manifest filename pattern: platform-release-manifest-YYYY-MM-DD-<short-sha>.json
_MANIFEST_FILENAME_RE = re.compile(
    r"^platform-release-manifest-\d{4}-\d{2}-\d{2}-([0-9a-f]{6,40})\.json$"
)


def _repo_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _gov_only_gap(base_sha: str, head_sha: str) -> bool:
    """Backward-compat wrapper around the canonical helper (CP-3 / G-3 fix)."""
    return is_gov_only_gap(base_sha, head_sha, repo_root=ROOT)


def _latest_manifest_head() -> tuple[str, str, str]:
    """Return (release_head, manifest_filename, filename_sha) for the latest manifest.

    filename_sha is the SHA fragment parsed from the manifest filename. GS-11
    consistency check compares it against release_head to detect a manifest
    that was renamed without its content being regenerated (or vice versa).

    Uses the canonical helper (_governance.manifest_picker) — single source of
    truth for "latest manifest" selection.
    """
    data = latest_manifest(RELEASES_DIR)
    if data is None:
        return "", "", ""
    path = pathlib.Path(data["_path"])
    release_head = str(data.get("release_head", ""))
    m = _MANIFEST_FILENAME_RE.match(path.name)
    filename_sha = m.group(1) if m else ""
    return release_head, path.name, filename_sha


def _latest_notice_head() -> tuple[str, str]:
    """Return (functional_head, notice_filename) for the latest non-draft notice.

    Sorted by (mtime, name) ascending — last is latest. The reverse iteration
    skips superseded/draft notices. LB-2 fix: explicit name tiebreaker (the
    legacy code's reverse-iteration was fragile when two notices shared mtime).
    """
    notices = sorted(NOTICES_DIR.glob("*.md"), key=lambda p: (p.stat().st_mtime, p.name))
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
    parser.add_argument(
        "--allow-docs-only-gap",
        action="store_true",
        default=False,
        dest="allow_docs_only_gap",
        help=(
            "Permit HEAD mismatches when all commits between the declared HEAD and "
            "current HEAD touch only governance files (docs/, scripts/, .github/)."
        ),
    )
    args = parser.parse_args()

    repo_head = _repo_head()
    manifest_head, manifest_name, manifest_filename_sha = _latest_manifest_head()
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
    # GS-11: manifest filename SHA must equal manifest content release_head SHA.
    # A renamed-but-not-regenerated manifest (or vice versa) is a corrupt artifact.
    if manifest_filename_sha and manifest_head and not _sha_match(manifest_filename_sha, manifest_head):  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep
        violations.append(
            f"manifest filename SHA {manifest_filename_sha[:12]} != manifest content "
            f"release_head {manifest_head[:12]} ({manifest_name})"
        )
    if not _sha_match(repo_head, manifest_head):
        if args.allow_docs_only_gap and _gov_only_gap(manifest_head, repo_head):
            pass  # governance-only commits after manifest — identity still valid
        else:
            violations.append(
                f"repo HEAD {repo_head[:12]} != manifest head "
                f"{manifest_head[:12]} ({manifest_name})"
            )
    if notice_head and not _sha_match(repo_head, notice_head):
        if args.allow_docs_only_gap and _gov_only_gap(notice_head, repo_head):
            pass  # governance-only commits after declared functional HEAD
        else:
            violations.append(
                f"repo HEAD {repo_head[:12]} != notice head {notice_head[:12]} ({notice_name})"
            )
    if notice_head and manifest_head and not _sha_match(notice_head, manifest_head):
        if args.allow_docs_only_gap and _gov_only_gap(notice_head, manifest_head):
            pass  # governance-only gap between notice and manifest heads
        else:
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
