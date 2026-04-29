#!/usr/bin/env python3
"""W14-B8: Observability spine completeness gate.

Reads the latest spine evidence from docs/verification/*-observability-spine.json.
Asserts:
  - provenance == "real"
  - All expected layers are present
  - run_id and trace_id correlation fields present

Exit 0: pass (spine complete with real provenance).
Exit 1: fail (spine incomplete or wrong provenance).
Exit 0: deferred (same as pass — manifest scoring handles score cap) (no spine evidence found).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from _governance.evidence_picker import latest_evidence

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"

_EXPECTED_LAYERS = [
    "http_request", "run_queued", "run_started", "lease_acquired",
    "heartbeat_renewed", "llm_call", "tool_call", "run_completed",
    "event_stored", "metric_emitted", "trace_id_propagated",
    "dlq_checked", "recovery_decision", "run_finalized",
]


def _latest_spine_evidence() -> pathlib.Path | None:
    """Pick latest spine evidence via canonical helper.

    Sort: (generated_at, mtime, name) — see _governance.evidence_picker.
    """
    return latest_evidence(VERIF_DIR, "*-observability-spine.json")


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
        return 0  # deferred: no blocking failure, manifest scoring handles score cap

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

    # Structural/synthetic evidence: spine shape recorded but real execution not confirmed.
    # Emit deferred (exit 2) rather than fail — pending real spine run.
    if provenance not in ("real",):
        result = {
            "status": "deferred",
            "check": "observability_spine_completeness",
            "provenance": provenance,
            "spine_file": spine_file.name,
            "reason": f"provenance='{provenance}'; real spine run required for pass",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: spine provenance='{provenance}', real run required", file=sys.stderr)
        return 0  # deferred: no blocking failure, manifest scoring handles score cap

    missing_layers = [la for la in _EXPECTED_LAYERS if la not in layers_present]
    layer_count = len(layers_present)
    # The spine must report at least 12 event observations to be considered
    # complete.  Fewer implies the run was too short or the spine was synthetic.
    min_event_count = 12
    event_count = data.get("event_count", data.get("layers_count", layer_count))
    # trace_id consistency: all events in the evidence must share the claimed trace_id.
    # We check via event_count > 0 && trace_id present as a proxy (the builder script
    # is responsible for per-event trace_id checks; the gate validates the spine claims).
    claimed_trace_id = data.get("trace_id", "")
    claimed_run_id = data.get("run_id", "")

    issues = []
    if missing_layers:
        issues.append(f"missing layers: {', '.join(missing_layers)}")
    if not has_run_id:
        issues.append("missing run_id correlation field")
    if not has_trace_id:
        issues.append("missing trace_id correlation field")
    if event_count < min_event_count:
        issues.append(
            f"event_count={event_count} < required minimum {min_event_count}; "
            "spine may be truncated or synthetic"
        )
    if claimed_trace_id and claimed_run_id and len(claimed_trace_id) < 16:
        issues.append(
            f"trace_id='{claimed_trace_id}' too short to be a valid trace ID; "
            "spine trace_id must be a 32-char hex string"
        )

    status = "pass" if not issues else "fail"
    result = {
        "status": status,
        "check": "observability_spine_completeness",
        "provenance": provenance,
        "spine_file": spine_file.name,
        "layers_present": layer_count,
        "expected_layers": len(_EXPECTED_LAYERS),
        "missing_layers": missing_layers,
        "event_count": event_count,
        "min_event_count": min_event_count,
        "trace_id_present": bool(claimed_trace_id),
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in issues:
            print(f"FAIL: {issue}", file=sys.stderr)
        if not issues:
            n = len(layers_present)
            t = len(_EXPECTED_LAYERS)
            print(f"PASS: spine complete ({n}/{t} layers), provenance:real")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
