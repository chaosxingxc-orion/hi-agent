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
