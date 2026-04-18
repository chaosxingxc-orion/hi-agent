# hi-agent Deployment Runbook

## Pre-deployment checklist

- [ ] All tests passing: `python -m pytest -q`
- [ ] Ruff clean: `python -m ruff check .`
- [ ] Release gate passes: `python -m hi_agent ops release-gate`
- [ ] `prod_e2e_recent` gate: recent prod-real execution exists in `.hi_agent/episodes/`
- [ ] `HI_AGENT_ENV` is set to `prod` in the target environment
- [ ] `ANTHROPIC_API_KEY` is configured and valid
- [ ] Episodic store directory `.hi_agent/episodes/` is writable

## Deployment steps

1. **Set environment variables**

   ```bash
   export HI_AGENT_ENV=prod
   export ANTHROPIC_API_KEY=<your-key>
   export HI_AGENT_EPISODES_DIR=.hi_agent/episodes  # default; override if needed
   ```

2. **Start the server**

   ```bash
   python -m hi_agent serve --port 8080
   ```

3. **Health check**

   ```bash
   curl localhost:8080/health
   ```

   Expected: `{"status": "ok"}` or equivalent green response.

4. **Verify manifest**

   ```bash
   curl localhost:8080/manifest | jq .runtime_mode
   ```

   Expected: `"prod-real"`

   Also check:

   ```bash
   curl localhost:8080/manifest | jq '{runtime_mode, evolve_policy, provenance_contract_version}'
   ```

   Expected shape:

   ```json
   {
     "runtime_mode": "prod-real",
     "evolve_policy": {"mode": "auto", "effective": false, "source": "env"},
     "provenance_contract_version": "2026-04-17"
   }
   ```

## Post-deployment verification

- Check `/ready` returns all subsystems green — no `"status": "fail"` entries.
- Run smoke test:

  ```bash
  curl -s -X POST localhost:8080/runs \
    -H 'Content-Type: application/json' \
    -d '{"goal": "smoke test", "task_family": "ops"}' | jq .run_id
  ```

- Confirm `execution_provenance.fallback_used` is `false` in the smoke run result:

  ```bash
  curl localhost:8080/runs/<run_id> | jq .execution_provenance.fallback_used
  ```

  Expected: `false`

## Release gate CLI

Run the full gate report before any deployment:

```bash
python -m hi_agent ops release-gate
```

All gates must show `pass` or `skipped` (never `fail`). The `prod_e2e_recent` gate is a **hard gate** — a `fail` here blocks deployment.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `prod_e2e_recent` gate fails | No recent prod run in episodic store | Run a prod-real execution before deploying |
| `runtime_mode` is `dev-smoke` in prod | `HI_AGENT_ENV` not set or wrong | Set `HI_AGENT_ENV=prod` |
| `/ready` shows subsystem failures | Wiring or dependency missing | Check `python -m hi_agent ops doctor` |
| `evolve_policy.effective` is `true` in prod | `EVOLVE_MODE` overriding auto policy | Unset `EVOLVE_MODE` or set to `off` |
