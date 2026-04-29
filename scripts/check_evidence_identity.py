#!/usr/bin/env python3
"""CI gate: T3 evidence verified_head must match manifest release_head (AX-D D10).

Prevents claiming a verified score against a different commit than the manifest.
The manifest ``release_head`` is the authoritative commit; the T3 evidence
``verified_head`` (or legacy ``sha`` field, or SHA parsed from filename) must
match it at 7-character prefix resolution.

Exit 0: PASS — verified_head and release_head agree
Exit 1: FAIL — mismatch, or a required field could not be parsed
Exit 2: not_applicable — no manifest or no T3 evidence found (non-strict mode)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DELIVERY_DIR = ROOT / "docs" / "delivery"
RELEASES_DIR = ROOT / "docs" / "releases"


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_latest_manifest() -> tuple[Path, dict] | None:
    """Return (path, data) for the most recent non-archived manifest."""
    if not RELEASES_DIR.exists():
        return None
    candidates = [
        f for f in RELEASES_DIR.glob("*.json")
        if "archive" not in str(f).lower()
        and not f.stem.endswith("-provenance")
    ]
    if not candidates:
        return None
    # Sort by name descending — YYYY-MM-DD prefix makes lexicographic order correct.
    latest = sorted(candidates)[-1]
    data = _load_json(latest)
    if data is None:
        return None
    return latest, data


def _find_latest_t3_evidence() -> tuple[Path, dict] | None:
    """Return (path, data) for the most recent T3 delivery evidence file."""
    if not DELIVERY_DIR.exists():
        return None
    candidates = [
        f for f in DELIVERY_DIR.glob("*")
        if (
            f.suffix == ".json"
            and not f.stem.endswith("-provenance")
            and "deferred" not in f.name.lower()
            and (
                "-t3-" in f.name.lower()
                or "-rule15-" in f.name.lower()
            )
        )
    ]
    if not candidates:
        return None
    latest = sorted(candidates)[-1]
    data = _load_json(latest)
    if data is None:
        return None
    return latest, data


def _extract_t3_sha(path: Path, data: dict) -> str:
    """Extract the gate SHA from T3 evidence: prefer verified_head, then sha, then filename."""
    # 1. Canonical field added in modern gate scripts.
    verified_head = data.get("verified_head")
    if verified_head and isinstance(verified_head, str) and len(verified_head) >= 7:
        return verified_head.strip()

    # 2. Legacy sha field.
    sha = data.get("sha")
    if sha and isinstance(sha, str) and len(sha) >= 7:
        return sha.strip()

    # 3. Filename fallback: YYYY-MM-DD-<sha7+>-{rule15|t3}-<tag>.json
    m = re.search(r"-([0-9a-f]{7,40})-(?:rule15|t3)-", path.name)
    if m:
        return m.group(1)

    return ""


def _normalize(sha: str) -> str:
    """Return first 7 lowercase hex chars, or empty string."""
    return sha.strip()[:7].lower()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evidence identity gate: T3 verified_head == manifest release_head (AX-D D10)."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat absent manifest or T3 evidence as FAIL",
    )
    args = parser.parse_args()

    manifest_result = _find_latest_manifest()
    if not manifest_result:
        msg: dict = {
            "status": "fail" if args.strict else "not_applicable",
            "check": "evidence_identity",
            "reason": "no manifest found in docs/releases/",
        }
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            prefix = "FAIL (strict)" if args.strict else "not_applicable"
            out = sys.stderr if args.strict else sys.stdout
            print(f"{prefix}: no manifest found in docs/releases/", file=out)
        return 1 if args.strict else 2

    manifest_path, manifest = manifest_result
    manifest_head: str = (
        manifest.get("release_head")
        or manifest.get("functional_head")
        or ""
    )

    t3_result = _find_latest_t3_evidence()
    if not t3_result:
        msg = {
            "status": "fail" if args.strict else "not_applicable",
            "check": "evidence_identity",
            "manifest_file": manifest_path.name,
            "manifest_head": manifest_head[:8] if manifest_head else "",
            "reason": "no T3 evidence found in docs/delivery/",
        }
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            prefix = "FAIL (strict)" if args.strict else "not_applicable"
            out = sys.stderr if args.strict else sys.stdout
            print(f"{prefix}: no T3 evidence found in docs/delivery/", file=out)
        return 1 if args.strict else 2

    t3_path, t3_data = t3_result
    t3_head = _extract_t3_sha(t3_path, t3_data)

    m_norm = _normalize(manifest_head)
    t_norm = _normalize(t3_head)

    if not m_norm or not t_norm:
        result: dict = {
            "status": "fail",
            "check": "evidence_identity",
            "manifest_file": manifest_path.name,
            "t3_file": t3_path.name,
            "manifest_head": manifest_head,
            "t3_head": t3_head,
            "reason": "could not parse SHA from manifest or T3 evidence",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"FAIL: could not parse SHA — "
                f"manifest_head={manifest_head!r}, t3_head={t3_head!r}",
                file=sys.stderr,
            )
        return 1

    # Match at 7-char prefix resolution (either direction)
    if m_norm != t_norm:
        result = {
            "status": "fail",
            "check": "evidence_identity",
            "manifest_file": manifest_path.name,
            "t3_file": t3_path.name,
            "manifest_head": manifest_head[:8],
            "t3_head": t3_head[:8],
            "reason": (
                f"T3 verified_head {t3_head[:8]!r} "
                f"!= manifest release_head {manifest_head[:8]!r}"
            ),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"FAIL: T3 verified_head={t3_head[:8]} "
                f"!= manifest release_head={manifest_head[:8]}",
                file=sys.stderr,
            )
        return 1

    result = {
        "status": "pass",
        "check": "evidence_identity",
        "manifest_file": manifest_path.name,
        "t3_file": t3_path.name,
        "manifest_head": manifest_head[:8],
        "t3_head": t3_head[:8],
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"PASS: T3 verified_head={t3_head[:8]} "
            f"matches manifest release_head={manifest_head[:8]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
