#!/usr/bin/env python3
"""W34-CONCURRENCY-BASELINE evidence freshness gate.

Verifies that ``docs/verification/`` carries at least one
``concurrency-N{N}M{M}.json`` artifact with:

  - schema == "hi-agent.concurrency-baseline.v1"
  - provenance == "real"
  - results.p95_ms is a positive float
  - results.successes >= 1

Per W34 the gate does not pin a specific {N, M} — RIA §10.1 explicitly
accepts the largest feasible N. The presence of *any* compliant baseline
is sufficient to close W34-CONCURRENCY-BASELINE.

Subsequent waves may extend this gate with regression-budget logic
(P95 must not exceed previous wave's P95 by more than 25%).

Exit 0 on pass; exit 1 with violation details otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VERIFICATION_DIR = ROOT / "docs" / "verification"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    if not VERIFICATION_DIR.exists():
        msg = f"verification directory missing: {VERIFICATION_DIR}"
        if args.json_output:
            print(json.dumps({"check": "concurrency_evidence", "status": "fail", "reason": msg}))
        else:
            print(f"FAIL concurrency_evidence: {msg}")
        return 1

    candidates = sorted(VERIFICATION_DIR.glob("*-concurrency-*.json"))
    if not candidates:
        msg = (
            "no docs/verification/*-concurrency-*.json artifact found. "
            "Run scripts/run_concurrency_baseline.py to produce one."
        )
        if args.json_output:
            print(json.dumps({"check": "concurrency_evidence", "status": "fail", "reason": msg}))
        else:
            print(f"FAIL concurrency_evidence: {msg}")
        return 1

    failures: list[str] = []
    valid: list[Path] = []
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{path.name}: cannot parse JSON: {exc}")
            continue
        if data.get("schema") != "hi-agent.concurrency-baseline.v1":
            failures.append(f"{path.name}: wrong schema={data.get('schema')!r}")
            continue
        if data.get("provenance") != "real":
            failures.append(f"{path.name}: provenance={data.get('provenance')!r}, expected 'real'")
            continue
        results = data.get("results", {})
        p95 = results.get("p95_ms", 0)
        successes = results.get("successes", 0)
        if not (isinstance(p95, (int, float)) and p95 > 0):
            failures.append(f"{path.name}: p95_ms must be positive, got {p95!r}")
            continue
        if not (isinstance(successes, int) and successes >= 1):
            failures.append(f"{path.name}: successes must be ≥ 1, got {successes!r}")
            continue
        valid.append(path)

    if args.json_output:
        print(json.dumps({
            "check": "concurrency_evidence",
            "status": "pass" if valid and not failures else "fail",
            "valid_artifacts": [p.name for p in valid],
            "failures": failures,
        }))
    else:
        if valid and not failures:
            latest = valid[-1]
            data = json.loads(latest.read_text(encoding="utf-8"))
            r = data["results"]
            print(
                f"OK concurrency_evidence ({len(valid)} valid artifacts; "
                f"latest {latest.name}: N={data['params']['N']} M={data['params']['M']} "
                f"P50={r['p50_ms']:.1f}ms P95={r['p95_ms']:.1f}ms P99={r['p99_ms']:.1f}ms)"
            )
        else:
            print("FAIL concurrency_evidence:")
            for f in failures:
                print(f"  {f}")
            if not valid:
                print(
                    "  No artifact passed validation. Run "
                    "scripts/run_concurrency_baseline.py to produce a fresh baseline."
                )
    return 0 if (valid and not failures) else 1


if __name__ == "__main__":
    sys.exit(main())
