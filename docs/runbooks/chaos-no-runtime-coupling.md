# Runbook: Chaos Scenario Not Runtime-Coupled

## Symptom
`check_chaos_runtime_coupling.py --strict` reports scenarios with `runtime_coupled: false`.

## Cause
One or more chaos scenarios inject faults structurally (code comments, skipped assertions) instead of at runtime seams.

## Resolution
1. Identify which scenario reports `runtime_coupled: false`.
2. Wire the fault injection via `hi_agent/server/fault_injection.py` (reads `HI_AGENT_FAULT_*` env at startup).
3. Re-run the scenario: `python tests/chaos/scenarios/<N>_*.py`.
4. Verify the evidence file shows `runtime_coupled: true, provenance: real`.

## Prevention
`check_chaos_runtime_coupling.py --strict` is a release gate.
