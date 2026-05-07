# Prod-E2E Skeleton Activation

**Status:** active
**Origin:** ledger entry W28-D
**Last updated:** 2026-05-07

## What this is

Four `prod_e2e` skeleton tests in `tests/e2e/test_e2e_trajectory_replay.py` (lines 17, 31, 43, 55) remain `@pytest.mark.skip`-ed at Wave 28 close. They exercise trajectory replay against a real PM2 + real-LLM operator shape, which has not been validated in CI. The reformed Rule 8 (architectural 7x24) does not replace the need for `prod_e2e` profile coverage; these tests must run against operator-shape infrastructure before the skips are lifted.

## When to use this runbook

- Triggered by: `hi_agent_prod_e2e_skipped_total` firing (skipped count fails to drop)
- Triggered by: `hi_agent_prod_e2e_skipped_alert`
- During: when operator-shape CI infrastructure (real PM2 + real-LLM lane) becomes available, or routine quarterly burndown review

## Diagnostic steps

1. Inspect the skip markers in `tests/e2e/test_e2e_trajectory_replay.py` at lines 17, 31, 43, 55. Confirm each carries the expected `expiry_wave` reason.
2. Verify which `prod_e2e` profile in `tests/profiles.toml` the tests target, and whether the matching CI job exists in `.github/workflows/`.
3. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W28-D` (defect_class `prod_e2e_skeleton_activation`).
4. Confirm the regression-test commitment in the ledger: "run tests under `prod_e2e` profile with real LLM; unskip passing tests".

## Remediation steps

1. Stand up the `prod_e2e` operator-shape lane (long-lived process, real LLM, real artifacts) per CLAUDE.md Rule 16's profile taxonomy.
2. Run the four trajectory-replay tests under the `prod_e2e` profile against the operator-shape harness.
3. Unskip each test that passes; for tests that surface real defects, file the defects rather than re-skipping.
4. Re-run `scripts/check_pytest_skip_discipline.py` to confirm the W29 expiry trigger no longer fires.

## Recurrence prevention

The release gate at `scripts/check_pytest_skip_discipline.py` enforces this in CI: each skip carries an `expiry_wave` reason, and the gate fails closed when `current_wave` exceeds expiry. CLAUDE.md Rule 16 requires the `prod_e2e` profile validation before skips on operator-shape tests can be lifted. If the gate has drifted (script renamed, workflow not invoking it, or the skip bumped without structural fix), see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id `W28-D`
- Code fix history: W29 target -- run under `prod_e2e` profile with real LLM, unskip passing tests
- Regression test: `tests/e2e/test_e2e_trajectory_replay.py` lines 17, 31, 43, 55 (unskipped)
- Process change: CLAUDE.md Rule 16 (test profile taxonomy) -- `prod_e2e` profile required before skip can be lifted
- Triage record: `docs/governance/wave-28-expiry-triage.md#group-7`
