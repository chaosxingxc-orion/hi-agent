# Release Identity Atomic Commit

**Status:** active
**Origin:** ledger entry W28-E
**Last updated:** 2026-05-07

## What this is

`scripts/check_release_identity.py` currently runs with `--allow-docs-only-gap` because the manifest, closure notice, and signoff are not produced atomically in CI. `scripts/build_release_manifest.py` runs locally and the manifest is committed in a docs-only follow-on commit; CI cannot generate-and-commit the manifest atomically because the release-gate workflow has no push access. The `--allow-docs-only-gap` flag exempts this legitimate structural gap, but it is also the door through which the W17 / W28 escape-hatch class re-entered (see ledger entry `P0-W28`).

## When to use this runbook

- Triggered by: `hi_agent_manifest_identity_gap_total` firing (the gap window persists across waves)
- Triggered by: `hi_agent_manifest_identity_gap_alert`
- During: when designing the W29+ atomic-manifest pipeline, or routine quarterly burndown review

## Diagnostic steps

1. Inspect the current release-gate invocation: locate the `check_release_identity` step in `.github/workflows/release-gate.yml` and confirm whether `--allow-docs-only-gap` is still passed.
2. Run `python scripts/check_release_identity.py --json` locally and inspect the gap classification (`docs_only_gap` vs `gov_only_gap` vs `functional_commit`).
3. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W28-E` (defect_class `release_identity_atomic_commit`).
4. Read the companion entry `P0-W28` (notice-pre-final-commit escape hatch) to understand why the atomic-commit target matters.
5. Confirm the regression-test commitment in the ledger: "`check_release_identity.py` passes without `--allow-docs-only-gap`".

## Remediation steps

1. Design the CI-native manifest pipeline so the manifest, closure notice, and release-captain signoff land in a single atomic commit at the final HEAD. Evaluate the release-captain bot approach noted in the ledger.
2. Remove `--allow-docs-only-gap` from the `check_release_identity` step in `release-gate.yml` once atomic generation is live.
3. Update CLAUDE.md Rule 14 reference if the order of operations changes.
4. Re-run the release gate end-to-end on a dry-run wave to confirm `check_release_identity.py` passes without the exemption flag.

## Recurrence prevention

The release gate at `scripts/check_release_identity.py` enforces release-identity invariants in CI. While `--allow-docs-only-gap` is in place, CLAUDE.md Rule 14's "no commits between final manifest HEAD and closure notice publication" rule is the compensating control. The `manifest_freshness` gate (see `docs/runbooks/manifest-stale.md`) and the `notice_pre_final_commit` gate from `P0-W28` also enforce subsets of this invariant. If any of these gates drift (script renamed, workflow not invoking it, or new exemptions added), see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id `W28-E`
- Companion entry: `docs/governance/recurrence-ledger.yaml` issue_id `P0-W28` (notice-pre-final-commit escape hatch)
- Code fix history: W29 target -- design CI-native manifest generation with atomic commit
- Regression test: W29 target -- `check_release_identity.py` passes without `--allow-docs-only-gap`
- Process change: CLAUDE.md Rule 14 (manifest is the single release fact source); W29 TODO annotation in `release-gate.yml`
- Triage record: `docs/governance/wave-28-expiry-triage.md#group-8`
