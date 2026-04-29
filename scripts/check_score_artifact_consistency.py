#!/usr/bin/env python3
"""CI gate: validate release manifest self-consistency (W22-A10).

Checks that every release manifest in docs/releases/ satisfies the three-way
SHA agreement:

  1. ``manifest_id`` field contains the same 7-character SHA prefix as ``release_head``
  2. The manifest filename contains that same SHA prefix

Exit code 0 = all consistent; 1 = one or more violations found.

Usage::

    # Scan all manifests in docs/releases/ (CI mode):
    python scripts/check_score_artifact_consistency.py

    # Validate a single file (used by tests):
    python scripts/check_score_artifact_consistency.py <path/to/manifest.json>

    # JSON output for build_release_manifest gate integration:
    python scripts/check_score_artifact_consistency.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def validate_manifest_file(filepath: str) -> None:
    """Validate that a single manifest file satisfies SHA self-consistency.

    Raises:
        ValueError: If any SHA prefix mismatch is detected, or a required
            field is missing.
    """
    path = Path(filepath)
    data = _load_json(path)
    if data is None:
        raise ValueError(f"Cannot read or parse {path.name}")

    release_head: str = str(data.get("release_head") or "").strip()
    manifest_id: str = str(data.get("manifest_id") or "").strip()

    if not release_head:
        raise ValueError(
            f"{path.name}: 'release_head' field is missing or empty"
        )
    if not manifest_id:
        raise ValueError(
            f"{path.name}: 'manifest_id' field is missing or empty"
        )

    rh7 = release_head[:7].lower()

    # Check 1: manifest_id must contain the release_head SHA prefix.
    if rh7 not in manifest_id.lower():
        raise ValueError(
            f"SHA mismatch in {path.name}: "
            f"release_head prefix {rh7!r} not found in manifest_id={manifest_id!r}"
        )

    # Check 2: filename must contain the release_head SHA prefix.
    if rh7 not in path.name.lower():
        raise ValueError(
            f"SHA mismatch in {path.name}: "
            f"release_head prefix {rh7!r} not found in filename"
        )


def _is_archive(path: Path) -> bool:
    """Return True if path is under an archive subdirectory."""
    return "archive" in path.parts


def check_all_manifests(releases_dir: Path) -> list[str]:
    """Check all non-archived manifest JSON files in releases_dir.

    Returns a list of violation strings (empty list = all pass).
    """
    if not releases_dir.exists():
        return []

    # Only check top-level manifests (not archived ones) — archived manifests
    # may have date mismatches in filename vs manifest_id that were corrected
    # in later waves; those are known and expected.
    manifest_files = [
        f
        for f in releases_dir.glob("*.json")
        if not _is_archive(f)
        and "manifest" in f.name.lower()
        and not f.stem.endswith("-provenance")
    ]

    violations: list[str] = []
    for mf in sorted(manifest_files):
        try:
            validate_manifest_file(str(mf))
        except ValueError as exc:
            violations.append(str(exc))

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score artifact self-consistency gate (W22-A10): "
            "validates that manifest filename, manifest_id, and release_head "
            "all share the same 7-character SHA prefix."
        )
    )
    parser.add_argument(
        "manifest_file",
        nargs="?",
        help="Single manifest file to validate. If omitted, scans docs/releases/.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    args = parser.parse_args()

    if args.manifest_file:
        # Single-file mode (used by tests and manual invocation).
        try:
            validate_manifest_file(args.manifest_file)
            msg = {
                "status": "pass",
                "check": "score_artifact_consistency",
                "file": args.manifest_file,
            }
            if args.json:
                print(json.dumps(msg, indent=2))
            else:
                print(f"PASS: {args.manifest_file} is self-consistent")
            return 0
        except ValueError as exc:
            msg = {
                "status": "fail",
                "check": "score_artifact_consistency",
                "file": args.manifest_file,
                "reason": str(exc),
            }
            if args.json:
                print(json.dumps(msg, indent=2))
            else:
                print(f"FAIL: {exc}", file=sys.stderr)
            return 1

    # Scan-all mode (CI).
    violations = check_all_manifests(RELEASES_DIR)
    if violations:
        result = {
            "status": "fail",
            "check": "score_artifact_consistency",
            "violations_found": len(violations),
            "violations": violations,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"FAIL: {len(violations)} score artifact consistency violation(s):",
                file=sys.stderr,
            )
            for v in violations:
                print(f"  {v}", file=sys.stderr)
        return 1

    manifest_files = list(RELEASES_DIR.glob("*.json"))
    manifest_count = sum(
        1 for f in manifest_files
        if "manifest" in f.name.lower() and not f.stem.endswith("-provenance")
    )
    result = {
        "status": "pass",
        "check": "score_artifact_consistency",
        "manifests_checked": manifest_count,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"PASS: {manifest_count} manifest file(s) self-consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
