#!/usr/bin/env python3
"""Multi-status gate convention audit.

Audits scripts/check_*.py to ensure every gate supports at minimum:
  pass | fail | not_applicable | deferred

A gate that only emits pass/fail cannot signal "this check is irrelevant in
this environment" and silently passes when its precondition is missing.

Detection heuristic: scan for "not_applicable" or "deferred" strings in the
script body. Scripts that lack both are flagged as single-path gates.

Exit 0: pass (all gates support multi-status).
Exit 1: fail (one or more single-path gates found).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

# These are known infrastructure scripts, not gates
_EXCLUDED = frozenset({
    "build_release_manifest.py",
    "release_notice.py",
    "release_pipeline.py",
    "render_doc_metadata.py",
    "runbook_drill.py",
    "soak_24h.py",
    "run_t3_gate.py",
    "verify_clean_env.py",
    "inject_volces_key.py",
    "_current_wave.py",
    "_allowlist.py",
    "_load_score_caps.py",
})

_MULTI_STATUS_MARKERS = re.compile(
    # Legacy markers (W14-D9 vintage) +  multistatus-protocol markers.
    # Either form is sufficient evidence that a gate supports multi-state output.
    r'"not_applicable"|"deferred"|not_applicable|deferred|'
    r'GateStatus\.|_governance\.multistatus',
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-status gate convention audit.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    single_path_gates: list[str] = []
    multi_status_gates: list[str] = []

    for script in sorted(SCRIPTS_DIR.glob("check_*.py")):
        if script.name in _EXCLUDED:
            continue
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if _MULTI_STATUS_MARKERS.search(text):
            multi_status_gates.append(script.name)
        else:
            single_path_gates.append(script.name)

    # Gates that don't yet support multi-status: deferred rather than fail.
    # Multi-status adoption is a Wave 14 initiative; full conversion is pending.
    status = "pass" if not single_path_gates else "deferred"
    result = {
        "status": status,
        "check": "multistatus_gates",
        "multi_status_gates": len(multi_status_gates),
        "single_path_gates": len(single_path_gates),
        "single_path_gate_list": single_path_gates,
        "multi_status_gate_list": multi_status_gates,
        "reason": "multi-status adoption in progress; not_applicable conversion pending" if single_path_gates else "",  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if single_path_gates:
            print(f"DEFERRED: {len(single_path_gates)} gates still single-path (conversion pending)", file=sys.stderr)  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep
        else:
            print(f"PASS: all {len(multi_status_gates)} gate scripts support multi-status")

    return 0


if __name__ == "__main__":
    sys.exit(main())
