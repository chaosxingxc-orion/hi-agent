# Runbook: Observability Spine Has Structural Provenance

## Symptom
`check_observability_spine_completeness.py` reports layers with `provenance: structural`.

## Cause
One or more of the 14 observability spine layers emits synthetic or structural events rather than real runtime events.

## Resolution
1. Identify which layer(s) report `provenance != "real"` in the spine evidence file.
2. Wire real emitters at the callsite (see `hi_agent/observability/spine_events.py`).
3. Re-run `scripts/build_observability_spine_e2e_real.py` to capture real evidence.
4. Verify provenance=real in the output JSON.

## Prevention
`check_observability_spine_completeness.py --strict` blocks ship on any non-real layer.
