#!/usr/bin/env python
"""T3 evidence checker for hot-path PR changes.

Reads a list of changed files and the PR body. If any changed file matches
a hot-path pattern and the PR body does not contain "T3 evidence:", exits 1
with a clear error message. Otherwise exits 0.

Usage:
    python scripts/check_t3_evidence.py \
        --changed-files /tmp/changed_files.txt \
        --pr-body "PR body text here"
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._governance.hot_paths import HOT_PATH_PATTERNS

T3_EVIDENCE_MARKER = "T3 evidence:"


def _matches_hot_path(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in HOT_PATH_PATTERNS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check T3 evidence requirement for hot-path PRs"
    )
    parser.add_argument(
        "--changed-files",
        required=True,
        help="Path to a file containing newline-separated list of changed file paths",
    )
    parser.add_argument(
        "--pr-body",
        required=True,
        help="PR body text",
    )
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Emit JSON to stdout")
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Under --strict, not_applicable (empty changed-files list) exits 1 instead of 0. "
            "Use in CI to catch misconfigured changed-files inputs."
        ),
    )
    args = parser.parse_args(argv)

    changed_files_path = Path(args.changed_files)
    try:
        raw = changed_files_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(
            f"ERROR: Cannot read changed-files list from {args.changed_files}: {exc}",
            file=sys.stderr,
        )
        return 1

    changed_files = [line.strip() for line in raw.splitlines() if line.strip()]
    hot_path_hits = [f for f in changed_files if _matches_hot_path(f)]

    if not hot_path_hits:
        result = {
            "check": "t3_evidence",
            "status": "not_applicable",
            "reason": "no hot-path files changed",
        }
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            print("No hot-path files changed. T3 evidence not required.")
        # Under --strict, an empty changed-files list likely means the input was not
        # configured; fail-closed so the caller must verify the gate is wired correctly.
        if args.strict and not changed_files:
            print(
                "ERROR (--strict): changed-files list is empty. "
                "Verify that --changed-files input is correctly wired.",
                file=sys.stderr,
            )
            return 1
        return 0

    pr_body = args.pr_body or ""
    if T3_EVIDENCE_MARKER in pr_body:
        result = {
            "check": "t3_evidence",
            "status": "pass",
            "hot_path_hits": len(hot_path_hits),
            "reason": "T3 evidence marker present in PR body",
        }
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            print(f"Hot-path files changed ({len(hot_path_hits)} file(s)) and T3 evidence marker found. OK.")  # noqa: E501  # expiry_wave: permanent  # added: W25 baseline sweep
        return 0

    result = {
        "check": "t3_evidence",
        "status": "fail",
        "hot_path_hits": len(hot_path_hits),
        "hot_path_files": hot_path_hits,
        "reason": "hot-path files changed but no T3 evidence marker in PR body",
    }
    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(
            "ERROR: Hot-path files changed but PR body does not contain 'T3 evidence:'",
            file=sys.stderr,
        )
        print("\nHot-path files touched:", file=sys.stderr)
        for f in hot_path_hits:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nPer Rule 8 (T3 Invariance), the PR description must include one of:\n"
            "  T3 evidence: docs/delivery/<YYYY-MM-DD>-<sha>-rule15-volces.json\n"
            "  T3 evidence: DEFERRED — <reason>",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
