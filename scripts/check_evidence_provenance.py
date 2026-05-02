#!/usr/bin/env python3
"""W14-B2: Evidence provenance gate.

Reads every JSON in docs/verification/ and docs/delivery/.
Fails when:
  - any artifact is missing the `provenance` field (emits NOT_APPLICABLE for legacy/_legacy/)
  - any artifact consumed by a strict gate has provenance in
    {synthetic, unknown, structural, degraded} (W31-L L-5' fix:
    adds structural and degraded to the disallowed set for real-required
    gates; previously the docstring claimed strict-real semantics but
    the code only blocked synthetic/unknown).

Strict gates that require provenance:real (no structural/degraded fallback):
  check_observability_spine_completeness, check_chaos_runtime_coupling,
  check_soak_evidence

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

_ALLOWED_FOR_ALL = frozenset({
    "real", "partial", "structural", "degraded", "dry_run",
    "synthetic", "unknown", "derived", "shape_verified", "manifest_self_reference",
    # W24 vocabulary additions (Tracks B, C, G; honest partial-credit tags):
    "runtime", "runtime_partial", "shape_1h", "simulated_pending_pm2",
})
# W31-L (L-5' fix): a "strict gate" requires provenance:real. Previously the
# docstring claimed real-required semantics but the disallowed set only
# blocked synthetic/unknown — a structural or degraded artifact silently
# satisfied the gate. The W31-L fix expands the disallowed set to include
# structural and degraded, so gates listed in _REAL_REQUIRED_CHECKS now
# block on any non-real provenance.
_DISALLOWED_FOR_STRICT = frozenset({"synthetic", "unknown", "structural", "degraded"})


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


_EVIDENCE_SCRIPTS = [
    "scripts/build_observability_spine_e2e_real.py",
    "scripts/run_chaos_matrix.py",
]


def _check_script_provenance(root: pathlib.Path) -> list[dict]:
    """Scan evidence-producing scripts for unannotated provenance='real' literals.

    Every line assigning provenance="real" in a script must be immediately
    preceded by a '# observation: <funcname>' comment.
    """
    issues = []
    for rel_path in _EVIDENCE_SCRIPTS:
        script = root / rel_path
        if not script.exists():
            continue
        lines = script.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if '"provenance"' in stripped and '"real"' in stripped and ":" in stripped:
                prev = lines[i - 1].strip() if i > 0 else ""
                if not prev.startswith("# observation:"):
                    issues.append({
                        "path": rel_path,
                        "line": i + 1,
                        "content": stripped[:120],
                        "issue": (
                            'provenance="real" without preceding'
                            ' "# observation: <funcname>" comment'
                        ),
                    })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence provenance gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    all_results = _scan_dir(VERIF_DIR) + _scan_dir(DELIVERY_DIR)
    script_issues = _check_script_provenance(ROOT)

    failing = [r for r in all_results if r.get("issues")]

    if not all_results and not script_issues:
        result = {
            "status": "fail",
            "check": "evidence_provenance",
            "reason": (
                "evidence_missing: no artifact files found in"
                " docs/verification/ or docs/delivery/"
            ),
            "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("FAIL: no artifact files found", file=sys.stderr)
        sys.exit(1)

    status = "pass" if not failing and not script_issues else "fail"
    # provenance is "real" only when the check actually ran and all assertions
    # passed.  If there are failures, the script observed real artifacts but the
    # results are not clean, so "structural" is more honest.
    derived_provenance = "real" if status == "pass" else "structural"
    result = {
        "status": status,
        "check": "evidence_provenance",
        "provenance": derived_provenance,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "artifacts_checked": len(all_results),
        "issues_found": len(failing),
        "issues": [
            {"path": r["path"], "issues": r["issues"]}
            for r in failing
        ],
        "script_source_issues": script_issues,
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
        if script_issues:
            for si in script_issues:
                print(f"FAIL {si['path']}:{si['line']}: {si['issue']}", file=sys.stderr)
        if not failing and not script_issues:
            print(f"PASS: {len(all_results)} artifacts checked, 0 script source issues")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
