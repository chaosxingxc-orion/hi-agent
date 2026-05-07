# Runbook: Wave-Label Drift in Recurrence Ledger (W32-D-recurrence)

**Status:** active (META — recurrence of W32-D)
**Origin:** ledger entry W32-D-recurrence
**Last updated:** 2026-05-07

## What this is

A meta-runbook on a gate-coverage failure. The W32-D entry was created precisely to
prevent wave-label drift across governance YAML, but it omitted
`recurrence-ledger.yaml` itself from its source list. As a result, the ledger's own
`current_wave` field drifted (33 vs 35) and the W32-D gate did not catch it.
Discovered by the W35 corrective audit §5.1.

The failure mode: a gate scoped to "the visible wave-label sources" forgot to scan
the file the gate's own definition lived in. The fix extends
`check_wave_consistency.py` to read `recurrence-ledger.yaml::current_wave` as a
fifth source.

## When to use this runbook

- Triggered by: `hi_agent_wave_label_drift_in_recurrence_ledger_total` non-zero
- Triggered by: `hi_agent_wave_label_drift_in_recurrence_ledger_alert` firing
- During: any addition of a new `current_wave`-style field to a governance YAML
- During: any change to `scripts/check_wave_consistency.py` source list

## Diagnostic steps

1. Run the wave-consistency gate and inspect the source comparison:
   `python scripts/check_wave_consistency.py --json`
2. The gate must compare five sources and report any pair that disagrees:
   - `current-wave.txt`
   - `docs/governance/allowlists.yaml::current_wave`
   - latest manifest `wave` field
   - latest non-draft notice wave
   - `docs/governance/recurrence-ledger.yaml::current_wave`
3. Cross-reference with the ledger entry:
   `docs/governance/recurrence-ledger.yaml::W32-D-recurrence`.
4. Verify the regression test still asserts the closure:
   `pytest tests/integration/test_check_wave_consistency_ledger.py` — must fail
   when the ledger drifts.

## Remediation steps

1. If the gate reports drift: reconcile the disagreeing source by editing it to
   match the agreed-upon current wave. There is no preferred direction — pick
   the value that matches the latest published manifest and align everything
   else to it.
2. If a new governance YAML field naming a wave was just added (`wave_lock`,
   `current_wave`, etc.): extend `scripts/check_wave_consistency.py` source list
   to include it AT LANDING TIME. Adding the field without extending the gate
   re-creates this defect class.
3. Re-run `python scripts/check_wave_consistency.py --json` to confirm clean pass.

## Recurrence prevention

The release gate at `release-gate.yml` step "Wave consistency" enforces this in
CI. The regression test
`tests/integration/test_check_wave_consistency_ledger.py` asserts the gate fails
when the ledger drifts.

Rule 14 reinforcement (per W32-D-recurrence process change): governance-doc files
that name a wave (`current_wave`, `wave_lock`, etc.) MUST be in the
wave-consistency gate's source list. New ledger fields naming a wave must be
added to the gate at landing time — the gate's source list is part of the
contract a new field signs.

If the gate has drifted, see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id W32-D-recurrence
- Code fix history: `scripts/check_wave_consistency.py` extended to read
  `recurrence-ledger.yaml::current_wave` as a fifth source (W35 corrective §5.1)
- Regression test: `tests/integration/test_check_wave_consistency_ledger.py`
- Process change: Rule 14 reinforcement — governance YAML wave-name fields enter
  the wave-consistency gate's source list at landing time
- Parent runbook: `docs/runbooks/doc-truth-governance-drift.md` (W32-D, the entry
  this runbook is the recurrence of)
