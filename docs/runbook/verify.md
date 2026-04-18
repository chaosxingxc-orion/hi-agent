# hi-agent Verification Runbook

This runbook covers how to verify a running hi-agent instance is healthy and operating correctly in prod-real mode.

## Quick health check

```bash
curl -s localhost:8080/health
```

Expected: HTTP 200, body contains `"status": "ok"`.

## Runtime mode verification

```bash
curl -s localhost:8080/manifest | jq .runtime_mode
```

| Environment | Expected value |
|-------------|---------------|
| Local dev | `"dev-smoke"` |
| Local with real kernel | `"local-real"` |
| Production | `"prod-real"` |

If `runtime_mode` does not match the expected value, do not proceed — diagnose with `python -m hi_agent ops doctor`.

## Subsystem readiness

```bash
curl -s localhost:8080/ready | jq .
```

All subsystems must report `"status": "pass"`. Any `"status": "fail"` entry is a blocking issue.

Key subsystems to verify:

- `capability_registry` — capability handlers registered
- `route_engine` — routing rules loaded
- `context_manager` — context budget configured
- `memory` — L0 raw memory store writable
- `llm_gateway` — LLM model tier configured

## Release gate check

```bash
python -m hi_agent ops release-gate
```

A release-ready system should show:

```
readiness         pass
doctor            pass
config_validation pass
current_runtime_mode  info  prod-real
known_prerequisites   pass
mcp_health        pass  (or skipped if no MCP configured)
prod_e2e_recent   pass
```

The `prod_e2e_recent` gate failing means no prod-real execution has been recorded in the last 24 hours — run a prod smoke test to unblock.

## Episodic store check

Verify recent executions are being persisted:

```bash
ls -lt .hi_agent/episodes/ | head -5
```

Each `.json` file should have a `runtime_mode` of `"prod-real"` when running in production.

## Post-run provenance check

After executing a run in prod:

```bash
curl -s localhost:8080/runs/<run_id> | jq '{
  runtime_mode: .execution_provenance.runtime_mode,
  fallback_used: .execution_provenance.fallback_used,
  contract_version: .execution_provenance.contract_version
}'
```

Expected in prod-real:

```json
{
  "runtime_mode": "prod-real",
  "fallback_used": false,
  "contract_version": "2026-04-17"
}
```

`fallback_used: true` indicates real capabilities were not available and a fallback path was taken — treat as a degraded execution.

## Evolve policy verification

In production, evolve should be effectively disabled unless explicitly approved:

```bash
curl -s localhost:8080/manifest | jq .evolve_policy
```

Expected:

```json
{"mode": "auto", "effective": false, "source": "env"}
```

If `effective` is `true` in prod-real mode, skill evolution mutations may run autonomously. Escalate to an approver before proceeding.

## RBAC verification (prod-real)

In prod-real mode, mutation routes require the `approver` role:

```bash
# Should return 403 without auth token
curl -s -X POST localhost:8080/skills/test/promote | jq .status_code
```

Expected: `403` (Forbidden). A `200` response without auth means RBAC is not active.
