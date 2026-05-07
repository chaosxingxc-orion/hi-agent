# Runbook: Doc-Truth Governance Drift (W32-D)

**Status:** active
**Origin:** ledger entry W32-D
**Last updated:** 2026-05-07

## What this is

A class of governance defects where doc-truth signals (current_wave fields, hardcoded
wave literals, allowlist permanence rationale, capability-matrix timestamps,
`__all__` scope distinctions, Rule 9 open-findings discipline) drift out of agreement
with each other or with the source-of-truth gates. W32 Track D surfaced six concurrent
instances. Root cause: each existing gate was scoped to one drift surface and could
not see the others.

## When to use this runbook

- Triggered by: `hi_agent_doc_truth_governance_drift_total` non-zero
- Triggered by: `hi_agent_doc_truth_governance_drift_alert` firing
- During: routine ops or post-incident review when wave/timestamp/allowlist signals
  disagree

## Diagnostic steps

1. Run the six gates that scan the drift surfaces:
   - `python scripts/check_doc_truth.py --json`
   - `python scripts/check_wave_consistency.py --json`
   - `python scripts/check_allowlist_discipline.py --json`
   - `python scripts/check_no_hardcoded_wave.py --json`
   - `python scripts/check_rule9_open_findings.py --json`
2. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W32-D`.
3. Verify the regression tests still assert the closure: the union of the five gates
   above plus `tests/scripts/test_check_rule9_open_findings.py`.

## Remediation steps

1. Reconcile `current_wave` across `current-wave.txt`, `allowlists.yaml`, the latest
   manifest, the latest non-draft notice, and `recurrence-ledger.yaml`.
2. For any flagged hardcoded `# expiry_wave: Wave N` literal in `hi_agent/` or
   `agent_server/`, either move it to a top-of-module marker or replace it with a
   structural fix.
3. Add a `permanence_rationale` field to any allowlist entry marked
   `expiry_wave: permanent` that lacks one.
4. Refresh the timestamps on `platform-capability-matrix.md`, `TODO.md`, and
   `platform-gaps.md` to reflect the current wave.
5. Annotate `runtime_adapter` `__all__` exports with `scope: public-contract` or
   `scope: process-internal`.
6. Re-run the five gates above to confirm clean pass.

## Recurrence prevention

The release gate at `release-gate.yml` steps `doc_truth / wave_consistency /
allowlist_discipline / no_hardcoded_wave / rule9_open_findings` enforces this in CI.
If any gate has drifted, see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id W32-D
- Code fix history: W32-D D.1 through D.6 (recurrence-ledger current_wave bump,
  hardcoded-wave scan extension, permanence_rationale addition, timestamp refresh,
  `__all__` scope annotation, Rule 9 gate creation)
- Regression test: union of the five `check_*` gates plus
  `tests/scripts/test_check_rule9_open_findings.py`
- Process change: Rule 14 + Rule 17 hardening — every governance YAML with a
  `current_wave` field is in the wave-consistency scan list; every
  `expiry_wave: permanent` allowlist entry carries `permanence_rationale`; production
  code wave-string scan radius matches the source-of-truth shim removal markers
- Related runbook: `docs/runbooks/wave-label-drift-in-recurrence-ledger.md`
  (recurrence of this class)
