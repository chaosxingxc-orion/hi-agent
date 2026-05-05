# hi-agent

**Capability layer for autonomous agent execution.**
hi-agent is the platform that the Research Intelligence App (RIA) and other downstream applications build on top of. It packages a cognitive runtime, durable execution substrate, and a versioned northbound HTTP facade — and refuses to host business logic.

**TRACE** = Task → Route → Act → Capture → Evolve. The five-stage execution model is the kernel's contract for every run.

---

## Architecture Positioning

hi-agent is built around six properties that downstream consumers should be able to rely on:

- **Idempotent.** Every mutating northbound route accepts an `Idempotency-Key`. Same key + tenant + body returns byte-identical responses; same key + different body returns 409.
- **Stable.** The v1 contract surface is frozen. `agent_server/contracts/` is digest-snapshotted; breaking changes go to a parallel `v2/` sub-package, never in-place.
- **Extensible.** New capabilities register via plugin hooks (skill, MCP, capability registry); the v1 surface gains additive routes without touching v1 contract types.
- **Evolvable.** ExperimentStore + ChampionChallenger + recurrence-ledger drive A/B versioning and rollback. Skill evolution is closed-loop with operationally-observable alerts.
- **Configurable.** Posture-aware defaults (`dev` permissive / `research` and `prod` fail-closed) flow from `HI_AGENT_POSTURE` through every subsystem; `TraceConfig` + `ConfigStack` support hot-reload.
- **Sustainable.** Seventeen engineering rules in `CLAUDE.md` are CI-enforced. Every contract crossing a tenant boundary carries `tenant_id`. Every silent-degradation path has a metric, log, and gate-asserted alarm.

The platform enforces a hard boundary between platform-layer logic (this repo) and business-layer logic (research team). All downstream integration goes through `agent_server/` HTTP routes only; direct imports of `hi_agent.*` from downstream code are not supported.

---

## Quickstart

**Requirements:** Python 3.12+

### Install

```bash
git clone <repo-url> hi-agent
cd hi-agent
pip install -e ".[llm,dev]"
```

### Smoke

```bash
pytest -m "not live_api and not network and not requires_secret"
```

Or via the canonical wrapper that produces fresh evidence JSON:

```bash
python scripts/verify_clean_env.py --profile default-offline
```

Current baseline: 9,256 passed / 8 skipped / 0 failed (Wave 33, default-offline profile,
2026-05-04).

### Start the northbound API server

```bash
agent-server serve --host 0.0.0.0 --port 8080
```

To use a real LLM provider and fail-closed research posture:

```bash
export HI_AGENT_POSTURE=research
export HI_AGENT_LLM_MODE=real
export OPENAI_API_KEY=<your-key>
agent-server serve --prod
```

### Submit a run

Write the request body to a JSON file (`request.json`), then:

```bash
agent-server run --tenant tenant-a --request-json request.json
```

Or via HTTP. Under research/prod posture every mutating route requires both `X-Tenant-Id`
and `Idempotency-Key`, plus a Bearer JWT signed with `HI_AGENT_JWT_SECRET`:

```bash
curl -s -X POST http://localhost:8080/v1/runs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Tenant-Id: tenant-a" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"tenant_id": "tenant-a", "profile_id": "default", "goal": "summarise quarterly results", "project_id": "proj-1"}'
```

### Cancel a run and stream events

```bash
agent-server cancel --tenant tenant-a --run-id <run_id>
agent-server tail-events --tenant tenant-a --run-id <run_id>
```

The `tail-events` command consumes the live SSE stream from
`GET /v1/runs/{id}/events` (W33-C.5 made it a true live stream rather than a
snapshot-and-close).

---

## Architecture Overview

```mermaid
graph TB
    subgraph BIZLAYER["Business Layer (out of repo)"]
        RIA["Research Intelligence App<br/>(domain logic, prompts, business schemas)"]
        SDK["Third-party SDKs"]
    end

    subgraph CAPLAYER["Capability Layer (this repo)"]
        subgraph NB["Northbound facade — agent_server/"]
            NB_API["api/ — FastAPI routes + middleware<br/>(JWTAuth → TenantContext → Idempotency)"]
            NB_FAC["facade/ — Contract↔kernel adapters<br/>(≤200 LOC each)"]
            NB_CON["contracts/ — Frozen v1 schemas<br/>(SHA 8c6e22f1)"]
            NB_RT["runtime/ — Real-kernel binding<br/>(RealKernelBackend, lifespan,<br/>auth_seam)"]
            NB_CLI["cli/ — Operator commands<br/>(serve · run · cancel · tail-events)"]
            NB_CFG["config/ — settings, version"]
            NB_BS["bootstrap.py — Assembly seam #1<br/>build_production_app"]
        end
        subgraph HI["Cognitive runtime + inlined kernel — hi_agent/"]
            HI_LLM["llm/ — Gateway, tier router, budget,<br/>failover chain"]
            HI_RUN["server/ — AgentServer + RunManager +<br/>durable SQLite stores (runs, events,<br/>queue, idempotency, gates, team)"]
            HI_RT["runtime/, runtime_adapter/<br/>— Sync bridge, kernel adapters"]
            HI_MEM["memory/, knowledge/, skill/<br/>— Cognitive subsystems"]
            HI_OBS["observability/ — RunEventEmitter,<br/>spine events, audit log, metrics"]
            HI_AUTH["auth/ + server/auth_middleware<br/>— JWT validation primitives"]
        end
    end

    RIA -->|"HTTP /v1/* + Bearer JWT (research/prod)"| NB_API
    SDK -->|"HTTP /v1/* + Bearer JWT"| NB_API
    NB_CLI --> NB_BS
    NB_API --> NB_FAC
    NB_FAC --> NB_CON
    NB_BS --> NB_API
    NB_BS --> NB_FAC
    NB_BS --> NB_RT
    NB_BS -. "import hi_agent.*<br/>(R-AS-1 seam #1)" .-> HI
    NB_RT -. "import hi_agent.*<br/>(R-AS-1 seam #2)" .-> HI
    NB_RT -. "auth_seam reuses<br/>hi_agent JWT primitives" .-> HI_AUTH
    NB_FAC -. "injected callables" .-> NB_RT
```

