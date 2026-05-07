# Runbook: Chaos Pilot-Run Carryover (W32-L)

**Status:** active
**Origin:** ledger entry W32-L
**Last updated:** 2026-05-07

## What this is

A Rule 7 silent-degradation carryover: two of ten chaos scenarios (concurrent-cancel
storm + worker-restart mid-LLM) still emit `provenance: pilot_run` instead of
`provenance: real`. The harness is `runtime_coupled` per the W16 P0-5 closure, but
the multi-process coordination needed to promote those two scenarios was deferred
across W28-W31 because each wave had higher-priority structural blockers.

## When to use this runbook

- Triggered by: `hi_agent_chaos_pilot_run_count` non-zero
- Triggered by: `hi_agent_chaos_pilot_run_alert` firing
- During: routine ops or post-incident review when chaos evidence regresses

## Diagnostic steps

1. Inspect the latest chaos evidence file under `docs/verification/<head>-runtime-chaos.json`
   and count scenarios where `provenance != real`.
2. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W32-L`.
3. Verify the regression test still asserts the closure: run
   `python scripts/check_chaos_runtime_coupling.py --json` and confirm the gate passes
   at `provenance: real` on at least 8/10 scenarios.
4. Inspect the per-scenario harness under `tests/chaos/scenarios/` and identify which
   scenarios still rely on a single-subprocess shape.

## Remediation steps

1. Extend `tests/chaos/scenarios/` with a multi-process coordination harness for the
   two pilot-run scenarios (concurrent-cancel storm, worker-restart mid-LLM).
2. Re-record evidence with `provenance: real` for both scenarios; regenerate
   `docs/verification/<head>-runtime-chaos.json`.
3. Re-run `python scripts/check_chaos_runtime_coupling.py --json` to confirm the gate
   accepts the upgraded provenance.

## Recurrence prevention

The release gate at `release-gate.yml` step "Check chaos runtime coupling (W14-C4)"
enforces this in CI. Any chaos scenario that lands as `provenance: pilot_run` must
carry an explicit ledger entry with W+1 expiry rather than slipping silently across
waves. If the gate has drifted, see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id W32-L
- Code fix history: W33 target — multi-process coordination harness for the two
  remaining `provenance: pilot_run` scenarios
- Regression test: `scripts/check_chaos_runtime_coupling.py --json` (currently PASS at
  `provenance: real` on 8/10; W33 will require 10/10)
- Process change: Rule 7 hardening — `provenance: pilot_run` chaos scenarios always
  enter the recurrence ledger with explicit W+1 expiry
- Related runbook: `docs/runbooks/chaos-no-runtime-coupling.md` (parent, P0-5)
