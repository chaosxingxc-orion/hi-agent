# Runbook: Wave Debt Burndown (P0-W29)

**Status:** active (HIGH severity)
**Origin:** ledger entry P0-W29 (and subsequent P0-W30 cycle-termination)
**Last updated:** 2026-05-07

## What this is

A wave-cycle / burndown discipline runbook. Multiple consecutive waves (W26 through
W29) collectively bumped 597 inline suppressions forward by one wave each with no
structural closure — paperwork-only deferrals. P0-W29 forbade another bump; P0-W30
terminated the cycle by classifying inherited markers as `expiry_wave: permanent`
where they were legitimate Rule 7 exceptions, and committed to structural fixes
(refactor + remove marker) for the rest. This runbook is HIGH severity because the
paperwork cycle hides structural debt growth behind clean gate output.

The canonical debt list is `docs/governance/recurrence-ledger.yaml`. Every wave's
burndown meeting must reconcile against this single source.

## When to use this runbook

- Triggered by: `hi_agent_wave_bound_debt_count` increase wave-over-wave
- Triggered by: `hi_agent_wave_bound_debt_alert` firing
- During: every wave-planning meeting (read the ledger, allocate explicit closure
  capacity)
- During: every wave-close review (verify no new paperwork-only bumps landed)
- During: any PR that touches `expiry_wave:` markers

## Diagnostic steps

1. Read the ledger and count entries by `current_closure_level`:
   - `python scripts/check_recurrence_ledger.py --json`
2. Run the three burndown gates and inspect their output:
   - `python scripts/check_expired_waivers.py --json`
   - `python scripts/check_noqa_discipline.py --json`
   - `python scripts/check_silent_degradation.py --json`
3. Identify which `expiry_wave` markers are about to fire next wave. For each,
   classify into:
   - **Structural-fix candidate**: refactor + remove marker
   - **Permanent-acceptance candidate**: `expiry_wave: permanent` with rationale
     next to the marker
   - **Forbidden bump**: `expiry_wave: Wave N+1` with no structural change
4. Cross-reference with the ledger entry:
   `docs/governance/recurrence-ledger.yaml::P0-W29` and `::P0-W30`.

## Remediation steps

1. Allocate explicit closure capacity in the current wave plan for some subset of
   the 597. Bumping `expiry_wave: permanent -> Wave N` is forbidden — that would
   re-introduce the cycle.
2. For each marker chosen for closure:
   - Apply the structural fix (refactor, narrow except, replace silent fallback,
     remove deprecated shim, etc.)
   - Remove the suppression
   - Re-run the relevant gate to confirm the marker is gone, not bumped
3. For markers that remain legitimate Rule 7 exceptions (e.g., structural typing
   gaps, re-export shims, test-only monkey-patching), mark them
   `expiry_wave: permanent` with an explicit acceptance rationale next to the
   marker. The rationale is required.
4. Re-run the three burndown gates above to confirm clean pass.
5. Update the ledger entries (P0-W29 / P0-W30 if the closure level changes).

## Recurrence prevention

The release gate at `release-gate.yml` steps `expired_waivers / noqa_discipline /
silent_degradation` enforces this in CI.

Rule 17 hardening (per P0-W30 process change): future waves MUST close any subset
of the 597 by structural fix (refactor + remove marker). Bumping
`expiry_wave: permanent -> Wave N` is forbidden. The reverse direction
(`Wave N -> permanent`) is acceptable only with explicit acceptance rationale next
to the marker.

If the gate has drifted, see runbook `release-gate-weakening.md`.

## References

- Ledger entries: `docs/governance/recurrence-ledger.yaml` issue_ids P0-W29
  (paperwork deferral cycle), P0-W30 (cycle termination via permanent
  classification)
- Code fix history: W29 bulk-bump (594 lines / 266 files); W30-B classified 597
  suppressions as `expiry_wave: permanent`; W30-A added permanent recognition to
  `check_noqa_discipline.py`
- Regression test: `check_noqa_discipline.py` + `check_silent_degradation.py` +
  `check_expired_waivers.py` — all PASS at HEAD; `ruff` (full) clean
- Process change: Rule 17 hardening (no `permanent -> Wave N` bumps; structural
  fix or permanent acceptance with rationale)
- Owner track: GOV
