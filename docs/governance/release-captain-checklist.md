# Release Captain Checklist

One named release captain per delivery. The captain is accountable for release truth.

## Captain Role

- Assigned at the start of the wave's Track J (final assembly).
- Owns: final HEAD, manifest, evidence completeness, score caps, notice consistency.
- Signs off before any push to main.
- Downstream MUST NOT discover stale evidence before the captain does.

## Pre-Push Signoff Matrix

Complete all rows before running `git push`.

| Item | Gate Script | Status |
|---|---|---|
| Final HEAD locked — no more code commits | `git status` clean | [ ] |
| Manifest at final HEAD | `check_manifest_freshness.py --json` → pass | [ ] |
| Release identity consistent (3 SHAs match) | `check_release_identity.py --json` → pass | [ ] |
| Doc consistency passes | `check_doc_consistency.py --json` → pass | [ ] |
| Clean-env artifact at final HEAD | `verify_clean_env.py` + head matches | [ ] |
| T3 evidence fresh (not stale after hot-path) | `check_t3_freshness.py` → pass | [ ] |
| Observability spine provenance=real | `check_observability_spine_completeness.py` → pass | [ ] |
| Chaos matrix runtime_coupled=true | `check_chaos_runtime_coupling.py` → pass | [ ] |
| Operator drill all_passed=true | `check_operator_drill.py` → pass | [ ] |
| Recurrence ledger complete | `check_recurrence_ledger.py` → pass | [ ] |
| Score cap correctly reflects deferred items | `check_score_cap.py` → pass | [ ] |
| Notice derived from manifest (no independent facts) | Visual review | [ ] |
| Wave label consistent across sources (W17/B11) | `check_wave_consistency.py --json` → pass | [ ] |
| No untracked release artifacts (W17/B13) | `check_untracked_release_artifacts.py --json` → pass | [ ] |
| Manifest rewrite budget within limit (W17/B19) | `check_manifest_rewrite_budget.py --json` → pass | [ ] |

## What Disqualifies a Captain

- The captain cannot sign off if they authored the delivery notice independently of the manifest.
- The captain cannot sign off if any gate above reports `fail` (not `deferred`).
- The captain cannot sign off if the notice Functional HEAD differs from `git rev-parse HEAD`.
- A captain who signs off on a delivery that downstream then finds stale must document root cause in the recurrence ledger.

## Signature Line

```
Wave: ___________
Captain: ___________
Date: 2026-___-___
Signed off at HEAD: ________________________________
All 15 items above checked: YES / NO
```
