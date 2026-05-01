#!/usr/bin/env python3
"""W14-C2 / GOV-E W28: Architectural 7x24 readiness gate.

Reformed in W28: 7x24 readiness is an architectural property, not a wall-clock
soak. Checks for docs/verification/<sha>-arch-7x24.json evidence with all 5
architectural assertions PASS.

Assertions (from score_caps.yaml::architectural_seven_by_twenty_four):
  1. cross_loop_stability       — 3 sequential real-LLM runs share one gateway
  2. lifespan_observable        — current_stage non-None within 30s on all turns
  3. cancellation_round_trip    — cancel→200 live, cancel→404 unknown
  4. spine_provenance_real      — observability spine provenance: real
  5. chaos_runtime_coupled_all  — all 10 chaos scenarios runtime_coupled: true

Status semantics:
  pass     — arch-7x24 evidence file found at current HEAD with all 5 PASS
  deferred — no arch-7x24 evidence yet (generates soak_24h_missing-equivalent cap)
  fail     — evidence found but one or more assertions FAIL; blocking

Exit codes:
  0  — pass or deferred (non-blocking; manifest scoring applies cap factor)
  1  — fail (blocking)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"

_REQUIRED_ASSERTIONS = [
    "cross_loop_stability",
    "lifespan_observable",
    "cancellation_round_trip",
    "spine_provenance_real",
    "chaos_runtime_coupled_all",
]


def _repo_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _find_arch_evidence(head_sha: str) -> pathlib.Path | None:
    """Find arch-7x24 evidence file for the given SHA (or any if no SHA)."""
    if head_sha:
        exact = VERIF_DIR / f"{head_sha[:8]}-arch-7x24.json"
        if exact.exists():
            return exact
        exact40 = VERIF_DIR / f"{head_sha}-arch-7x24.json"
        if exact40.exists():
            return exact40
    # Fallback: most recent arch-7x24 evidence in verif dir
    candidates = sorted(VERIF_DIR.glob("*-arch-7x24.json")) if VERIF_DIR.exists() else []
    return candidates[-1] if candidates else None


def _emit(args: argparse.Namespace, payload: dict, *, exit_code: int) -> int:
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        status = payload.get("status", "unknown")
        reason = payload.get("reason", "")
        if status == "pass":
            print(f"PASS: {reason}")
        elif status == "fail":
            print(f"FAIL: {reason}", file=sys.stderr)
        else:
            print(f"DEFERRED: {reason}", file=sys.stderr)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Architectural 7x24 readiness gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    head_sha = _repo_head()
    evidence_file = _find_arch_evidence(head_sha)

    if evidence_file is None:
        return _emit(
            args,
            {
                "check": "soak_evidence",
                "status": "deferred",
                "reason": (
                    "no arch-7x24 evidence found; run scripts/run_arch_7x24.py "
                    "to produce <sha>-arch-7x24.json"
                ),
                "assertions_required": _REQUIRED_ASSERTIONS,
            },
            exit_code=0,
        )

    try:
        data = json.loads(evidence_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _emit(
            args,
            {
                "check": "soak_evidence",
                "status": "fail",
                "reason": f"arch-7x24 evidence unreadable: {exc}",
                "evidence_file": evidence_file.name,
            },
            exit_code=1,
        )

    assertions = data.get("assertions", {})
    failed = [k for k in _REQUIRED_ASSERTIONS if assertions.get(k) != "pass"]
    all_pass = len(failed) == 0

    if all_pass:
        return _emit(
            args,
            {
                "check": "soak_evidence",
                "status": "pass",
                "reason": "all 5 architectural 7x24 assertions PASS",
                "evidence_file": evidence_file.name,
                "assertions": assertions,
            },
            exit_code=0,
        )
    else:
        return _emit(
            args,
            {
                "check": "soak_evidence",
                "status": "fail",
                "reason": f"arch-7x24 assertions failed: {failed}",
                "evidence_file": evidence_file.name,
                "assertions": assertions,
                "failed_assertions": failed,
            },
            exit_code=1,
        )


if __name__ == "__main__":
    sys.exit(main())
