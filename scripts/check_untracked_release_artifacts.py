#!/usr/bin/env python3
"""W17/B13: Untracked release-artifact gate.

Runs `git status --porcelain` against docs/releases/ and docs/verification/
and fails when any untracked file is present. The W17 thrash left 19 untracked
manifests + verification artifacts in the working tree, masking which manifest
was actually authoritative.

Allowed paths (untracked-tolerant):
  - docs/releases/archive/**
  - docs/verification/archive/**

Anything else under those two directories MUST be either committed (the
canonical case for fresh release evidence) or moved into archive/ (historical
debris from a prior wave).

Exit 0: no offending untracked files.
Exit 1: untracked files present outside archive/.

Status values: pass | fail | not_applicable | deferred
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WATCHED = ("docs/releases/", "docs/verification/")
ALLOW_PREFIXES = ("docs/releases/archive/", "docs/verification/archive/")


def _git_status_porcelain() -> list[tuple[str, str]]:
    """Return list of (status_code, path) tuples for git status --porcelain."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", *WATCHED],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
    except OSError as exc:
        raise RuntimeError(f"git invocation failed: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"git status exit {result.returncode}: {result.stderr.strip()}")
    out: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # porcelain v1 format: "XY path" — first 2 chars are status flags.
        code = line[:2]
        path = line[3:].strip().strip('"')
        out.append((code, path))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Untracked release-artifact gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        entries = _git_status_porcelain()
    except RuntimeError as exc:
        result = {
            "check": "untracked_release_artifacts",
            "status": "fail",
            "reason": str(exc),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    untracked: list[str] = []
    for code, path in entries:
        if code != "??":
            continue  # tracked-but-modified is out of scope for this gate
        if any(path.startswith(p) for p in ALLOW_PREFIXES):
            continue
        untracked.append(path)

    status = "pass" if not untracked else "fail"
    result = {
        "check": "untracked_release_artifacts",
        "status": status,
        "untracked_total": len(untracked),
        "untracked_paths": untracked,
        "watched_dirs": list(WATCHED),
        "allowed_archive_prefixes": list(ALLOW_PREFIXES),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for p in untracked:
            print(
                f"FAIL untracked_release_artifacts: {p}\n"
                f"  Either commit it (release evidence) or move to docs/.../archive/W{{N}}/.",
                file=sys.stderr,
            )
        if not untracked:
            print("PASS: no untracked release artifacts")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
