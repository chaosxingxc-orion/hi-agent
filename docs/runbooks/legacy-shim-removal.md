# Legacy Shim Removal

**Status:** active
**Origin:** ledger entry W28-A
**Last updated:** 2026-05-07

## What this is

Compatibility shims (`hi_agent.plugin` -> `hi_agent.plugins`, `hi_agent.experiment` -> `hi_agent.operations`) were introduced in Wave 11 for backward compatibility and remain active. They emit `DeprecationWarning` on import. Consumer audit and removal are pending; the shim packages still ship in the wheel.

## When to use this runbook

- Triggered by: `hi_agent_deprecated_shim_import_total` firing (any non-zero count of consumer code importing the shim modules in research/prod)
- Triggered by: `hi_agent_deprecated_shim_import_alert`
- During: routine quarterly burndown review or when bumping the `expiry_wave` carryover

## Diagnostic steps

1. Grep the repo for active import sites:
   - `Grep` for `from hi_agent.plugin` and `from hi_agent.experiment` across `hi_agent/`, `agent_server/`, `agent_kernel/`, `tests/`, `examples/`.
   - Confirm whether any non-shim source still imports the deprecated paths.
2. Inspect the shim packages themselves: locate `hi_agent/plugin/__init__.py` and `hi_agent/experiment/__init__.py` and verify they only re-export from the canonical packages.
3. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W28-A` (defect_class `legacy_shim_removal`).
4. Verify the regression-test commitment still stands: per the ledger, the W29 target is "grep for any import of `hi_agent.plugin.` or `hi_agent.experiment.` to confirm zero callers".

## Remediation steps

1. Audit every import site found in step 1. Migrate each consumer to the canonical package (`hi_agent.plugins`, `hi_agent.operations`).
2. Remove the shim packages (`hi_agent/plugin/`, `hi_agent/experiment/`) once all callers are migrated.
3. Drop the matching layering allowlist entries (see `docs/runbooks/layering-allowlist-burndown.md` -- ledger entry W28-C is paired with this one).
4. Re-run the release gate (`scripts/check_expired_waivers.py`) to confirm the W29 expiry trigger no longer fires.

## Recurrence prevention

The waiver-discipline gate at `scripts/check_expired_waivers.py` enforces this in CI: the shim entries carry an `expiry_wave` marker, and the gate fails closed when `current_wave` exceeds expiry. If the gate has drifted (script renamed, workflow not invoking it, or the entry was bulk-bumped without structural fix), see runbook `release-gate-weakening.md` and consult `docs/governance/recurrence-ledger.yaml::P0-W30` (the cycle-termination decision that forbids paperwork-only bumps).

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id `W28-A`
- Code fix history: W29 target -- audit consumers, remove shim packages
- Regression test: W29 target -- grep import survey returning zero callers
- Process change: CLAUDE.md Rule 17 (allowlist discipline); `expiry_wave` was bumped to Wave 29 during W28 close
- Companion runbook: `docs/runbooks/layering-allowlist-burndown.md` (W28-C)
- Triage record: `docs/governance/wave-28-expiry-triage.md#group-1`
