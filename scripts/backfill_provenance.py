#!/usr/bin/env python3
"""One-shot: backfill *-provenance.json sidecars for existing evidence files.

Walks docs/verification/ and docs/delivery/ and generates paired
*-provenance.json for every JSON file that doesn't have one yet.
Preserves the artifact body files unchanged (immutability maintained).

Usage:
    python scripts/backfill_provenance.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _detect_provenance(body: dict) -> str:
    """Detect provenance from artifact body, defaulting to 'derived'."""
    # Look in various standard locations
    for key in ("provenance", "_provenance", "status_provenance"):
        val = body.get(key)
        if isinstance(val, str):
            return val
    # Check nested
    meta = body.get("_evidence_meta", {})
    val = meta.get("provenance")
    if isinstance(val, str):
        return val
    return "derived"


def backfill_dir(directory: Path, dry_run: bool) -> tuple[int, int]:
    """Returns (created, skipped)."""
    created = 0
    skipped = 0
    for json_file in sorted(directory.rglob("*.json")):
        if "__pycache__" in json_file.parts:
            continue
        # Skip existing sidecars
        if json_file.stem.endswith("-provenance"):
            continue
        sidecar = json_file.with_name(json_file.stem + "-provenance.json")
        if sidecar.exists():
            skipped += 1
            continue
        # Read artifact to detect provenance
        try:
            body = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            skipped += 1
            continue
        provenance = _detect_provenance(body)
        sidecar_body = {
            "artifact_path": str(json_file.relative_to(ROOT)),
            "provenance": provenance,
            "head_sha": body.get("_evidence_meta", {}).get("head_sha", "backfill-unknown"),
            "generated_at": body.get("_evidence_meta", {}).get("generated_at", "backfill-unknown"),
            "generator_script": "scripts/backfill_provenance.py",
            "backfill": True,
        }
        if dry_run:
            print(f"  would create: {sidecar.relative_to(ROOT)}")
        else:
            sidecar.write_text(json.dumps(sidecar_body, indent=2), encoding="utf-8")
        created += 1
    return created, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill provenance sidecars.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dirs = [ROOT / "docs" / "verification", ROOT / "docs" / "delivery"]
    total_created = 0
    total_skipped = 0
    for d in dirs:
        if not d.exists():
            print(f"  skip (absent): {d}")
            continue
        c, s = backfill_dir(d, args.dry_run)
        print(f"  {d.name}: {c} sidecar(s) {'would be ' if args.dry_run else ''}created, {s} already present/skipped")  # noqa: E501  # expiry_wave: Wave 26  # added: W25 baseline sweep
        total_created += c
        total_skipped += s

    action = "would create" if args.dry_run else "created"
    print(f"\nTotal: {total_created} sidecar(s) {action}, {total_skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
