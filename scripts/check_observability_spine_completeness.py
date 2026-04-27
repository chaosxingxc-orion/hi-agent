#!/usr/bin/env python3
"""W14-B8: Observability spine completeness gate.

Reads the latest spine evidence from docs/verification/*-observability-spine.json.
Asserts:
  - provenance == "real"
  - All expected layers are present
  - run_id and trace_id correlation fields present

Exit 0: pass (spine complete with real provenance).
Exit 1: fail (spine incomplete or wrong provenance).
Exit 2: deferred (no spine evidence found).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"

_EXPECTED_LAYERS = [
    "http_request", "run_queued", "run_started", "lease_acquired",
    "heartbeat_renewed", "llm_call", "tool_call", "run_completed",
    "event_stored", "metric_emitted", "trace_id_propagated",
    "dlq_checked", "recovery_decision", "run_finalized",
]


def _latest_spine_evidence() -> pathlib.Path | None:
    files = sorted(VERIF_DIR.glob("*-observability-spine.json"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Observability spine completeness gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    spine_file = _latest_spine_evidence()
    if spine_file is None:
        result = {
            "status": "deferred",
            "check": "observability_spine_completeness",
            "reason": "no spine evidence found in docs/verification/",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: no observability spine evidence", file=sys.stderr)
        return 2

    try:
        data = json.loads(spine_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result = {
            "status": "fail",
            "check": "observability_spine_completeness",
            "reason": f"cannot read spine evidence: {exc}",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 1

    provenance = data.get("provenance", "unknown")
    layers_present = data.get("layers", [])
    has_run_id = bool(data.get("run_id"))
    has_trace_id = bool(data.get("trace_id"))

    issues = []
    if provenance != "real":
        issues.append(f"provenance is '{provenance}', requires 'real'")
    missing_layers = [l for l in _EXPECTED_LAYERS if l not in layers_present]
    if missing_layers:
        issues.append(f"missing layers: {', '.join(missing_layers)}")
    if not has_run_id:
        issues.append("missing run_id correlation field")
    if not has_trace_id:
        issues.append("missing trace_id correlation field")

    status = "pass" if not issues else "fail"
    result = {
        "status": status,
        "check": "observability_spine_completeness",
        "provenance": provenance,
        "spine_file": spine_file.name,
        "layers_present": len(layers_present),
        "expected_layers": len(_EXPECTED_LAYERS),
        "missing_layers": missing_layers,
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in issues:
            print(f"FAIL: {issue}", file=sys.stderr)
        if not issues:
            print(f"PASS: spine complete ({len(layers_present)}/{len(_EXPECTED_LAYERS)} layers), provenance:real")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
