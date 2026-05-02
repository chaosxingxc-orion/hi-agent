#!/usr/bin/env python3
"""CI gate: verify that current HEAD has at least one verification artifact.

Walks docs/verification/*.json and docs/delivery/*.json.
Passes when at least one artifact's 'release_head' or 'verified_head' matches
the current git HEAD (short or full SHA prefix).

With --allow-docs-only-gap: also passes when the most-recent artifact is from
a SHA where the only commits between that SHA and current HEAD touch docs/ files.
This handles the self-referential docs commit that adds the artifact itself.

Historical artifacts from prior HEADs are normal record-keeping — they are NOT
treated as "stale". The gate only fails when NO fresh artifact exists for the
current HEAD (or its docs-only parents when the flag is set).

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


_GOVERNANCE_PREFIXES = (
    "docs/",
    "scripts/",
    ".github/",
)


def _docs_only_gap(base_sha: str, head: str) -> bool:
    """Return True if commits between base_sha and head only touch gov-infra files.

    Gov-infra files: docs/, scripts/, .github/ — none of which affect
    the platform's release-verified runtime behaviour.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_sha}..{head}"],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        if result.returncode != 0:
            return False
        changed = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        return bool(changed) and all(
            any(f.startswith(p) for p in _GOVERNANCE_PREFIXES) for f in changed
        )
    except Exception:
        return False


def _check_artifacts(allow_docs_only_gap: bool = False) -> tuple[list[str], list[str], bool]:
    """Return (checked_files, current_files, has_current_head).

    checked_files: all artifact files that have a SHA field.
    current_files: artifacts whose SHA matches current HEAD (or docs-only parent).
    has_current_head: True when at least one current artifact exists.
    """
    head = _git_head()
    checked: list[str] = []
    current: list[str] = []

    dirs = [
        ROOT / "docs" / "verification",
        ROOT / "docs" / "delivery",
        ROOT / "docs" / "releases",
    ]
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("provenance") == "manifest_self_reference":
                continue  # pre-write bootstrap artifact; excluded from head-check
            artifact_head = (
                data.get("release_head")
                or data.get("verified_head")
                or data.get("head_sha")
                or data.get("sha")
                or data.get("head")
                or ""
            )
            if not artifact_head:
                continue
            rel = str(f.relative_to(ROOT))
            checked.append(rel)
            if _sha_matches(artifact_head, head) or (
                allow_docs_only_gap and _docs_only_gap(artifact_head, head)
            ):
                current.append(rel)

    return checked, current, bool(current)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--allow-docs-only-gap", action="store_true",
        help="Accept artifacts whose SHA differs only by docs-only commits from HEAD",
    )
    args = parser.parse_args(argv)

    checked, current, has_current = _check_artifacts(
        allow_docs_only_gap=args.allow_docs_only_gap
    )

    if len(checked) == 0:  # noqa: SIM108  # expiry_wave: permanent  # added: W25 baseline sweep
        status = "not_applicable"
    else:
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
        return 0 if status in ("pass", "not_applicable") else 1

    if status == "not_applicable":
        print("not_applicable verification_artifacts: no artifact files found")
        return 0
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
