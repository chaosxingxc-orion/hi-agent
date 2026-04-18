# hi-agent Rollback Runbook

Use this runbook when a deployment must be reversed due to a runtime failure, bad release gate result, or incident.

## Decision criteria for rollback

Roll back immediately if any of the following are true:

- `/health` returns non-200 after deployment
- `runtime_mode` in `/manifest` does not match `"prod-real"` in prod
- `/ready` shows one or more subsystem failures that cannot be hot-fixed in < 10 minutes
- Active runs are failing with `execution_budget_exhausted` or `harness_denied` at elevated rates
- `fallback_used: true` on more than 5% of runs (real capabilities unavailable)

## Rollback steps

### 1. Stop the current server

```bash
# Send SIGTERM to the running process
kill -TERM <pid>

# Or if managed by systemd
systemctl stop hi-agent
```

The server handles SIGTERM gracefully: in-flight runs will be checkpointed before shutdown.

### 2. Restore the previous binary / checkout

```bash
# Git-based rollback: restore previous commit
git checkout <previous-tag-or-sha>

# Or restore from artifact store if using packaged releases
cp /releases/hi-agent-<prev-version>/ /opt/hi-agent/ -r
```

### 3. Verify rollback target

Before starting the old version, confirm its release gate would pass:

```bash
python -m hi_agent ops release-gate
```

If `prod_e2e_recent` fails against the old version, it means no recent prod run was recorded by the old version either — this gate check can be skipped during emergency rollback with explicit team approval, documented in the incident log.

### 4. Restart the server

```bash
export HI_AGENT_ENV=prod
export ANTHROPIC_API_KEY=<your-key>
python -m hi_agent serve --port 8080
```

### 5. Verify restored health

```bash
curl localhost:8080/health
curl localhost:8080/manifest | jq .runtime_mode
curl localhost:8080/ready | jq '[.subsystems[] | select(.status == "fail")]'
```

All three checks must pass before declaring rollback complete.

### 6. Resume interrupted runs (if needed)

Runs that were checkpointed during shutdown can be resumed:

```bash
python -m hi_agent resume --checkpoint .checkpoint/checkpoint_<run_id>.json
```

List available checkpoints:

```bash
ls .checkpoint/
```

## Post-rollback actions

- File an incident ticket with: rollback trigger, affected runs, time to recovery.
- Check episodic store for any corrupt entries written by the bad version:

  ```bash
  for f in .hi_agent/episodes/*.json; do python -c "import json; json.load(open('$f'))" 2>&1 | grep -v "^$" && echo "BAD: $f"; done
  ```

- Run the full test suite on the restored version to confirm baseline:

  ```bash
  python -m pytest -q
  ```

- Do not re-deploy the rolled-back version until root cause is identified and a new release gate run passes cleanly.
