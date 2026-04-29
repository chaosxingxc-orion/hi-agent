# Runbook: Clean-Env Not at Final HEAD

## Symptom
`check_clean_env.py` fails: no clean-env verification JSON exists at the current HEAD SHA.

## Cause
A functional commit landed after the last `verify_clean_env.py` run, invalidating the clean-env evidence.

## Resolution
1. Run `python scripts/verify_clean_env.py --profile default-offline` on the current HEAD.
2. Verify ≥8723 tests pass, `failure_reason=null`.
3. Commit the new verification JSON.
4. Re-run the release gate.

## Prevention
Wire `check_clean_env.py` as a blocking CI gate in `release-gate.yml`.
