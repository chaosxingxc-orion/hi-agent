#!/usr/bin/env python3
"""CI gate: validate release manifest self-consistency (W22-A10).

Checks that every release manifest in docs/releases/ satisfies the three-way
SHA agreement:

  1. ``manifest_id`` field contains the same 7-character SHA prefix as
     ``release_head``.
  2. The manifest filename contains that same SHA prefix.

Exit code 0 = PASS; 1 = FAIL.

Usage::

    # Scan all manifests in docs/releases/ (CI mode):
    python scripts/check_score_artifact_consistency.py

    # Validate a single file (used by tests):
    python scripts/check_score_artifact_consistency.py <path/to/manifest.json>

    # Multistatus JSON output (W23-A):
    python scripts/check_score_artifact_consistency.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit


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
        raise ValueError(f"{path.name}: 'release_head' field is missing or empty")
    if not manifest_id:
        raise ValueError(f"{path.name}: 'manifest_id' field is missing or empty")

    rh7 = release_head[:7].lower()

    if rh7 not in manifest_id.lower():
        raise ValueError(
            f"SHA mismatch in {path.name}: "
            f"release_head prefix {rh7!r} not found in manifest_id={manifest_id!r}"
        )

    if rh7 not in path.name.lower():
        raise ValueError(
            f"SHA mismatch in {path.name}: "
            f"release_head prefix {rh7!r} not found in filename"
        )


def _is_archive(path: Path) -> bool:
    return "archive" in path.parts


def check_all_manifests(releases_dir: Path) -> list[str]:
    """Check all non-archived manifest JSON files in releases_dir.

    Returns a list of violation strings (empty list = all pass).
    """
    if not releases_dir.exists():
        return []
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


def _evaluate_single(filepath: str) -> GateResult:
    try:
        validate_manifest_file(filepath)
        return GateResult(
            status=GateStatus.PASS,
            gate_name="score_artifact_consistency",
            reason=f"{Path(filepath).name} is self-consistent",
            evidence={"file": filepath},
        )
    except ValueError as exc:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="score_artifact_consistency",
            reason=str(exc),
            evidence={"file": filepath},
        )


def _evaluate_all() -> GateResult:
    violations = check_all_manifests(RELEASES_DIR)
    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="score_artifact_consistency",
            reason=f"{len(violations)} manifest(s) inconsistent",
            evidence={"violations": violations},
        )
    manifest_files = list(RELEASES_DIR.glob("*.json")) if RELEASES_DIR.exists() else []
    manifest_count = sum(
        1 for f in manifest_files
        if "manifest" in f.name.lower() and not f.stem.endswith("-provenance")
    )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="score_artifact_consistency",
        reason=f"{manifest_count} manifest file(s) self-consistent",
        evidence={"manifests_checked": manifest_count},
    )


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
        help="Emit multistatus JSON output.",
    )
    args = parser.parse_args()

    result = (
        _evaluate_single(args.manifest_file)
        if args.manifest_file
        else _evaluate_all()
    )

    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS: {result.reason}")
        return 0
    if args.manifest_file:
        print(f"FAIL: {result.reason}", file=sys.stderr)
    else:
        print(f"FAIL: {result.reason}:", file=sys.stderr)
        for v in result.evidence.get("violations", []):
            print(f"  {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
