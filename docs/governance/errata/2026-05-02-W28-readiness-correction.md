# Errata: W28 verified=94.55 readiness claim — retroactive cap

**Effective**: 2026-05-02 (Wave 31; W31-D, D-10' fix)
**Status**: append-only — do not edit after publication
**Affected artifacts**:
- `docs/releases/archive/W28/platform-release-manifest-2026-05-02-9e607a65.json` (W28 final manifest)
- `docs/downstream-responses/2026-05-02-w28-delivery-notice.md` (W28 delivery notice)
- W28 had **no formal release-captain signoff** (no `wave28-signoff.json` exists in `docs/releases/`).

## What the published artifact said (verbatim)

From `docs/releases/archive/W28/platform-release-manifest-2026-05-02-9e607a65.json`
lines 4767-4775:

> ```json
> "scorecard": {
>   "raw": 94.55,
>   "verified": 94.55,
>   "raw_implementation_maturity": 94.55,
>   "current_verified_readiness": 94.55,
>   "seven_by_twenty_four_operational_readiness": 94.55,
>   "conditional_readiness_after_blockers": 94.55,
>   "cap": null,
>   "cap_reason": "all gates pass",
>   "cap_factors": [],
> ```

The W28 delivery notice repeated this claim, asserting `verified=94.55` and
`7×24=94.55` based on architectural assertions (the W28 cap-retirement reform of the
old wall-clock soak gate).

## What the corrected interpretation is

The W28 verified=94.55 claim was **a metric redefinition, not a re-verified
measurement**. Specifically:

1. **Manifest release-identity break (W29-A root cause).** W28 declared
   `release_head=9e607a65` but after the W28 PR#17 merge `main` HEAD became
   `24742d7d`. Per Rule 14 a stale `release_head` caps `current_verified_readiness`
   at 50. The 94.55 claim was therefore not authoritative even at the moment of
   publication. The escape hatch was the `notice-pre-final-commit: true` marker in
   `check_doc_consistency.py` E1a (added W10.2; never closed). W29-A added
   `scripts/check_notice_pre_final_commit_clean.py` as the recurrence prevention.

2. **Soak-cap retirement without paired-evidence rule (W31-L root cause).** W28's
   `architectural_seven_by_twenty_four` reform replaced the wall-clock 24h soak with
   five architectural assertions (cross-loop stability, lifespan observable,
   cancellation round-trip, spine provenance:real, chaos runtime_coupled:true).
   That reform allowed W28 to retire the wall-clock-soak cap on
   `seven_by_twenty_four_operational_readiness` and consequently report 94.55 in
   that tier without measured soak evidence. **The retirement was not paired with a
   measured-evidence rule** — `score_caps.yaml` after W28 had no soak cap on
   `current_verified_readiness` either, and `build_release_manifest.py`'s
   `_ARCH_CONSTRAINT_GATES` excluded soak/spine/chaos from the `gate_fail` scope on
   the verified tier. W31-L (Track L) re-introduces soak as a cap-retirement gate
   with the **paired-evidence rule**: a cap-retirement may only occur when a
   `provenance: real` evidence artifact at the same wave is present.

3. **No formal signoff for W28.** No `docs/releases/wave28-signoff.json` exists.
   W21..W27 and W29..W30 each have a signoff JSON; W28 does not. The
   `2026-05-02-W28-cap-reason-language.md` errata documents the related
   `cap_reason: "all gates pass"` defect (Rule 14 forbidden phrase).

W29 retroactively closed the release-identity break; W31-L closes the
paired-evidence rule. The corrected interpretation of W28 readiness is:

- W28 `current_verified_readiness` should have been **capped at 70**
  (`release_head_mismatch` cap per Rule 14 §4.2) at the time of publication.
- W28 `seven_by_twenty_four_operational_readiness` 94.55 is a **redefinition score**,
  not a measured score. Future cap-retirement requires paired real evidence (W31-L).
- The W28 delivery notice should be read as **historical commentary**, not a
  release-readiness claim, on a HEAD that was never the release HEAD.

## Recurrence prevention

- **Notice pre-final-commit clean** — `scripts/check_notice_pre_final_commit_clean.py`
  (W29-A, commit `9add02bc`). Fails CI when the latest active notice carries
  `notice-pre-final-commit: true`.
- **Cap-retirement paired-evidence rule** — W31-L Track L deliverables
  (`scripts/check_score_cap.py` paired-evidence rule + `tests/scripts/test_score_cap_paired_evidence.py`).
- **Stale W28 manifest relocation** — W29-A moved
  `docs/releases/platform-release-manifest-2026-05-02-9e607a65.json` to
  `docs/releases/archive/W28/`. Documented in
  `2026-05-02-W28-manifest-path-relocation.md` errata.
- **Recurrence ledger** — `docs/governance/recurrence-ledger.yaml` entry
  (W29-A; named instance at line 404 referencing the W28 release_head mismatch).
- **Rule 14** — Score is three-tier; manual score increases are prohibited; score
  must be derived from manifest facts.
- **Rule 15** — Closure-claim taxonomy: "all gates pass" without evidence at the
  release HEAD is not a valid closure claim.

---

## L-track perspective (W31-L appendix)

Audit perspective from W31-L (gov-track L: integrity gap closure on the
score-cap / soak / evidence-provenance trio). This appendix is appended on
2026-05-03 (W31-L atomic close); all earlier sections remain unchanged.

### Metric-redefinition mechanics

The W28 verified score moved from W27's 65 to W28's 94.55 — a 29.55-point
jump with no offsetting engineering commit. The mechanics:

1. W28 retired the wall-clock-soak cap on `seven_by_twenty_four_operational_readiness`
   (the only tier that previously reflected soak evidence at all).
2. W28 added `score_caps.yaml::architectural_seven_by_twenty_four` which evaluates
   five static assertions emitted by `scripts/run_arch_7x24.py`.
3. W28 left `_ARCH_CONSTRAINT_GATES` containing `soak_evidence`, so any
   real FAIL on soak via `scripts/check_soak_evidence.py` did NOT contribute
   to `gate_fail` on `current_verified_readiness` either.
4. The combined effect: the verified tier had **no soak signal at all**.
   Verified jumped 65 → 94.55 because the cap that previously held 65 was
   removed without any replacement.

This is the metric-redefinition pattern: scores changed by changing the
scoring rule, not by improving the system being scored. The W28 delivery
notice did not flag this — the notice asserted the new score as a
measurement.

### Integrity-gap acknowledgement

Per Rule 14 §5 (no manual score increases) and the closure-claim taxonomy
(Rule 15), W28's verified=94.55 claim was an integrity gap. The gap was
not detected at W28 publication time, was not detected at W29 either
(W29 inherited the same scoring rules), and only surfaced during the
W31-L audit when the ratio of "wall-clock soak evidence" to "score
inflation" was computed. W31-L re-introduces soak as a cap-retirement
gate AND adds the paired-evidence rule, closing both halves of the gap.

### W31-L corrections (this wave)

The L-track delivers four interlocking corrections, each with a paired
test:

| Defect | Code fix | Test |
|---|---|---|
| L-1' (`check_soak_evidence` --strict) | scripts/check_soak_evidence.py | tests/unit/scripts/test_check_soak_evidence_strict.py |
| L-2' (HEAD-tied arch-7x24 lookup) | scripts/build_release_manifest.py:_find_arch_evidence_for_head | tests/unit/scripts/test_build_release_manifest_head_tied.py |
| W31-G1 (paired-evidence rule) | scripts/check_score_cap.py:_check_paired_evidence | tests/unit/scripts/test_score_cap_paired_evidence.py |
| L-5' (provenance strict for real-required gates) | scripts/check_evidence_provenance.py:_DISALLOWED_FOR_STRICT | tests/unit/scripts/test_check_evidence_provenance_strict.py |
| L-12'/L-13' (soak cap on verified tier) | scripts/build_release_manifest.py:_ARCH_CONSTRAINT_GATES + score_caps.yaml | tests/unit/scripts/test_soak_evidence_not_real_cap.py |
| L-15' (run_soak strict polling) | scripts/run_soak.py:--require-polling-observation | tests/unit/scripts/test_run_soak_require_polling.py |

Each correction is small and surgical; their union closes the
metric-redefinition vector at every layer it can re-emerge:
- Cap-retirement validation (W31-G1 paired-evidence + L-5' provenance)
- Cap-coverage on the primary tier (L-12'/L-13')
- HEAD-tied evidence lookup (L-2', preventing stale evidence from
  silently clearing caps)
- Strict observability requirement (L-15', preventing fast-completing
  runs from substituting structural signals for live observability)
- CI strict failure on missing evidence (L-1' --strict)

### What this errata does NOT do

- Does NOT retroactively rewrite `docs/releases/archive/W28/platform-release-manifest-2026-05-02-9e607a65.json`.
  Per Rule 14, published artifacts are immutable. The W28 manifest stays as-is.
- Does NOT recompute W28's score. The audit interpretation in the
  "Corrected interpretation" section above is binding for downstream readers,
  but the manifest field values are not edited.
- Does NOT block the W31 manifest from being built. W31's verified tier
  will reflect the new soak_evidence_not_real cap; if no real soak evidence
  is produced at W31 final HEAD, W31 verified is capped at 75. That is the
  intended (honest) outcome.
