#!/usr/bin/env python3
"""W14-B8 / Observability spine completeness gate.

Reads the latest spine evidence from docs/verification/*-observability-spine.json.

Exit semantics (per  plan §Risks — partial-credit allowed):
  - PASS     : provenance=="real" AND layer_count>=14 AND trace_id_consistent
  - DEFER    : provenance=="real" AND 8<=layer_count<14, OR no evidence file.
               (Acceptable per plan: partial coverage still beats structural.)
  - DEFER    : provenance!="real" (structural / synthetic) — score-cap applies.
  - FAIL     : evidence file unreadable, or claims real with <8 layers.

DEFER and PASS both return exit code 0 (manifest scoring handles caps).
FAIL returns exit code 1.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from _governance.evidence_picker import latest_evidence

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"

# 14 layer slots — names match scripts/run_observability_spine.py.
_EXPECTED_LAYERS = [
    "http_request", "middleware", "tenant_context",
    "run_manager", "kernel_dispatch", "reasoning_loop",
    "capability_handler", "llm_gateway", "sync_bridge",
    "http_transport", "llm_provider_response", "fallback_recorder",
    "artifact_ledger", "event_store",
]

# Legacy event_type names (kept for backward compatibility with older
# build_observability_spine_evidence.py outputs that listed event_types
# rather than logical layer slots).
_LEGACY_EVENT_TYPES = [
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


def _layers_present(data: dict) -> list[str]:
    """Extract the list of present layer names from evidence.

    Newer format: ``layers_present`` is a list of layer-slot names.
    Older (W14) format: ``layers`` is a list of event_type strings.
    """
    layers_present = data.get("layers_present")
    if isinstance(layers_present, list):
        return [str(la) for la in layers_present]
    legacy_layers = data.get("layers", [])
    if isinstance(legacy_layers, list) and legacy_layers and isinstance(legacy_layers[0], str):
        return [str(la) for la in legacy_layers]
    if isinstance(legacy_layers, list) and legacy_layers and isinstance(legacy_layers[0], dict):
        return [la.get("layer", "") for la in legacy_layers if isinstance(la, dict)]
    return []


def _is_consistent_correlation(data: dict) -> bool:
    """Return True iff the evidence claims trace_id_consistent."""
    # New  flag.
    if "trace_id_consistent" in data:
        return bool(data["trace_id_consistent"])
    # Older evidence: presence of trace_id is the proxy.
    return bool(data.get("trace_id"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Observability spine completeness gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    spine_file = _latest_spine_evidence()
    if spine_file is None:
        result = {
            "status": "fail",
            "check": "observability_spine_completeness",
            "reason": "evidence_missing: no spine evidence found in docs/verification/",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("FAIL: no observability spine evidence", file=sys.stderr)
        return 1

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
    layers_present = _layers_present(data)
    layer_count = int(
        data.get("layer_count", data.get("event_count", len(layers_present)))
    )
    has_run_id = bool(data.get("run_id"))
    has_trace_id = bool(data.get("trace_id"))
    trace_consistent = _is_consistent_correlation(data)

    # ------------------------------------------------------------------
    # Structural / synthetic evidence: spine shape recorded but real
    # execution not confirmed. Emit deferred (exit 0) rather than fail —
    # pending real spine run.
    # ------------------------------------------------------------------
    if provenance != "real":
        result = {
            "status": "deferred",
            "check": "observability_spine_completeness",
            "provenance": provenance,
            "spine_file": spine_file.name,
            "layer_count": layer_count,
            "coverage": f"{layer_count}/14",
            "reason": f"provenance='{provenance}'; real spine run required for pass",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"DEFERRED: spine provenance='{provenance}', real run required",
                file=sys.stderr,
            )
        return 0

    # ------------------------------------------------------------------
    # Real provenance: gate on layer_count and correlation.
    # ------------------------------------------------------------------
    issues: list[str] = []
    if not has_run_id:
        issues.append("missing run_id correlation field")
    if not has_trace_id:
        issues.append("missing trace_id correlation field")
    if not trace_consistent:
        issues.append("trace_id not consistent across stored-event layers")

    # Compute missing layers (using the new layer-slot taxonomy when available).
    if layers_present and any(la in _EXPECTED_LAYERS for la in layers_present):
        missing_layers = [la for la in _EXPECTED_LAYERS if la not in layers_present]
    else:
        # Legacy event_type taxonomy — keep the old gate behaviour.
        missing_layers = [la for la in _LEGACY_EVENT_TYPES if la not in layers_present]

    # Three-band exit:
    #   layer_count >= 14 AND no issues : PASS
    #   8 <= layer_count < 14            : DEFER (partial credit per plan §Risks)
    #   layer_count < 8                  : FAIL (claims real but covers nothing)
    if layer_count >= 14 and not issues:
        status = "pass"
    elif layer_count >= 8:
        status = "deferred"
    else:
        status = "fail"
        issues.append(
            f"layer_count={layer_count} < 8; spine evidence too thin "
            "for real-provenance claim"
        )

    result = {
        "status": status,
        "check": "observability_spine_completeness",
        "provenance": provenance,
        "spine_file": spine_file.name,
        "layer_count": layer_count,
        "expected_layers": len(_EXPECTED_LAYERS),
        "coverage": f"{layer_count}/14",
        "missing_layers": missing_layers,
        "trace_id_present": has_trace_id,
        "trace_id_consistent": trace_consistent,
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if status == "pass":
            print(
                f"PASS: spine complete ({layer_count}/14 layers), provenance:real"
            )
        elif status == "deferred":
            print(
                f"DEFERRED: partial spine coverage ({layer_count}/14 layers) — "
                "lifts above structural but below full pass",
                file=sys.stderr,
            )
        else:
            for issue in issues:
                print(f"FAIL: {issue}", file=sys.stderr)

    # PASS and DEFER both exit 0; only FAIL exits 1.
    return 0 if status in ("pass", "deferred") else 1


if __name__ == "__main__":
    sys.exit(main())
