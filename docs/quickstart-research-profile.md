# Quickstart: Research Profile (30 minutes)

This guide walks you through setting up hi-agent in **research posture** — the configuration used by research teams who need durable run history, project scoping, and artifact persistence.

## Prerequisites

- Python 3.11+
- `pip install hi-agent` (or the repo cloned and installed with `pip install -e .`)
- An LLM API key: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`

---

## Step 1 — Scaffold the config directory

```bash
hi-agent init --posture research --config-dir ./my_config
```

Expected output:

```
  write: /path/to/my_config/hi_agent_config.json
  write: /path/to/my_config/profiles/research.json
  write: /path/to/my_config/.env.example
Scaffolded research config at /path/to/my_config
```

This creates three files:

| File | Purpose |
|------|---------|
| `my_config/hi_agent_config.json` | Runtime tunables (concurrency, queue size, rate limits) |
| `my_config/profiles/research.json` | Minimal valid research profile |
| `my_config/.env.example` | Documents required env vars |

---

## Step 2 — Set your data directory and credentials

Research posture requires a **durable data directory** for run history and artifacts.

```bash
export HI_AGENT_DATA_DIR=./my_data
mkdir -p ./my_data

# Set at least one LLM key:
export ANTHROPIC_API_KEY=sk-ant-...
# or:
export OPENAI_API_KEY=sk-...
```

---

## Step 3 — Run the health check

```bash
HI_AGENT_CONFIG_DIR=./my_config hi-agent doctor
```

Expected: all checks pass or warn about optional env vars. Any `[FAIL]` line must be resolved before proceeding.

If `HI_AGENT_DATA_DIR` is not set, you will see a blocking check:

```
[FAIL] [posture] HI_AGENT_DATA_DIR is required under research posture
  fix: set HI_AGENT_DATA_DIR=/var/hi_agent (or any writable directory)
```

---

## Step 4 — Export posture and config dir

Set the two required env vars for all subsequent commands in this session:

```bash
export HI_AGENT_POSTURE=research
export HI_AGENT_CONFIG_DIR=./my_config
```

---

## Step 5 — Start the server

```bash
python -m hi_agent serve --port 8080
```

You should see log output ending with something like:

```
INFO     hi_agent.server.app: hi-agent serving on http://0.0.0.0:8080
```

Leave this running. Open a new terminal for the following steps.

---

## Step 6 — Submit a first run

```bash
curl -s -X POST http://localhost:8080/runs \
  -H "Content-Type: application/json" \
  -d '{"goal": "hello world", "project_id": "proj-1", "profile_id": "research"}' \
  | python -m json.tool
```

Expected response (`201 Created`):

```json
{
  "run_id": "run-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "state": "pending",
  "created_at": "2026-04-25T10:00:00Z"
}
```

Save the `run_id` for the next step:

```bash
RUN_ID=run-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Step 7 — Check the run status

```bash
curl -s http://localhost:8080/runs/$RUN_ID | python -m json.tool
```

The `state` field transitions through: `pending` → `running` → `done` (or `failed`).

Poll until the state reaches a terminal value:

```bash
watch -n 2 "curl -s http://localhost:8080/runs/$RUN_ID | python -m json.tool"
```

---

## Step 8 — Check artifacts

Once the run is complete, list artifacts scoped to your project:

```bash
curl -s http://localhost:8080/artifacts/by-project/proj-1 | python -m json.tool
```

Expected response:

```json
{
  "project_id": "proj-1",
  "artifacts": [...]
}
```

---

## Step 9 — Verify durability (restart the server)

Stop the server (`Ctrl-C`), then restart it:

```bash
python -m hi_agent serve --port 8080
```

Now re-check the run — it should still be retrievable:

```bash
curl -s http://localhost:8080/runs/$RUN_ID | python -m json.tool
```

If the run state is preserved, your durable backend is working correctly. If it returns 404, check that `HI_AGENT_DATA_DIR` is set to the same directory as in Step 2.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `400 {"error": "missing_project_id"}` | Research posture enforces project_id | Add `"project_id": "..."` to the request body |
| `503 {"error": "queue_full"}` | Run queue at capacity | Increase `run_manager.max_concurrent` in `hi_agent_config.json` or wait |
| Run state stuck at `pending` | No LLM credentials | Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` |
| Doctor reports `blocking` on data_dir | `HI_AGENT_DATA_DIR` not set | `export HI_AGENT_DATA_DIR=/var/hi_agent` |

---

## Next steps

- Read `docs/posture-reference.md` for the full posture feature table
- Read `docs/api-reference.md` for all available endpoints
- Migrate to prod posture: see the checklist in `docs/posture-reference.md`
