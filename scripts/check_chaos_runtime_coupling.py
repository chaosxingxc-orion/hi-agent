#!/usr/bin/env python3
"""W14-C4: Chaos runtime-coupling gate.

Reads docs/verification/*-chaos-*.json evidence.
Fails when any scenario has runtime_coupled: false or synthetic: true.
Defers when no chaos evidence exists.

Exit 0: pass (all scenarios runtime-coupled with real provenance).
Exit 1: fail (non-runtime-coupled scenarios).
Exit 2: deferred (no chaos evidence found).
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


def _latest_chaos_evidence() -> pathlib.Path | None:
    """Pick latest chaos evidence from either verification or delivery directories.

    Sort logic delegated to _governance.evidence_picker.
    """
    a = latest_evidence(VERIF_DIR, "*chaos*.json")
    b = latest_evidence(DELIVERY_DIR, "*chaos*.json")
    if a and b:
        try:
            return a if a.stat().st_mtime >= b.stat().st_mtime else b
        except OSError:
            return a
    return a or b


def main() -> int:
    parser = argparse.ArgumentParser(description="Chaos runtime-coupling gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    chaos_file = _latest_chaos_evidence()
    if chaos_file is None:
        result = {
            "status": "deferred",
            "check": "chaos_runtime_coupling",
            "reason": "no chaos evidence found in docs/verification/ or docs/delivery/",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: no chaos evidence", file=sys.stderr)
        return 2

    try:
        data = json.loads(chaos_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result = {"status": "fail", "check": "chaos_runtime_coupling", "reason": f"unreadable: {exc}"}
        if args.json:
            print(json.dumps(result, indent=2))
        return 1

    scenarios = data.get("scenarios", [])
    if not scenarios:
        result = {
            "status": "deferred",
            "check": "chaos_runtime_coupling",
            "reason": "chaos evidence has no scenarios",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 2

    issues = []
    for s in scenarios:
        name = s.get("name", "?")
        if not s.get("runtime_coupled", False):
            issues.append(f"scenario '{name}': runtime_coupled=false")
        if s.get("synthetic", False):
            issues.append(f"scenario '{name}': synthetic=true")

    provenance = data.get("provenance", "unknown")
    if provenance in ("synthetic", "structural", "unknown"):
        issues.append(f"evidence provenance:{provenance} not accepted for chaos gate")

    status = "pass" if not issues else "fail"
    result = {
        "status": status,
        "check": "chaos_runtime_coupling",
        "scenarios_checked": len(scenarios),
        "provenance": provenance,
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in issues:
            print(f"FAIL: {issue}", file=sys.stderr)
        if not issues:
            print(f"PASS: all {len(scenarios)} chaos scenarios are runtime-coupled")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
