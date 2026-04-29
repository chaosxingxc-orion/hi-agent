# Runbook: manifest_stale (P0-1)

**Alert**: `hi_agent_manifest_freshness_violations_total > 0 for 5m`
**Owner**: GOV
**Severity**: Warning (blocks release, not runtime)

## What this alert means

The release manifest (`docs/releases/platform-release-manifest-*.json`) has either:
- `release_head != git rev-parse HEAD` (manifest is stale), or
- `is_dirty == true` (uncommitted changes exist at build time)

Per Rule 14, a stale manifest caps `current_verified_readiness` at 70 and blocks release claim.

## Immediate actions

1. Check current HEAD vs manifest head:
   ```bash
   git rev-parse HEAD
   python scripts/check_manifest_freshness.py
   ```

2. If stale due to new commits since manifest: re-run manifest build at current HEAD:
   ```bash
   python scripts/build_release_manifest.py
   ```

3. If stale due to dirty working tree: commit or discard changes, then rebuild manifest.

4. If the manifest itself was never built: run the full release gate sequence (see Rule 14 order of operations).

## Root cause investigation

Run: `python scripts/check_manifest_freshness.py --verbose`

Check:
- Is there a gap between manifest HEAD and current HEAD?
- Which commits landed after the manifest was built? (`git log <manifest_head>..HEAD`)
- Are those commits functional (touching code) or docs-only?

## Escalation

If manifest rebuild fails (non-zero exit from `build_release_manifest.py`), escalate to the release captain.
If the alert fires in production monitoring (not just CI), a release process violation has occurred — file a recurrence-ledger entry.

## Metric definition

Counter: `hi_agent_manifest_freshness_violations_total`
- Incremented by `scripts/check_manifest_freshness.py` when violations are detected
- Labels: none (aggregate count only)
- Reset: counter resets on process restart; use `rate()` for alerting

## Prevention

- `scripts/check_manifest_freshness.py` is blocking in `release-gate.yml`
- Rule 14 Step 9 requires manifest to be built after all implementation commits
- No commits allowed between final manifest and closure notice publication (except manifest, notice, signoff)
