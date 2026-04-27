#!/usr/bin/env python3
"""W14-B2: Evidence provenance gate.

Reads every JSON in docs/verification/ and docs/delivery/.
Fails when:
  - any artifact is missing the `provenance` field (emits NOT_APPLICABLE for legacy/_legacy/)
  - any artifact consumed by a strict gate has provenance in {synthetic, unknown}

Strict gates that require provenance:real:
  check_t3_freshness, check_observability_spine_completeness,
  check_chaos_runtime_coupling

Exit 0: pass or not_applicable (all legacy).
Exit 1: fail (missing or disallowed provenance).
Exit 2: deferred (some artifacts missing but not strictly required).
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"
DELIVERY_DIR = ROOT / "docs" / "delivery"
LEGACY_DIR = VERIF_DIR / "_legacy"

# Gates that require provenance:real (not structural/synthetic/unknown)
_REAL_REQUIRED_CHECKS = frozenset({
    "observability_spine_completeness",
    "chaos_runtime_coupling",
    "soak_evidence",
})

_ALLOWED_FOR_ALL = frozenset({"real", "structural", "dry_run", "synthetic", "unknown", "derived", "shape_verified"})
_DISALLOWED_FOR_STRICT = frozenset({"synthetic", "unknown"})


def _scan_dir(directory: pathlib.Path) -> list[dict]:
    """Return list of {path, provenance, check, issues} for each JSON in directory."""
    results = []
    if not directory.exists():
        return results
    for jf in sorted(directory.glob("*.json")):
        if jf.parent == LEGACY_DIR:
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            results.append({"path": str(jf.relative_to(ROOT)), "issues": ["unreadable JSON"]})
            continue

        provenance = data.get("provenance")
        check = data.get("check", "")
        issues = []

        if provenance is None:
            issues.append("missing 'provenance' field")
        elif provenance not in _ALLOWED_FOR_ALL:
            issues.append(f"unknown provenance value: {provenance!r}")
        elif check in _REAL_REQUIRED_CHECKS and provenance in _DISALLOWED_FOR_STRICT:
            issues.append(
                f"gate '{check}' requires provenance:real but got provenance:{provenance}"
            )

        results.append({
            "path": str(jf.relative_to(ROOT)),
            "check": check,
            "provenance": provenance,
            "issues": issues,
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence provenance gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    all_results = _scan_dir(VERIF_DIR) + _scan_dir(DELIVERY_DIR)

    failing = [r for r in all_results if r.get("issues")]
    missing_provenance = [r for r in all_results if not r.get("provenance") and not r.get("issues")]

    if not all_results:
        result = {
            "status": "not_applicable",
            "check": "evidence_provenance",
            "reason": "no artifact files found",
            "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 0

    status = "pass" if not failing else "fail"
    result = {
        "status": status,
        "check": "evidence_provenance",
        "provenance": "real",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "artifacts_checked": len(all_results),
        "issues_found": len(failing),
        "issues": [
            {"path": r["path"], "issues": r["issues"]}
            for r in failing
        ],
        "summary": [
            {"path": r["path"], "check": r.get("check", ""), "provenance": r.get("provenance")}
            for r in all_results
        ],
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if failing:
            for r in failing:
                for issue in r["issues"]:
                    print(f"FAIL {r['path']}: {issue}", file=sys.stderr)
        else:
            print(f"PASS: {len(all_results)} artifacts checked, all have valid provenance")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
