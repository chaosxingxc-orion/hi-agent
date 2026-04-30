"""Multistatus gate runner (W23-A).

Invokes any gate script that supports the multistatus protocol
(``--json`` flag emitting a :class:`GateResult` JSON line on stdout) and
aggregates results across all 9 boundary gates.

Usage::

    # Run all 9 W23-converted gates:
    python -m scripts._governance.multistatus_runner --all --json

    # Run a single gate by name:
    python -m scripts._governance.multistatus_runner --gate contract_freeze --json

Output (--json)::

    {
      "results":     [ {gate, status, reason, evidence, expiry_wave}, ... ],
      "pass_count":  N,
      "fail_count":  N,
      "warn_count":  N,
      "defer_count": N
    }

Exit code:
  - 0 if no FAILs.
  - 1 if any gate returned FAIL.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any

# Allow `python -m scripts._governance.multistatus_runner` AND direct execution.
_HERE = pathlib.Path(__file__).resolve()
_ROOT = _HERE.parent.parent.parent
if str(_HERE.parent.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent.parent))

from _governance.multistatus import (
    GateResult,
    GateStatus,
    MultistatusParseError,
    parse,
)

# Gate registry: gate_name -> (script filename relative to scripts/, extra args)
GATES: dict[str, tuple[str, list[str]]] = {
    "contract_freeze":               ("check_contract_freeze.py",               []),
    "contracts_purity":              ("check_contracts_purity.py",              []),
    "facade_loc":                    ("check_facade_loc.py",                    []),
    "no_domain_types":               ("check_no_domain_types.py",               []),
    "no_reverse_imports":            ("check_no_reverse_imports.py",            []),
    "route_tenant_context":          ("check_route_tenant_context.py",          []),
    "score_artifact_consistency":    ("check_score_artifact_consistency.py",    []),
    "state_transition_centralization": ("check_state_transition_centralization.py", []),
    "tdd_evidence":                  ("check_tdd_evidence.py",                  []),
}

SCRIPTS_DIR = _ROOT / "scripts"


def run_gate(gate_name: str, *, timeout: int = 60) -> GateResult:
    """Invoke a single gate script with --json and parse its multistatus output.

    On any failure to parse, returns a GateResult with status=FAIL and an
    explanatory reason. The caller (the runner) uses the resulting status to
    drive its exit code.
    """
    spec = GATES.get(gate_name)
    if spec is None:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name=gate_name,
            reason=f"unknown gate name {gate_name!r}; expected one of {sorted(GATES)}",
        )
    script, extra_args = spec
    script_path = SCRIPTS_DIR / script
    if not script_path.exists():
        return GateResult(
            status=GateStatus.FAIL,
            gate_name=gate_name,
            reason=f"gate script not found: {script}",
        )
    cmd = [sys.executable, str(script_path), *extra_args, "--json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_ROOT),
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name=gate_name,
            reason=f"gate timed out after {timeout}s",
        )
    except Exception as exc:  # surfaces as FAIL with attribution
        return GateResult(
            status=GateStatus.FAIL,
            gate_name=gate_name,
            reason=f"gate launch failed: {exc!r}",
        )

    stdout = proc.stdout or ""
    try:
        result = parse(stdout)
    except MultistatusParseError as exc:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name=gate_name,
            reason=f"gate did not emit multistatus JSON: {exc}",
            evidence={
                "exit_code": proc.returncode,
                "stdout_tail": stdout[-400:],
                "stderr_tail": (proc.stderr or "")[-400:],
            },
        )

    # Cross-check: gate's intrinsic exit code MUST agree with the parsed status.
    # PASS/WARN/DEFER → exit 0, FAIL → exit 1.
    expected = 1 if result.status is GateStatus.FAIL else 0
    if proc.returncode != expected:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name=gate_name,
            reason=(
                f"exit-code/status disagreement: status={result.status.value} "
                f"but exit={proc.returncode}"
            ),
            evidence={"original": result.to_dict()},
        )
    return result


def run_all(*, timeout: int = 60) -> list[GateResult]:
    """Run every registered gate and return the list of results in registry order."""
    return [run_gate(name, timeout=timeout) for name in GATES]


def aggregate(results: list[GateResult]) -> dict[str, Any]:
    """Build the runner output dict from a list of results."""
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "DEFER": 0}
    for r in results:
        counts[r.status.value] += 1
    return {
        "results":     [r.to_dict() for r in results],
        "pass_count":  counts["PASS"],
        "fail_count":  counts["FAIL"],
        "warn_count":  counts["WARN"],
        "defer_count": counts["DEFER"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multistatus gate runner (W23-A).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run every registered gate.")
    group.add_argument("--gate", help="Run a single gate by name.")
    parser.add_argument("--json", action="store_true", help="Emit aggregated JSON to stdout.")
    parser.add_argument("--timeout", type=int, default=60, help="Per-gate timeout in seconds.")
    args = parser.parse_args(argv)

    if args.all:
        results = run_all(timeout=args.timeout)
    else:
        results = [run_gate(args.gate, timeout=args.timeout)]

    payload = aggregate(results)

    if args.json:
        print(json.dumps(payload, separators=(",", ":")))
    else:
        for r in results:
            print(f"{r.status.value:5s}  {r.gate_name:36s}  {r.reason}")
        print(
            f"\npass={payload['pass_count']}  fail={payload['fail_count']}  "
            f"warn={payload['warn_count']}  defer={payload['defer_count']}"
        )

    return 0 if payload["fail_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
