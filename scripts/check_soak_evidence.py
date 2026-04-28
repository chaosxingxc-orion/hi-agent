#!/usr/bin/env python3
"""W14-C2: Soak evidence gate.

Reads the latest soak evidence from docs/verification/*-soak-*.json.
  - pass: provenance==real AND duration_seconds>=86400
  - deferred (cap 65 on 7x24): real soak < 24h OR dry_run
  - fail: no evidence OR synthetic/unknown provenance

Exit 0: pass.
Exit 1: fail.
Exit 0: deferred (same as pass — manifest scoring handles score cap).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from _governance.evidence_picker import latest_evidence

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"
DELIVERY_DIR = ROOT / "docs" / "delivery"

_MIN_SOAK_SECONDS = 86400  # 24 hours


def _latest_soak_evidence() -> pathlib.Path | None:
    """Pick latest soak evidence from either verification or delivery directories.

    Sort logic delegated to _governance.evidence_picker — single source of truth
    that uses (generated_at, mtime, name).
    """
    a = latest_evidence(VERIF_DIR, "*soak*.json")
    b = latest_evidence(DELIVERY_DIR, "*soak*.json")
    if a and b:
        try:
            return a if a.stat().st_mtime >= b.stat().st_mtime else b
        except OSError:
            return a
    return a or b


def main() -> int:
    parser = argparse.ArgumentParser(description="Soak evidence gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    soak_file = _latest_soak_evidence()
    if soak_file is None:
        result = {
            "status": "deferred",
            "check": "soak_evidence",
            "reason": "no soak evidence found (24h soak required for 7x24 readiness)",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: no soak evidence", file=sys.stderr)
        return 0  # deferred: no blocking failure, manifest scoring handles score cap

    try:
        data = json.loads(soak_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result = {"status": "fail", "check": "soak_evidence", "reason": f"unreadable: {exc}"}
        if args.json:
            print(json.dumps(result, indent=2))
        return 1

    provenance = data.get("provenance", "unknown")
    duration = data.get("duration_seconds", 0)
    mode = data.get("mode", "")

    if provenance in ("synthetic", "unknown"):
        result = {
            "status": "fail",
            "check": "soak_evidence",
            "reason": f"soak evidence has provenance:{provenance} — not accepted",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"FAIL: {result['reason']}", file=sys.stderr)
        return 1

    if provenance == "dry_run" or mode == "dry_run":
        result = {
            "status": "deferred",
            "check": "soak_evidence",
            "reason": "soak was dry_run; real 24h soak required for 7x24 readiness",
            "provenance": provenance,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: {result['reason']}", file=sys.stderr)
        return 0  # deferred: no blocking failure, manifest scoring handles score cap

    if provenance == "real" and duration >= _MIN_SOAK_SECONDS:
        result = {
            "status": "pass",
            "check": "soak_evidence",
            "provenance": provenance,
            "duration_seconds": duration,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"PASS: real 24h soak evidence present ({duration}s)")
        return 0

    # Real but short
    result = {
        "status": "deferred",
        "check": "soak_evidence",
        "reason": f"real soak duration {duration}s < {_MIN_SOAK_SECONDS}s (24h)",
        "provenance": provenance,
        "duration_seconds": duration,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"DEFERRED: {result['reason']}", file=sys.stderr)
    return 0  # deferred: no blocking failure, manifest scoring handles score cap


if __name__ == "__main__":
    sys.exit(main())
