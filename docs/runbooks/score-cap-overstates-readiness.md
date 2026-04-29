# Runbook: Score Cap Overstates Readiness

## Symptom
`check_score_cap.py` or the release manifest shows `current_verified_readiness` higher than what gate evidence supports.

## Cause
A cap factor was removed, a dimension base_score was bumped manually, or the manifest HEAD does not match the current HEAD.

## Resolution
1. Run `python scripts/build_release_manifest.py --dry-run` to see the computed score.
2. Cross-check each dimension: verify the gate evidence file supports the claimed base_score.
3. If a score was bumped without CI evidence, revert the bump in `docs/scorecard_weights.yaml`.
4. Re-run failing gates and regenerate the manifest.

## Prevention
Score bumps require a passing CI gate. Never modify base_score without accompanying green gate evidence.
