# Deprecated Field Removal

**Status:** active
**Origin:** ledger entry W28-B
**Last updated:** 2026-05-07

## What this is

Deprecated data fields and API keys remain present at Wave 28 close: `TeamSharedContext.{hypotheses, claims, phase_history}`, `TeamRun.pi_run_id`, the evaluation `citations` key (with fallback), and a `json_config_loader` env alias. These were added with a Wave 28 removal promise during the Wave 11 contract reshape; consumer audit is incomplete, so the deprecated paths still resolve at runtime.

## When to use this runbook

- Triggered by: `hi_agent_deprecated_field_access_total` firing (any read of the deprecated attributes in research/prod)
- Triggered by: `hi_agent_deprecated_field_access_alert`
- During: routine quarterly burndown review or when bumping the `expiry_wave` carryover

## Diagnostic steps

1. Grep the repo for live consumers of each deprecated surface:
   - `TeamSharedContext.hypotheses`, `.claims`, `.phase_history`
   - `TeamRun.pi_run_id`
   - eval payloads keyed on `citations` (and its fallback path)
   - `json_config_loader` env alias key
2. Verify whether each access site has a migration target on the canonical contract.
3. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W28-B` (defect_class `deprecated_field_removal`).
4. Confirm the regression-test commitment in the ledger: "unit tests asserting deprecated fields raise `AttributeError` on access".

## Remediation steps

1. Migrate every consumer to the canonical fields. Land migrations in the same PR as the field removal where possible to avoid cross-wave ambiguity.
2. Remove the deprecated fields from `TeamSharedContext` and `TeamRun`; drop the `citations` fallback in the eval pipeline; remove the `json_config_loader` env alias.
3. Add unit tests asserting `AttributeError` (or the typed equivalent) on access.
4. Re-run the release gate (`scripts/check_expired_waivers.py`) to confirm the W29 expiry trigger no longer fires.

## Recurrence prevention

The waiver-discipline gate at `scripts/check_expired_waivers.py` enforces this in CI: each deprecated field carries an `expiry_wave` marker, and the gate fails closed when `current_wave` exceeds expiry. If the gate has drifted (script renamed, workflow not invoking it, or the entry was bulk-bumped without structural fix), see runbook `release-gate-weakening.md` and the cycle-termination policy in `docs/governance/recurrence-ledger.yaml::P0-W30`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id `W28-B`
- Code fix history: W29 target -- remove deprecated fields, citations fallback, env alias
- Regression test: W29 target -- unit tests asserting `AttributeError` on deprecated access
- Process change: CLAUDE.md Rule 17 (allowlist discipline); `expiry_wave` bumped to Wave 29 during W28 close
- Triage record: `docs/governance/wave-28-expiry-triage.md#group-3`
