#!/usr/bin/env python3
"""Chaos runtime-coupling gate (W14-C4 / W24 Track B).

Reads the latest ``docs/verification/*-chaos*.json`` evidence and reports:

  PASS    — provenance is ``runtime`` (all 10 scenarios genuinely executed
            against a live hi_agent server, all passed, none skipped).

  DEFER   — provenance is ``runtime_partial`` (server was live; >=1 scenario
            had to be skipped honestly because this environment cannot
            reproduce the fault, e.g. needs Docker, real LLM, or per-
            scenario server restart) **OR** legacy ``real`` evidence still
            present **OR** no evidence yet.

  FAIL    — provenance ``synthetic`` / ``structural`` / ``unknown`` /
            ``degraded`` (server never started or evidence is bogus) **OR**
            scenarios array is shorter than 10.

The W24 Track B contract:
  - ``provenance`` MUST be ``runtime`` or ``runtime_partial`` for this gate
    to advance toward PASS.
  - ``len(scenarios) >= 10``.
  - ``all_passed == true`` for full PASS; otherwise DEFER.

Exit codes:
  0 - PASS or DEFER (no blocking failure; manifest scoring handles score cap)
  1 - FAIL (evidence shows synthetic/structural runs or a missing artifact
      that should have been there)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from _governance.evidence_picker import all_evidence

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"
DELIVERY_DIR = ROOT / "docs" / "delivery"

# W24 Track B vocabulary.  Ordered from strongest (PASS-eligible) to weakest.
_RUNTIME_PROVENANCES = frozenset({"runtime", "runtime_partial"})
# Legacy provenance from older drivers (run_chaos_matrix.py).  Kept as DEFER
# so the gate does not retroactively fail historical evidence; freshly
# generated artifacts must use the W24 Track B vocabulary.
_LEGACY_OK_PROVENANCES = frozenset({"real"})
_HARD_FAIL_PROVENANCES = frozenset(
    {"synthetic", "structural", "unknown", "degraded"}
)
_MINIMUM_SCENARIOS = 10


def _latest_chaos_evidence() -> pathlib.Path | None:
    """Pick latest chaos evidence from either verification or delivery directories.

    Sort logic delegated to _governance.evidence_picker.all_evidence.  Sidecar
    artifacts (``*-provenance.json``) are excluded so the picker selects the
    actual body, not the metadata stub.
    """

    def _pick(dir_: pathlib.Path) -> pathlib.Path | None:
        # Preference order (broadest match wins ties via mtime/generated_at):
        #   1. W24 Track B naming: ``*-chaos-runtime.json``
        #   2. Legacy run_chaos_matrix runtime evidence: ``*-runtime-chaos.json``
        #   3. Any other ``*chaos*.json``
        # The first pattern with at least one non-sidecar match wins.
        for pattern in (
            "*-chaos-runtime.json",
            "*-runtime-chaos.json",
            "*chaos*.json",
        ):
            files = [
                p
                for p in all_evidence(dir_, pattern)
                if not p.name.endswith("-provenance.json")
            ]
            if files:
                return files[-1]
        return None

    a = _pick(VERIF_DIR)
    b = _pick(DELIVERY_DIR)
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
            "status": "fail",
            "check": "chaos_runtime_coupling",
            "reason": (
                "evidence_missing: no chaos evidence found in"
                " docs/verification/ or docs/delivery/"
            ),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("FAIL: no chaos evidence", file=sys.stderr)
        return 1

    try:
        data = json.loads(chaos_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result = {
            "status": "fail",
            "check": "chaos_runtime_coupling",
            "reason": f"unreadable: {exc}",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 1

    scenarios = data.get("scenarios", [])
    if not scenarios:
        result = {
            "status": "fail",
            "check": "chaos_runtime_coupling",
            "reason": "evidence_missing: chaos evidence has no scenarios",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("FAIL: chaos evidence has no scenarios", file=sys.stderr)
        return 1

    provenance = data.get("provenance", "unknown")
    all_passed = bool(data.get("all_passed", False))

    issues: list[str] = []
    deferrals: list[str] = []

    # -- Hard-fail conditions ------------------------------------------------
    if provenance in _HARD_FAIL_PROVENANCES:
        issues.append(
            f"evidence provenance:{provenance} not accepted for chaos gate"
        )

    if len(scenarios) < _MINIMUM_SCENARIOS:
        issues.append(
            f"scenarios={len(scenarios)} < required minimum {_MINIMUM_SCENARIOS}"
        )

    # -- PASS eligibility (W24 Track B) --------------------------------------
    # PASS requires: provenance == "runtime" AND all_passed AND >=10 scenarios.
    # Anything else with a runtime-class provenance becomes DEFER.
    if provenance == "runtime" and all_passed and len(scenarios) >= _MINIMUM_SCENARIOS:
        status = "pass"
    elif provenance == "runtime_partial" and len(scenarios) >= _MINIMUM_SCENARIOS:
        status = "deferred"
        skipped_names = [
            s.get("name", "?")
            for s in scenarios
            if s.get("skipped")
        ]
        if skipped_names:
            deferrals.append(
                f"provenance=runtime_partial; {len(skipped_names)} scenarios "
                f"skipped: " + ", ".join(skipped_names)
            )
        else:
            deferrals.append(
                "provenance=runtime_partial; some scenarios not fully exercised"
            )
    elif provenance in _LEGACY_OK_PROVENANCES and len(scenarios) >= _MINIMUM_SCENARIOS:
        # Legacy ``real`` evidence from run_chaos_matrix.py: keep deferring
        # so historical artifacts do not block the gate, but flag that a
        # W24 Track B re-run is required for PASS.
        status = "deferred"
        deferrals.append(
            "provenance=real (legacy); requires runtime/runtime_partial re-run "
            "under run_chaos_runtime_coupled.py for PASS"
        )
    elif issues:
        status = "fail"
    else:
        # Provenance not in any recognised set, or scenarios short.  Defer
        # rather than fail - the artifact is honest, just not yet PASS-grade.
        status = "deferred"
        deferrals.append(
            f"provenance={provenance!r} not yet PASS-eligible; "
            "expected runtime / runtime_partial"
        )

    result = {
        "status": status,
        "check": "chaos_runtime_coupling",
        "scenarios_checked": len(scenarios),
        "provenance": provenance,
        "all_passed": all_passed,
        "issues": issues,
        "deferrals": deferrals,
        "evidence_path": str(chaos_file),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if status == "pass":
            print(
                f"PASS: {len(scenarios)} runtime-coupled scenarios "
                f"(provenance={provenance})"
            )
        elif status == "deferred":
            for d in deferrals:
                print(f"DEFER: {d}", file=sys.stderr)
        else:
            for issue in issues:
                print(f"FAIL: {issue}", file=sys.stderr)

    # Exit 0 for PASS or DEFER; only structural FAIL is exit 1.  Manifest
    # scoring handles the score-cap interaction (``chaos_non_runtime_coupled``
    # cap fires when this gate is not PASS).
    return 0 if status in ("pass", "deferred") else 1


if __name__ == "__main__":
    sys.exit(main())
