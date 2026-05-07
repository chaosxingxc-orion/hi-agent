# Layering Allowlist Burndown

**Status:** active
**Origin:** ledger entry W28-C
**Last updated:** 2026-05-07

## What this is

`scripts/check_layering.py` carries an internal `ALLOWLIST` with two Wave 29-expiry entries that defer enforcement of the layering rule for the deprecated compat shims (`hi_agent.plugin`, `hi_agent.experiment`). The allowlist is paired with the shim-removal carryover in `W28-A`: once the shims are removed, the allowlist entries are obsolete.

## When to use this runbook

- Triggered by: `hi_agent_layering_allowlist_count` firing (allowlist size increases or fails to drop after the paired shim removal)
- Triggered by: `hi_agent_layering_allowlist_alert`
- During: routine quarterly burndown review or whenever the W28-A shim removal lands

## Diagnostic steps

1. Inspect the allowlist directly in `scripts/check_layering.py` and confirm which paths each Wave 29-expiry entry exempts.
2. Run the gate: `python scripts/check_layering.py --json` -- record the current allowlist count and which entries are flagged for expiry.
3. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W28-C` (defect_class `layering_allowlist_burndown`).
4. Confirm the paired shim status with `docs/runbooks/legacy-shim-removal.md` (W28-A): allowlist removal is gated on shim removal landing first.

## Remediation steps

1. Land the W28-A shim removal first. Removing the allowlist before the shims will cause `check_layering.py` to fail closed on legitimate-but-deprecated imports.
2. Delete the two Wave 29-expiry entries from the `ALLOWLIST` constant in `scripts/check_layering.py`.
3. Re-run `python scripts/check_layering.py --json` and confirm zero hits for the shim paths.
4. Re-run the release gate to confirm the layering check passes without the allowlist entries.

## Recurrence prevention

The release gate at `scripts/check_layering.py` enforces the layering rule in CI; the allowlist is a structured deferral, not a permanent exemption. CLAUDE.md Rule 17 requires every allowlist entry to carry `owner`, `risk`, `reason`, `expiry_wave`, `replacement_test`, and `added_at`, and `scripts/check_allowlist_discipline.py` fails closed on expired entries. If the gate has drifted (script renamed, workflow not invoking it, or the entry bumped without structural fix), see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id `W28-C`
- Code fix history: W29 target -- remove allowlist entries after the W28-A shim removal lands
- Regression test: `scripts/check_layering.py --json` (zero hits for shim paths once allowlist entries are removed)
- Process change: CLAUDE.md Rule 17 (allowlist discipline); entries bumped to Wave 29 during W28 close-out
- Companion runbook: `docs/runbooks/legacy-shim-removal.md` (W28-A)
- Triage record: `docs/governance/wave-28-expiry-triage.md#group-6`