Two repository packages cooperate:

| Package | Role |
|---|---|
| `agent_server/` | Versioned northbound HTTP facade (v1 contract frozen at SHA `8c6e22f1`); the **only contract surface** RIA depends on |
| `hi_agent/` | Cognitive runtime + inlined execution kernel: LLM gateway, runner, memory, knowledge, skills, config, observability, durable run stores |

> The historical `agent_kernel/` package was inlined into `hi_agent/server/` at Wave 11. References to `agent_kernel.*` in older docs map to `hi_agent.server.*` today.

R-AS-1 (two-seam discipline): only `agent_server/bootstrap.py` and `agent_server/runtime/**` may import `hi_agent.*`. CI gate `scripts/check_layering.py` enforces; annotated `# r-as-1-seam:` imports in two facade modules carry rationale and are policed by `scripts/check_facade_seams.py`.

Detailed architecture: [`docs/architecture-reference.md`](docs/architecture-reference.md). Per-subsystem docs in §[Reference Map](#reference-map).

---

## Project Status

| Wave | Headline | Status |
|---|---|---|
| W1–W11 | Foundation: cognitive runtime, TRACE S1–S5, agent_kernel inlined | closed |
| W12 | Default-path hardening; Rules 14–17 codified | closed |
| W13–W15 | Systemic class closures; 35-gate infrastructure | closed |
| W16 | Observability spine + chaos + operator drill | closed |
| W17–W18 | Manifest discipline + governance gap definitions | closed |
| W19 | Scope-aware caps + 6 class closures (verified=86.6) | closed |
| W20 | 10 defect classes (CL1–CL10); raw=88.7 | closed |
| W21–W22 | Continuous closure (verified rebound to 80.0) | closed |
| W23 | 8 parallel tracks + 3 cleanups (verified=94.55) | closed |
| W24 | Agent server MVP (5 routes + idempotency + CLI) | closed |
| W25 | PM2 drill + contract freeze + git-worktree dispatch | closed |
| W26 | Hidden-gap closure pass | closed |
| W27 | 17 lanes closed; PR#17; soak deferred | closed |
| W28 | Architectural 7×24 tier (`run_arch_7x24.py`); soak retired | closed |
| W29–W30 | Substantive closure passes | closed |
| W31 | RIA directive 13/14 IDs PASS; verified=55.0 (capped by `soak_evidence_not_real`); 79/91 hidden findings closed | closed |
| W32 | Real-kernel binding for v1 northbound; ARCHITECTURE refresh; hidden-gap closure; cleanup | closed |
| W33 | RIA acceptance follow-ups: JWT middleware (C.4); SSE live-stream (C.5); SIGTERM graceful drain (C.2); RunQueue tenant defense-in-depth (D.2); spine lineage (F.1); `HI_AGENT_ENV` unification (E.1); audit-log tenant_id (D.1) | closed |

Current verified readiness: **75.0** (Wave 33 manifest `2026-05-03-ce9330fa`; cap held by `soak_evidence_not_real` waiver per RIA acceptance §2). Architectural 7×24: 5/5 PASS at HEAD `ac37383`.

| Capability | Level | Notes |
|---|---|---|
| Run execution (TRACE S1–S5) | L3 | Long-lived process, real LLM, durable queue |
| TierRouter | L3 | Active calibration, signal-weight routing (P-6 closed W27) |
| ExtensionRegistry | L4 | Full lifecycle, rollback, third-party registration |
| PostmortemEngine | L2 | Wired into RunManager; `on_project_completed` hook |
| StageDirective wiring | L3 | `skip_to` + `insert_stage` + `replan` wired |
| Multi-agent team | L2 | `TeamRunSpec`; registry; not production-default |
| Knowledge graph | L2 | SQLite backend; four-layer retrieval (no v1 northbound route) |
| Evolution closed-loop | L2 | `ExperimentStore` rollback; recurrence-ledger observable |
| MCP tools | L2 | `StdioMCPTransport`; plugin-registered (v1 route is L1 stub) |
| Observability spine | L3 | `RunEventEmitter` (12 event types); real provenance enforced |
| agent_server v1 contract | L3 | Frozen at SHA `8c6e22f1`; production default |

Maturity levels: L0 demo · L1 tested component · L2 public contract · L3 production default · L4 ecosystem ready (Rule 13).

---

## Key Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `HI_AGENT_POSTURE` | `dev` | Execution posture: `dev` permissive, `research`/`prod` fail-closed (Rule 11) |
| `HI_AGENT_LLM_MODE` | `heuristic` | `real` routes to actual LLM provider |
| `HI_AGENT_ENV` | `dev` | `prod` enables fail-fast 503 on missing credentials. Read only via `Posture.resolve_runtime_mode()` (W33-E.1) |
| `AGENT_SERVER_BACKEND` | `real` | `real` binds `RealKernelBackend` from `agent_server/runtime/`; `stub` keeps `_InProcessRunBackend` for the default-offline test profile (forbidden under research/prod) |
| `AGENT_SERVER_STATE_DIR` | – | Persistent state directory (SQLite stores: runs, events, queue, idempotency, gates, team) |
| `HI_AGENT_HOME` | – | Fallback state-dir parent: `$HI_AGENT_HOME/.agent_server` |
| `AGENT_SERVER_HOST` / `AGENT_SERVER_PORT` | `0.0.0.0` / `8080` | Settings for `AgentServerSettings.load_settings()` |
| `HI_AGENT_JWT_SECRET` | – | HMAC secret for `JWTAuthMiddleware` (W33-C.4); required under research/prod |
| `HI_AGENT_KERNEL_BASE_URL` | – | Legacy detached-kernel RPC (deprecated; kernel inlined at W11) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `VOLCES_API_KEY` | – | LLM provider credentials |

Full environment matrix: [`docs/deployment-env-matrix.md`](docs/deployment-env-matrix.md).

---

## Reference Map

Per-subsystem architecture docs (each follows the standard 11-section SE template, all
diagrams in mermaid):

| Subsystem | Document |
|---|---|
| **L0 system** | [`ARCHITECTURE.md`](ARCHITECTURE.md) (arc42-style) |
| **L1 agent_server** | [`agent_server/ARCHITECTURE.md`](agent_server/ARCHITECTURE.md) |
| L2 HTTP routes + middleware | [`agent_server/api/ARCHITECTURE.md`](agent_server/api/ARCHITECTURE.md) |
| L2 Contract↔kernel adaptation | [`agent_server/facade/ARCHITECTURE.md`](agent_server/facade/ARCHITECTURE.md) |
| L2 Frozen v1 contracts | [`agent_server/contracts/ARCHITECTURE.md`](agent_server/contracts/ARCHITECTURE.md) |
| L2 Real-kernel binding | [`agent_server/runtime/ARCHITECTURE.md`](agent_server/runtime/ARCHITECTURE.md) |
| L2 Operator CLI | [`agent_server/cli/ARCHITECTURE.md`](agent_server/cli/ARCHITECTURE.md) |
| L2 Config + version constants | [`agent_server/config/ARCHITECTURE.md`](agent_server/config/ARCHITECTURE.md) |
| **L1 hi_agent codebase reference** | [`docs/architecture-reference.md`](docs/architecture-reference.md) — canonical module index, R-AS rules, gate map |

---

## Contributing

| Pointer | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Seventeen engineering rules + ownership tracks + narrow-trigger rules. CI-enforced. |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Wave-by-wave implementation plans (W12 onward); latest: `2026-05-04-wave-33-ria-acceptance-followups.md` |
| [`docs/governance/`](docs/governance/) | Closure taxonomy, evidence-provenance schema, allowlists, recurrence ledger |
| [`docs/platform/`](docs/platform/) | Public surface descriptions: `agent-server-northbound-contract-v1.md`, runtime profile guide |
| [`docs/downstream-responses/`](docs/downstream-responses/) | Wave delivery notices to downstream teams (latest: `2026-05-04-w33-delivery-notice.md`) |

Owner tracks govern review responsibilities (see `CLAUDE.md`):

| Track | Scope |
|---|---|
| CO | Contracts, schemas, posture |
| RO | Execution, state machines, persistence |
| DX | CLI, config, developer tooling |
| TE | Artifacts, observability, evolution |
| GOV | CI, delivery governance, CLAUDE.md |
| AS-CO | `agent_server` contracts (v1 frozen) |
| AS-RO | `agent_server` routes, facades, CLI, runtime |

Every PR must declare its owner track in the commit body. Hot-path changes require T3 gate evidence at `docs/delivery/`. Pre-commit checklist (Rule 3) is mandatory.

---

## License

Proprietary — internal platform use only. Not for external distribution.
