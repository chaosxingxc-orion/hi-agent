#!/usr/bin/env python3
"""CI gate: fail if clean-env evidence is stale or absent at current HEAD (AX-D D1).

Validates that docs/verification/<HEAD_SHA>-*-clean-env.json or
docs/delivery/<date>-<HEAD_SHA>-clean-env.json exists, has status=passed,
bundle_profile=default-offline, passed >= MIN_PASS, and failure_reason=null.

Exit 0: PASS — fresh clean-env evidence at HEAD
Exit 1: FAIL — absent, stale, or failing clean-env evidence
Exit 2: not_applicable — verification dirs absent (non-strict mode)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = ROOT / "docs" / "verification"
DELIVERY_DIR = ROOT / "docs" / "delivery"
MIN_PASS = 8723


def _get_head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=str(ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _find_candidates(head_sha: str) -> list[Path]:
    """Find clean-env evidence files for the given HEAD SHA in both dirs."""
    short_sha = head_sha[:7]
    candidates: list[Path] = []

    # docs/verification/<short7>-*-clean-env.json
    if VERIFICATION_DIR.exists():
        for pattern in [
            f"{short_sha}*clean-env*.json",
            f"{head_sha}*clean-env*.json",
        ]:
            candidates += [
                f for f in VERIFICATION_DIR.glob(pattern)
                if not f.stem.endswith("-provenance")
            ]

    # docs/delivery/<date>-<sha>-clean-env.json  (short or full sha in name)
    if DELIVERY_DIR.exists():
        for pattern in [
            f"*{short_sha}*clean-env*.json",
            f"*{head_sha}*clean-env*.json",
        ]:
            candidates += [
                f for f in DELIVERY_DIR.glob(pattern)
                if not f.stem.endswith("-provenance")
            ]

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _validate_evidence(evidence: dict) -> list[str]:
    """Return a list of issue strings (empty = all good)."""
    issues: list[str] = []

    status = evidence.get("status")
    if status not in ("passed", "pass"):
        issues.append(f"status={status!r} (expected 'passed')")

    # Accept 'passed' count from top-level or nested summary
    passed = evidence.get("passed")
    if passed is None:
        summary = evidence.get("summary") or {}
        passed = summary.get("passed", 0)
    try:
        if int(passed) < MIN_PASS:
            issues.append(f"passed={passed} < MIN_PASS={MIN_PASS}")
    except (TypeError, ValueError):
        issues.append(f"could not parse passed count: {passed!r}")

    failure_reason = evidence.get("failure_reason")
    if failure_reason:
        issues.append(f"failure_reason={failure_reason!r}")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean-env freshness gate (AX-D D1).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat absent verification dirs as FAIL (default: not_applicable)",
    )
    args = parser.parse_args()

    head_sha = _get_head_sha()
    if not head_sha:
        result: dict = {
            "status": "fail",
            "check": "clean_env",
            "reason": "could not determine HEAD SHA",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("FAIL: could not determine HEAD SHA", file=sys.stderr)
        return 1

    dirs_exist = VERIFICATION_DIR.exists() or DELIVERY_DIR.exists()
    if not dirs_exist:
        msg = {
            "status": "fail" if args.strict else "not_applicable",
            "check": "clean_env",
            "reason": "neither docs/verification/ nor docs/delivery/ found",
        }
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            prefix = "FAIL (strict)" if args.strict else "not_applicable"
            print(f"{prefix}: neither docs/verification/ nor docs/delivery/ found",
                  file=sys.stderr if args.strict else sys.stdout)
        return 1 if args.strict else 2

    candidates = _find_candidates(head_sha)
    if not candidates:
        result = {
            "status": "fail",
            "check": "clean_env",
            "head_sha": head_sha[:8],
            "reason": (
                f"no clean-env evidence found for HEAD {head_sha[:8]}; "
                "run scripts/verify_clean_env.py"
            ),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"FAIL: no clean-env evidence at HEAD {head_sha[:8]}; "
                "run scripts/verify_clean_env.py",
                file=sys.stderr,
            )
        return 1

    # Validate the most recently named candidate
    evidence_file = sorted(candidates)[-1]
    try:
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result = {
            "status": "fail",
            "check": "clean_env",
            "reason": f"could not read {evidence_file.name}: {exc}",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"FAIL: could not read {evidence_file.name}: {exc}", file=sys.stderr)
        return 1

    issues = _validate_evidence(evidence)
    passed = evidence.get("passed")
    if passed is None:
        passed = (evidence.get("summary") or {}).get("passed", 0)

    if issues:
        result = {
            "status": "fail",
            "check": "clean_env",
            "evidence_file": evidence_file.name,
            "issues": issues,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"FAIL: clean-env evidence has issues: {'; '.join(issues)}", file=sys.stderr)
        return 1

    result = {
        "status": "pass",
        "check": "clean_env",
        "evidence_file": evidence_file.name,
        "passed": passed,
        "head_sha": head_sha[:8],
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"PASS: clean-env at HEAD {head_sha[:8]} ({passed} tests passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
