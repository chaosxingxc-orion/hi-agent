# agent_server

> **Last refreshed:** 2026-05-06 (W35 corrective close + W36 plans staged). HEAD `276917d8`.
> **Status:** v1 RELEASED. Frozen at SHA `55e51a7f` (`agent_server/config/version.py::V1_FROZEN_HEAD`).

`agent_server/` is the **versioned northbound HTTP facade** of the hi-agent platform. It is the only contract surface that the Research Intelligence App (RIA) and third-party SDKs depend on. Direct imports of `hi_agent.*` from downstream code are unsupported and CI-rejected.

This is a thin, posture-aware FastAPI app. It owns transport, validation, idempotency, JWT authentication, and tenant-scoping; it does **not** own agent execution, memory, cognition, or durable run persistence — those live in `hi_agent/`.

---

## Who calls this

| Caller | Surface | Auth |
|---|---|---|
| Research Intelligence App (RIA) | HTTP `/v1/*` | Bearer JWT (research/prod) |
| Third-party SDKs | HTTP `/v1/*` | Bearer JWT |
| Operator (release captain, on-call) | `agent-server` CLI | local process |

The HTTP surface is the contract. The CLI is operator-facing convenience that shells through `bootstrap.py::build_production_app` to the same FastAPI app.

---

## Quickstart

### Install (with the umbrella package)

```bash
pip install -e ".[llm]"
```

### Mount as a FastAPI app

```python
# uvicorn snippet — production assembly seam
from agent_server.bootstrap import build_production_app

app = build_production_app()  # reads HI_AGENT_POSTURE, AGENT_SERVER_STATE_DIR
```

```bash
uvicorn module:app --host 0.0.0.0 --port 8080
```

For local development, the canonical entry point is the CLI:

```bash
agent-server serve --host 0.0.0.0 --port 8080
```

### Production posture

```bash
export HI_AGENT_POSTURE=research          # or prod
export HI_AGENT_LLM_MODE=real
export HI_AGENT_JWT_SECRET=<32-byte-hmac-key>
export OPENAI_API_KEY=<provider-key>     # or VOLCES_API_KEY / ANTHROPIC_API_KEY
agent-server serve --prod
```

### Submit a run

```bash
curl -s -X POST http://localhost:8080/v1/runs \
  -H "Authorization: Bearer $JWT" \
  -H "X-Tenant-Id: tenant-a" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-a","profile_id":"default","goal":"summarise quarterly results","project_id":"proj-1"}'
```

Three headers are required under research/prod, every mutating route, every request:

- `Authorization: Bearer <jwt>` — HMAC-validated by `JWTAuthMiddleware` (W33-C.4)
- `X-Tenant-Id` — every posture, every request
- `Idempotency-Key` — every mutating route under research/prod

Optional context: `X-Project-Id`, `X-Profile-Id`, `X-Session-Id`.

---

## Document map

| Layer | Document |
|---|---|
| Package architecture | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| HTTP transport (routes + middleware) | [`api/ARCHITECTURE.md`](api/ARCHITECTURE.md) |
| Contract↔kernel adapters | [`facade/ARCHITECTURE.md`](facade/ARCHITECTURE.md) |
| Frozen v1 schemas | [`contracts/ARCHITECTURE.md`](contracts/ARCHITECTURE.md) |
| Real-kernel binding | [`runtime/ARCHITECTURE.md`](runtime/ARCHITECTURE.md) |
| Operator CLI | [`cli/ARCHITECTURE.md`](cli/ARCHITECTURE.md) |
| Settings + version | [`config/ARCHITECTURE.md`](config/ARCHITECTURE.md) |
| Public surface specification | [`../docs/platform/agent-server-northbound-contract-v1.md`](../docs/platform/agent-server-northbound-contract-v1.md) |

---

## Stability promise

The v1 contract is **frozen**. `agent_server/contracts/` is digest-snapshotted in `docs/governance/contract_v1_freeze.json`; CI gate `scripts/check_contract_freeze.py` blocks any field change. The digest was re-rolled at W35-T1 once `__post_init__` validators were attached to 53 dataclasses (additive, no field shape change).

A breaking change MUST land in a parallel `agent_server/contracts/v2/` sub-package; the v1 module is not modified in place.

The frozen surface includes:

- HTTP path + method + body shape for every `/v1/*` route
- Request/response dataclass field names + types
- Error envelope shape (`ContractError` + categories)
- `AGENT_SERVER_API_VERSION = "v1"`

---

## Quality bar (R-AS-1 through R-AS-8)

`agent_server/` is governed by eight package-scoped rules in addition to the seventeen platform-wide rules in [`../CLAUDE.md`](../CLAUDE.md):

