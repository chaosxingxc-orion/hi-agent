# Operator Runbook

This runbook covers day-2 operations for hi-agent deployments. It pairs with
the reference templates in `deploy/` and exists so operators can reproduce the
operator-shape readiness gate (Rule 8) outside the developer machine.

Audience: SRE / platform operators running hi-agent under PM2, systemd, or
Docker / docker-compose. For developer-side configuration see
[`docs/deployment-env-matrix.md`](deployment-env-matrix.md) and
[`docs/posture-reference.md`](posture-reference.md).

---

## Contents

1. [Starting the server under each runtime](#1-starting-the-server-under-each-runtime)
2. [Where logs go](#2-where-logs-go)
3. [Graceful drain via `/ops/drain`](#3-graceful-drain-via-opsdrain)
4. [Heap-dump procedure](#4-heap-dump-procedure)
5. [Rotating Volces / API keys](#5-rotating-volces--api-keys)
6. [Restart drill](#6-restart-drill)
7. [Verifying tenant isolation](#7-verifying-tenant-isolation)
8. [Reading the readiness manifest](#8-reading-the-readiness-manifest)

---

## 1. Starting the server under each runtime

All three runtimes drive the same entry point: `python -m hi_agent serve --port 8080`.
Pick the runtime your environment standardizes on; do not mix.

### PM2

```bash
# First time
pm2 start deploy/pm2/ecosystem.config.js
pm2 save                              # remember the process list across reboots
pm2 startup                           # generate the boot script (run as root)

# Day-to-day
pm2 status hi-agent
pm2 reload hi-agent                   # zero-downtime reload (if applicable)
pm2 stop hi-agent                     # graceful stop (PM2 sends SIGINT then SIGKILL)
```

The PM2 file pins `instances: 1` and `exec_mode: fork`. Do **not** switch to
cluster mode — hi-agent owns SQLite handles and an in-memory `RunManager`;
multiple workers would corrupt state.

### systemd

```bash
sudo install -m 0644 deploy/systemd/hi-agent.service /etc/systemd/system/
sudo install -d -o hi-agent -g hi-agent /var/lib/hi-agent /var/log/hi-agent
sudo install -m 0640 -o root -g hi-agent /path/to/your/env /etc/hi-agent/env

sudo systemctl daemon-reload
sudo systemctl enable --now hi-agent
sudo systemctl status hi-agent
```

The unit installs as user `hi-agent`. Create that user (`useradd --system
--shell /usr/sbin/nologin hi-agent`) before the first start, or override
`User=` in a drop-in.

### Docker / docker-compose

```bash
docker build -f deploy/docker/Dockerfile -t hi-agent:local .

# Single container
docker run -d --name hi-agent -p 8080:8080 \
  -e HI_AGENT_POSTURE=research \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v hi-agent-data:/var/lib/hi-agent \
  hi-agent:local

# Compose
docker compose -f deploy/docker/docker-compose.yml up -d
docker compose -f deploy/docker/docker-compose.yml ps
```

Verify the server is up before any other operation:

```bash
curl -fsS http://127.0.0.1:8080/health | jq
# expect: {"status":"ok", ...}
```

---

## 2. Where logs go

| Runtime | stdout / stderr | Live tail |
|---------|-----------------|-----------|
| PM2 | `./logs/hi-agent.out.log`, `./logs/hi-agent.err.log` (relative to PM2 cwd) | `pm2 logs hi-agent --lines 200` |
| systemd | `journald` (also visible via `StandardOutput=journal`) | `journalctl -u hi-agent -f` |
| Docker | container stdout/stderr (Docker logging driver) | `docker logs -f hi-agent` |
| docker-compose | per-service stream | `docker compose -f deploy/docker/docker-compose.yml logs -f hi-agent` |

Application-level structured logs (Rule 7 fallback alarms, run lifecycle,
gate events) go to the same stdout/stderr stream. Filter by event names —
e.g. `journalctl -u hi-agent | grep llm_fallback_total`.

Persistent state (SQLite databases, run artifacts, ledger) lives under
`HI_AGENT_HOME` (default `/var/lib/hi-agent` for systemd / Docker, repo
root for PM2). Back this up — losing it loses the audit trail.

---

## 3. Graceful drain via `/ops/drain`

`POST /ops/drain` flips the server into draining state, waits for in-flight
runs to terminate, and rejects new mutating requests with `503`. `/health`
flips to `503 draining` so load balancers stop routing traffic.

```bash
# Initiate drain — body is optional; default timeout is 120s.
curl -X POST http://127.0.0.1:8080/ops/drain \
     -H 'Content-Type: application/json' \
     -d '{"timeout_s": 120}'

# Response:
#   {"status":"drained","draining":true,"in_flight":0,...}    # success
#   {"status":"forced", "draining":true,"in_flight":N, ...}   # timeout — check N
```

Operational sequence for a routine restart:

1. `curl -X POST .../ops/drain -d '{"timeout_s":120}'`
2. Wait for HTTP 200 with `"status":"drained"`. If `"forced"` is returned
   instead, capture `/ops/runs` output (still up; it's a read endpoint) for
   the run IDs that did not terminate, then proceed.
3. Stop the process: `pm2 stop hi-agent` / `systemctl stop hi-agent` /
   `docker compose stop hi-agent`. SIGTERM is honoured — the server will
   re-run drain at the kernel level as a belt-and-braces measure.
4. Start the process again. `/health` returns `200` once ready.

Do **not** kill -9 the process unless drain has already been attempted and
failed. SIGKILL skips the SQLite WAL checkpoint; the next start may need to
roll forward the WAL, which is slow and surfaces as elevated `/health` start
time.

---

## 4. Heap-dump procedure

hi-agent runs on CPython, so heap dumps use either `tracemalloc` (built-in,
low-overhead snapshot) or a third-party tool such as `py-spy` or `memray`
(richer detail, requires installation).

### tracemalloc (always available)

The server can be started with tracing enabled by setting
`PYTHONTRACEMALLOC=25` in the unit / compose env. To capture a snapshot
on demand from a running process, attach via Python's interactive
debugger or — preferred — use a one-shot helper script:

```bash
# As root, attach to the process and dump the top-25 allocators.
sudo PYTHONTRACEMALLOC=25 python3 -X dev <<'PY'
import os, signal
# Ask the process to log a tracemalloc snapshot via SIGUSR1; the
# server installs a SIGUSR1 handler when PYTHONTRACEMALLOC is set.
pid = int(open('/run/hi-agent.pid').read().strip())
os.kill(pid, signal.SIGUSR1)
PY
```

If the SIGUSR1 hook is not wired in your build, fall back to py-spy.

### py-spy (best for live process)

```bash
sudo pip install py-spy
sudo py-spy dump --pid $(pgrep -f 'hi_agent serve')              # stack trace
sudo py-spy record --pid $(pgrep -f 'hi_agent serve') -o flame.svg --duration 30
```

### memray (best for full heap)

```bash
# Requires running the server under memray from the start:
memray run -o /var/log/hi-agent/heap.bin -m hi_agent serve --port 8080
# After capture:
memray flamegraph /var/log/hi-agent/heap.bin
```

Store dumps under `/var/log/hi-agent/` (writable per the systemd unit) and
attach them to the incident ticket. Sanitise before sharing — process memory
may contain API keys.

---

## 5. Rotating Volces / API keys

Volces (a.k.a. ARK) keys live in `ARK_API_KEY` for the runtime; the
OpenAI-compatible MaaS gateway reads `OPENAI_API_KEY` (the same variable, by
design — `HI_AGENT_OPENAI_API_KEY_ENV` configures which env var the gateway
reads from). Anthropic uses `ANTHROPIC_API_KEY`.

> Per project policy ([memory note](../memory/MEMORY.md)),
> the live Volces key is **never** committed to the repo. Treat every commit
> that adds an API key string as an incident.

### Rotation steps (zero-downtime)

1. **Mint** a new key in the provider console. Note the expiry.
2. **Stage** the new key alongside the old one in your secret store
   (Vault / SOPS / cloud KMS). Do not deploy yet.
3. **Drain + reload** in turn:
   - PM2: update the env (`pm2 restart hi-agent --update-env`) after the
     env file is rewritten by your config-management tool.
   - systemd: rewrite `/etc/hi-agent/env`, then
     `curl -X POST .../ops/drain && systemctl restart hi-agent`.
   - Docker / compose: rewrite the `.env` next to the compose file, then
     `docker compose up -d --force-recreate hi-agent` after a drain.
4. **Verify** the new key is live:
   ```bash
   curl -fsS http://127.0.0.1:8080/diagnostics | jq '.credentials_present'
   # expect: {"OPENAI_API_KEY": true, "ARK_API_KEY": true, ...}
   ```
   Then run a real-LLM smoke (`POST /runs` with a trivial task) and confirm
   `llm_fallback_count == 0` in the run's `meta.fallback_events`.
5. **Revoke** the old key in the provider console after at least one
   successful real-LLM run.

If a key was leaked: revoke immediately, rotate per above, and grep the repo
+ logs for the leaked prefix to confirm no other artifact contains it.

---

## 6. Restart drill

Run quarterly. The drill exercises Rule 5 (cross-loop resource stability)
and Rule 8 step 3 (sequential real-LLM runs) end-to-end.

```bash
# 0. Pre-flight
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready

# 1. Run three back-to-back real-LLM jobs.
for i in 1 2 3; do
  curl -fsS -X POST http://127.0.0.1:8080/runs \
       -H 'Content-Type: application/json' \
       -d "{\"task\":\"echo restart-drill-${i}\",\"profile_id\":\"default\"}" \
       | tee /tmp/run-${i}.json
done

# 2. Drain + restart.
curl -X POST http://127.0.0.1:8080/ops/drain -d '{"timeout_s":60}'
sudo systemctl restart hi-agent     # or pm2 restart / docker compose up -d --force-recreate

# 3. Repeat the three jobs.
for i in 4 5 6; do
  curl -fsS -X POST http://127.0.0.1:8080/runs ...   # same as above
done

# 4. Inspect each run.
for id in $(jq -r .run_id /tmp/run-*.json); do
  curl -fsS http://127.0.0.1:8080/runs/$id | \
    jq '{state, finished_at, llm_fallback_count: (.meta.fallback_events|length)}'
done
```

Pass criteria (Rule 8):

- Every run reaches `state == "done"` within `2 * observed_p95`.
- `llm_fallback_count == 0` for every run.
- Runs 4-6 (post-restart) reuse the same gateway/adapter instance pattern
  with no `Event loop is closed` or `ConnectTimeout` in logs.
- `/runs/{id}/cancel` on a live run returns 200; on an unknown id returns 404.

Record the drill run as `docs/delivery/<date>-<sha>-restart-drill.md`.
Unrecorded drills do not count.

---

## 7. Verifying tenant isolation

hi-agent is multi-tenant by contract (Rule 12). Every persistent record
carries a `tenant_id`; cross-tenant reads return `404`, never `403`.

Smoke check (research / prod posture):

```bash
# Tenant A creates a run.
curl -fsS -X POST http://127.0.0.1:8080/runs \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant-a' \
  -d '{"task":"isolation-check","profile_id":"default"}' \
  | jq -r .run_id > /tmp/run-a.txt

# Tenant A reads its own run — should succeed.
curl -fsS -H 'X-Tenant-Id: tenant-a' \
     http://127.0.0.1:8080/runs/$(cat /tmp/run-a.txt) | jq .state

# Tenant B reads tenant-a's run id — MUST return 404.
http_code=$(curl -s -o /dev/null -w '%{http_code}' \
  -H 'X-Tenant-Id: tenant-b' \
  http://127.0.0.1:8080/runs/$(cat /tmp/run-a.txt))
test "$http_code" = "404" || echo "FAIL: cross-tenant returned $http_code"
```

Repeat for every read endpoint your downstream consumer uses
(`/runs/{id}/events`, `/runs/{id}/artifacts`, `/artifacts/{id}`,
`/feedback`). A 200 from any cross-tenant call is a P0 incident — drain,
investigate, and file under HD-4 lineage.

If `HI_AGENT_POSTURE=dev`, missing `X-Tenant-Id` is permitted and falls back
to a default tenant. Under `research` / `prod`, missing tenant returns
`400`. This is a posture invariant — see [`docs/posture-reference.md`](posture-reference.md).

---

## 8. Reading the readiness manifest

`GET /manifest` returns the live capability and configuration manifest;
`GET /ready` returns the platform readiness contract. The release manifest
under `docs/releases/` is generated from these endpoints plus repo state by
`scripts/build_release_manifest.py` (Rule 14).

### Live runtime

```bash
# Full manifest (capability list, posture, runtime mode, config provenance).
curl -fsS http://127.0.0.1:8080/manifest | jq

# Readiness contract — 200 = ready, 503 = not ready (with reason).
curl -is http://127.0.0.1:8080/ready

# Diagnostics — env-var resolution, credential presence, kernel binding.
curl -fsS http://127.0.0.1:8080/diagnostics | jq
```

Look for these fields when validating a deployment:

| Field | Expected (research/prod) |
|-------|--------------------------|
| `runtime_mode` | `prod-real` (prod) or `research-real` (research) |
| `kernel_base_url` | configured HTTP URL or `local` (in-process kernel) |
| `llm_mode` | `real` |
| `llm_fallback_count` (per run) | `0` |
| `posture` | matches `HI_AGENT_POSTURE` env |
| `credentials_present.OPENAI_API_KEY` | `true` if using OpenAI / MaaS path |

### Release manifest (governance)

After a wave is closed, the release manifest is the authoritative source of
release facts (Rule 14). It lives under `docs/releases/` and has these
top-level fields you should treat as ground truth:

- `release_head` — the git SHA the manifest was generated against. **Must**
  equal `git rev-parse HEAD` for the manifest to be valid.
- `git.is_dirty` — `false` for a valid release. `true` invalidates the
  readiness claim and caps `current_verified_readiness` at 70.
- `current_verified_readiness` — the only number that should be cited as
  the release's readiness score. Headlines must use this, not
  `raw_implementation_maturity` or `conditional_readiness_after_blockers`.
- `wave` — the wave number the manifest closes.
- `cap_factors` — list of active score caps; if non-empty, expect the cap
  reason in the closure notice.

Quick check after a deploy:

```bash
ls -t docs/releases/ | head -5
jq '{wave, release_head, current_verified_readiness, cap_factors}' \
   docs/releases/$(ls -t docs/releases/ | head -1)
git rev-parse HEAD  # must equal .release_head
```

If the manifest's `release_head` differs from `git rev-parse HEAD`, the
deployment is on a SHA other than the one the readiness number was computed
against. Either redeploy at the manifest SHA or generate a fresh manifest
before claiming readiness.

---

## Appendix — quick reference

| Action | Endpoint / command |
|--------|--------------------|
| Health check | `GET /health` |
| Readiness check | `GET /ready` |
| Diagnostics | `GET /diagnostics` |
| Manifest | `GET /manifest` |
| Drain | `POST /ops/drain` |
| Cancel run | `POST /runs/{id}/cancel` |
| Release gate snapshot | `GET /ops/release-gate` |
| DLQ inspection | `GET /ops/dlq` |
| Reload (PM2) | `pm2 reload hi-agent` |
| Restart (systemd) | `systemctl restart hi-agent` |
| Restart (compose) | `docker compose up -d --force-recreate hi-agent` |

For the full env-var inventory see
[`docs/deployment-env-matrix.md`](deployment-env-matrix.md).
