# Incident Guide: Evolve Unexpected Skill Mutation

**Severity**: P1 (unexpected skill mutations in prod can change agent behavior irreversibly)  
**Category**: Governance / Skill evolution

## Symptoms

- A skill's behavior changed unexpectedly between runs without an explicit promote action
- `/manifest` shows `evolve_policy.effective: true` in prod-real mode
- Logs contain `SkillEvolver: applied gradient` or `skill promoted to champion`
- A skill A/B test outcome changed the production skill without approver sign-off
- `POST /skills/{id}/evolve` succeeded without auth in prod-real mode

## Immediate containment

### 1. Freeze skill evolution immediately

```bash
export EVOLVE_MODE=off
# Then restart or send config reload signal
python -m hi_agent ops config reload --key evolve_mode --value off
```

Verify:

```bash
curl -s localhost:8080/manifest | jq .evolve_policy
# Expected: {"mode": "off", "effective": false, "source": "env"}
```

### 2. Identify mutated skills

```bash
curl -s localhost:8080/skills | jq '[.[] | select(.last_mutation_at != null) | {id, version, last_mutation_at}]'
```

Skills mutated in the last 24 hours are candidates for rollback.

### 3. Pin the affected skill to its last known-good version

```bash
curl -X POST localhost:8080/skills/<skill-id>/pin --data '{"version": "<last-good-version>"}'
```

This prevents further champion/challenger promotion until the pin is explicitly removed by an approver.

## Investigation steps

### Check evolve mode history

```bash
python -m hi_agent ops audit --type evolve_mode --since 24h
```

Look for a `evolve_mode_changed` audit event that transitioned `effective` to `true`.

### Review the mutation event

```bash
curl -s localhost:8080/skills/<skill-id>/history | jq '.[0]'
```

Key fields to examine:

- `trigger`: should be `approver_action`; if `auto_gradient` it means auto-evolution fired
- `champion_score` vs `challenger_score`: was the promotion statistically valid?
- `approver_id`: should be present for all prod-real promotions

### Check RBAC state at time of mutation

If `POST /skills/{id}/promote` succeeded without auth, RBAC may have been bypassed:

```bash
curl -s localhost:8080/auth/audit | jq '[.[] | select(.route | contains("promote"))]'
```

Expected in prod-real: all promote requests require `role=approver` JWT claim.

## Recovery

### Roll back the skill

```bash
curl -X POST localhost:8080/skills/<skill-id>/rollback \
  -H 'Authorization: Bearer <approver-token>' \
  --data '{"target_version": "<last-good-version>", "reason": "incident rollback"}'
```

### Verify rollback

Run a test execution that exercises the rolled-back skill and confirm behavior matches the expected baseline:

```bash
python -m pytest tests/integration/ -k "skill" -v
```

### Remove freeze after root cause is confirmed

```bash
unset EVOLVE_MODE  # Return to "auto" default
python -m hi_agent ops config reload --key evolve_mode --value auto
```

Only remove the freeze after:
1. Root cause is documented
2. The fix (RBAC re-enforcement or evolve policy correction) is deployed and verified
3. An approver has signed off

## Root cause patterns

| Root cause | Fix |
|-----------|-----|
| `EVOLVE_MODE` env var not set in prod | Set `EVOLVE_MODE=auto` explicitly; do not rely on default |
| RBAC middleware not wired in prod config | Verify `@require_operation` is active on all mutation routes |
| Champion/challenger auto-promoted by scheduler | Disable `DreamScheduler` auto-promotion in prod; require manual approve |
| Dev bypass active in prod-real mode | Check `HI_AGENT_ENV` — a mislabeled env may run in dev-smoke mode |

## Prevention

- Always confirm `/manifest.evolve_policy.effective` is `false` before releasing to prod
- The `@require_operation` decorator on `/skills/{id}/promote`, `/skills/evolve`, `/memory/consolidate` is enforced in prod-real mode — do not remove without architecture review
- Run `test_runner_evolve_gated.py` and `test_inline_evolution.py` as part of CI
- Require dual-approver sign-off for any changes to `EvolveMode` defaults