| Rule | Subject | Gate |
|---|---|---|
| **R-AS-1** | Single-seam discipline. Only `bootstrap.py` and `runtime/**` may import `hi_agent.*`. | `scripts/check_layering.py`, `scripts/check_facade_seams.py` |
| **R-AS-2** | No reverse imports. `hi_agent/` MUST NOT import `agent_server.*`. | `scripts/check_no_reverse_imports.py` |
| **R-AS-3** | v1 contract freeze. `contracts/` digest-snapshotted; no in-place breaking changes. | `scripts/check_contract_freeze.py` |
| **R-AS-4** | Route scope discipline. Every route declares its tenant-scope category. | `scripts/check_route_scope.py`, `scripts/check_route_tenant_context.py` |
| **R-AS-5** | TDD evidence. Every route handler carries `# tdd-red-sha: <sha>` referencing the failing-test commit. | `scripts/check_tdd_evidence.py` |
| **R-AS-6** | Facade purity. No business logic; constructor-injected callables only. | code review |
| **R-AS-7** | Posture-aware defaults. Every config knob declares dev/research/prod behaviour. | `scripts/check_rules.py` (Rule 11) |
| **R-AS-8** | Facade module ≤200 LOC. Forces composition over fat adapters. | `scripts/check_facade_loc.py` |

PR descriptions touching `agent_server/api/**`, `agent_server/facade/**`, `agent_server/cli/**`, `agent_server/mcp/**`, `agent_server/tenancy/**`, or `agent_server/workspace/**` declare `Owner: AS-RO`. Contract changes declare `Owner: AS-CO`.

---

## Posture model summary

| Posture | Tenant header | Idempotency-Key | JWT | Backend | Spine validation (W35-T1) |
|---|---|---|---|---|---|
| `dev` | required | optional, warn if absent | passthrough; anonymous claims | `real` (default) or `stub` permitted | warns on missing field |
| `research` | required | required on mutating routes | required HMAC | `real` only | raises `SpineCompletenessError` (400) |
| `prod` | required | required on mutating routes | required HMAC | `real` only | raises |

Set via `HI_AGENT_POSTURE={dev,research,prod}` (default `dev`). See [`ARCHITECTURE.md`](ARCHITECTURE.md) §6 for the full matrix.

---

## Where state lives

`agent_server/` itself owns minimal state. All durable persistence flows to `hi_agent/server/` SQLite stores under `state_dir`:

```
<state_dir>/
├── runs.db          # SQLiteRunStore
├── events.db        # SQLiteEventStore
├── queue.db         # RunQueue
├── idempotency.db   # IdempotencyStore (W35-T4 background TTL purge)
├── gates.db         # GateStore
├── team_events.db   # TeamEventStore
└── workspace/       # tenant-scoped artifacts
```

`state_dir` resolution (`bootstrap.py::_default_state_dir`):

1. `AGENT_SERVER_STATE_DIR` (explicit override)
2. `$HI_AGENT_HOME/.agent_server`
3. `./.agent_server` (CWD-relative fallback)

---

## Operator commands

```
agent-server serve                  # uvicorn against build_production_app
agent-server run <tenant> <json>    # POST /v1/runs and wait
agent-server cancel <id>            # POST /v1/runs/{id}/cancel
agent-server tail-events <id>       # consume SSE stream from /v1/runs/{id}/events
```

The `tail-events` stream is a true live SSE stream (W33-C.5); it stays open and yields events until the run reaches a terminal state.

---

## Endpoints at a glance

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/runs` | Start a new run |
| GET | `/v1/runs/{id}` | Read run state |
| POST | `/v1/runs/{id}/cancel` | Drive run to terminal (200 live, 404 unknown) |
| GET | `/v1/runs/{id}/events` | SSE live event stream |
| GET | `/v1/artifacts` | List tenant artifacts |
| GET | `/v1/artifacts/{id}` | Read artifact metadata |
| POST | `/v1/gates/{id}/decision` | Decide a human gate |
| POST | `/v1/skills` | Register a skill (when enabled) |
| POST | `/v1/memory` | Write a memory record (when enabled) |
| POST | `/v1/mcp/tools` | Register an MCP tool (when enabled) |
| GET | `/v1/manifest` | Capability + posture matrix |
| GET | `/v1/health` | Per-subsystem status + api_version |
| GET | `/health`, `/ready`, `/diagnostics`, `/metrics` | Operator observability |

Detailed contract: [`docs/platform/agent-server-northbound-contract-v1.md`](../docs/platform/agent-server-northbound-contract-v1.md).

---

## Contributing

Read [`../CLAUDE.md`](../CLAUDE.md) first — it defines the seventeen platform engineering rules. Then [`ARCHITECTURE.md`](ARCHITECTURE.md) for the package's component model.

A typical contribution path:

1. Open a wave plan under `docs/superpowers/plans/`.
2. Write the failing test first; commit with `[<wave>] RED: <description>`. Capture its SHA.
3. Implement the code in `agent_server/` (or `hi_agent/` if it's kernel work). Annotate any new route handler with `# tdd-red-sha: <sha>`.
4. Update `agent_server/contracts/` if and only if the change is additive (R-AS-3). Re-run `scripts/check_contract_freeze.py`.
5. Run `python scripts/verify_clean_env.py --profile default-offline`.
6. PR description includes `Owner: AS-RO|AS-CO`, `Profile validated: default-offline|release`, and the four-line root-cause block (Rule 1).

Hot-path changes (`agent_server/api/**`, `agent_server/facade/**`, `agent_server/cli/**`) require T3 evidence at the proposed merge HEAD per Rule 8 T3 invariance.

---

## License

Proprietary. Internal platform use only.
