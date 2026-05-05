# Architecture: hi-agent Platform (arc42)

> **Last refreshed:** Wave 33 (2026-05-04). Manifest `2026-05-03-ce9330fa`.
>
> **Document hierarchy**
> - L0 system boundary: this file
> - L1 agent-server detail: [`agent_server/ARCHITECTURE.md`](agent_server/ARCHITECTURE.md)
>   - L2 transport (`api/`): [`agent_server/api/ARCHITECTURE.md`](agent_server/api/ARCHITECTURE.md)
>   - L2 adapters (`facade/`): [`agent_server/facade/ARCHITECTURE.md`](agent_server/facade/ARCHITECTURE.md)
>   - L2 contracts (`contracts/`): [`agent_server/contracts/ARCHITECTURE.md`](agent_server/contracts/ARCHITECTURE.md)
>   - L2 kernel binding (`runtime/`): [`agent_server/runtime/ARCHITECTURE.md`](agent_server/runtime/ARCHITECTURE.md)
>   - L2 operator CLI (`cli/`): [`agent_server/cli/ARCHITECTURE.md`](agent_server/cli/ARCHITECTURE.md)
>   - L2 config surfaces (`config/`): [`agent_server/config/ARCHITECTURE.md`](agent_server/config/ARCHITECTURE.md)
> - L1 hi-agent detail: [`hi_agent/ARCHITECTURE.md`](hi_agent/ARCHITECTURE.md)
>   - L2 server kernel: [`hi_agent/server/ARCHITECTURE.md`](hi_agent/server/ARCHITECTURE.md)
>   - L2 runtime helpers: [`hi_agent/runtime/ARCHITECTURE.md`](hi_agent/runtime/ARCHITECTURE.md)
>   - L2 runtime_adapter: [`hi_agent/runtime_adapter/ARCHITECTURE.md`](hi_agent/runtime_adapter/ARCHITECTURE.md)
>   - L2 LLM gateway: [`hi_agent/llm/ARCHITECTURE.md`](hi_agent/llm/ARCHITECTURE.md)
>   - L2 observability: [`hi_agent/observability/ARCHITECTURE.md`](hi_agent/observability/ARCHITECTURE.md)
>   - L2 knowledge: [`hi_agent/knowledge/ARCHITECTURE.md`](hi_agent/knowledge/ARCHITECTURE.md)
>   - L2 skill: [`hi_agent/skill/ARCHITECTURE.md`](hi_agent/skill/ARCHITECTURE.md)
>   - L2 capability: [`hi_agent/capability/ARCHITECTURE.md`](hi_agent/capability/ARCHITECTURE.md)
> - Stable codebase facts: [`docs/architecture-reference.md`](docs/architecture-reference.md)

---

## 1. Introduction and Goals

hi-agent is a **platform-layer** agent execution system. It is not a business application.
Its purpose is to provide the research team's intelligence applications with a stable,
versioned, operationally observable API surface for running long-lived autonomous agents.

**Primary goals:**

1. Expose a frozen northbound HTTP contract (`agent_server/`, v1) that downstream teams can
   depend on across platform upgrades.
2. Execute TRACE (Task -> Route -> Act -> Capture -> Evolve) runs durably, with restart
   survival, cancellation, and per-run observability.
3. Enforce a hard platform/business boundary so research-team business logic never leaks
   into the platform kernel.
4. Provide posture-aware defaults (`dev` permissive, `research`/`prod` fail-closed) so the
   same codebase runs safely across local development, research, and production deployments.

**Quality requirements (binding):** See Section 10.

---

## 2. Constraints

| Constraint | Source |
|---|---|
| Python 3.12+ | `pyproject.toml` |
| FastAPI/Starlette for HTTP | `pyproject.toml` dependencies |
| No business logic in `hi_agent/` (capability layer only) | CLAUDE.md G1 gate |
| `agent_server/` may import `hi_agent.*` only from two seams: `bootstrap.py` and `runtime/**` | R-AS-1 rule, `scripts/check_layering.py` |
| Annotated `# r-as-1-seam:` imports tolerated only in facade modules with documented rationale | `scripts/check_facade_seams.py` |
| v1 contract is digest-frozen at SHA `8c6e22f1`; breaking changes require `contracts/v2/` sub-package | CLAUDE.md AS-CO track, `scripts/check_contract_freeze.py` |
| Every new route handler requires `# tdd-red-sha: <sha>` annotation | CLAUDE.md R-AS-5 |
| Every facade module must stay ≤200 LOC | CLAUDE.md R-AS-8, `scripts/check_facade_loc.py` |
| `asyncio.run(` outside entry points is forbidden; sync callers use `sync_bridge` | CLAUDE.md Rule 5 |
| Inline fallbacks of the shape `x or DefaultX()` are forbidden | CLAUDE.md Rule 6 |
| Every persistent record carries `tenant_id` (Contract Spine Completeness) | CLAUDE.md Rule 12, `scripts/check_contract_spine_completeness.py` |
| SQLite for default persistence; PostgreSQL optional via `asyncpg` | `pyproject.toml` optional deps |

---

## 3. System Context

```mermaid
flowchart LR
    DS["Research Intelligence App<br/>(downstream team)"]
    SDK["Third-party SDK<br/>(JWT bearer)"]
    AS["agent_server<br/>northbound facade<br/>uvicorn :8080"]
    HA["hi_agent<br/>cognitive runtime<br/>+ inlined kernel<br/>(Wave 11)"]
    LLM["LLM Providers<br/>Anthropic / OpenAI-compatible<br/>Volces Ark"]
    DB[(SQLite stores<br/>runs / events / queue<br/>idempotency / gates / team)]
    MCP["MCP Tool Servers<br/>(plugin-registered)"]

    DS -->|"HTTP /v1/* + JWT (research/prod)"| AS
    SDK -->|"HTTP /v1/* + JWT"| AS
    AS -->|"R-AS-1 seam: bootstrap.py<br/>R-AS-1 seam: runtime/**"| HA
    HA -->|"chat completions<br/>(OpenAI-compatible)"| LLM
    HA -->|read/write| DB
    HA -->|stdio transport| MCP
```

**Downstream** uses only the `agent_server` HTTP API. Direct `import hi_agent` from RIA is
unsupported and CI-rejected. The `agent_kernel` package was inlined into `hi_agent/server/`
in Wave 11; references to `agent_kernel/*` in older docs map to `hi_agent/server/*` today.

---

## 4. Solution Strategy

| Decision | Rationale |
|---|---|
| Two-package structure (`hi_agent/` + `agent_server/`); kernel inlined into `hi_agent/server/` at W11 | Atomic versioning; eliminates submodule coordination overhead |
| Frozen v1 contract in `agent_server/contracts/` (snapshot at SHA `8c6e22f1`) | Downstream teams must not be broken by internal refactors |
| Two-seam R-AS-1 boundary (`bootstrap.py` + `runtime/**`) | Single point of `hi_agent.*` ingress per concern: assembly vs kernel binding |
| Posture enum (`dev`/`research`/`prod`) read from env | Enables the same binary to run permissively in dev and fail-closed in production without code changes |
| Async-first core; sync bridge for sync-facing callers | Avoids cross-loop async resource lifetime bugs (Rule 5) |
| JWT validation outermost in middleware chain (W33-C.4) | Reject unauthenticated traffic before tenant or idempotency layers see it |
| TierRouter with active calibration | Routes LLM calls to appropriate model tier based on quality signals; avoids expensive models for lightweight steps |
| Four-layer retrieval (grep -> BM25 -> graph -> embedding) | Cost-efficient retrieval without requiring embedding infrastructure for all queries |
| Rule 8 operator-shape gate before any delivery | Prevents "passes tests but fails in production" class of defects |

---

## 5. Building Block View

```mermaid
flowchart TB
    subgraph agent_server["agent_server — northbound facade"]
        MW["JWTAuthMiddleware (outermost)<br/>TenantContextMiddleware<br/>IdempotencyMiddleware"]
        RT["Route handlers<br/>/v1/runs /v1/artifacts<br/>/v1/gates /v1/skills<br/>/v1/memory /v1/mcp/tools<br/>/v1/manifest /v1/health"]
        FA["Facades (≤200 LOC each)<br/>RunFacade EventFacade<br/>ArtifactFacade ManifestFacade<br/>IdempotencyFacade"]
        CO["Frozen contracts v1<br/>RunRequest RunResponse<br/>TenantContext ContractError<br/>+ skill/gate/memory/streaming"]
        CLI2["CLI (R-AS-1 stdlib only)<br/>serve run cancel tail-events"]
        BS["bootstrap.py (R-AS-1 seam #1)<br/>build_production_app"]
        RTM["runtime/ (R-AS-1 seam #2)<br/>RealKernelBackend<br/>build_real_kernel_lifespan<br/>auth_seam (W33)"]
    end

    subgraph hi_agent["hi_agent — cognitive runtime + inlined kernel"]
        RUN["runner.py / runner_stage.py<br/>RunExecutor<br/>TRACE S1–S5"]
        LLM2["llm/<br/>LLMGateway TierRouter<br/>ModelSelector FailoverChain<br/>BudgetTracker"]
        MEM["memory/<br/>L0 Raw L1 STM<br/>L2 Dream L3 LongTerm"]
        KNW["knowledge/<br/>Wiki KnowledgeGraph<br/>FourLayerRetrieval"]
        SKL["skill/<br/>SkillLoader<br/>SkillVersionManager<br/>SkillEvolver A/B"]
        EVO["evolve/<br/>PostmortemEngine<br/>ExperimentStore<br/>ChampionChallenger"]
        OBS["observability/<br/>RunEventEmitter<br/>12 typed events<br/>Prometheus metrics<br/>spine_events"]
        CFG["config/<br/>TraceConfig Posture<br/>SystemBuilder builders"]
        SRV["server/ (kernel-inlined W11)<br/>AgentServer RunManager<br/>SQLiteRunStore SQLiteEventStore<br/>IdempotencyStore RunQueue<br/>GateStore TeamRunRegistry"]
        AUTH["auth/ + server/auth_middleware<br/>JWT validation primitives"]
        RTA["runtime_adapter/<br/>RuntimeAdapter protocol<br/>KernelFacadeAdapter<br/>ResilientKernelAdapter"]
    end

    subgraph providers["LLM Providers"]
        ANT["Anthropic Claude"]
        OAI["OpenAI-compatible<br/>Volces Ark"]
    end

    MW --> RT
    RT --> FA
    FA --> RTM
    BS --> MW
    BS --> FA
    BS --> RTM
    RTM --> SRV
    SRV --> RUN
    RUN --> LLM2
    RUN --> MEM
    RUN --> KNW
    RUN --> SKL
    RUN --> EVO
    RUN --> OBS
    RTM -.-> AUTH
    SRV --> RTA
    LLM2 --> ANT
    LLM2 --> OAI
```

---

## 6. Runtime View

The following sequence shows the happy-path flow for `POST /v1/runs` under the Wave 33
middleware chain (JWT outermost → TenantContext → Idempotency → route).

```mermaid
sequenceDiagram
    participant C as Downstream Client
    participant JWT as JWTAuthMiddleware
    participant TC as TenantContextMiddleware
    participant IM as IdempotencyMiddleware
    participant RH as routes_runs.py
    participant RF as RunFacade
    participant RKB as RealKernelBackend
    participant RM as hi_agent RunManager
    participant RUN as runner.py (RunExecutor)
    participant LLM as llm/TierRouter+Gateway
    participant OBS as observability/RunEventEmitter

    C->>JWT: POST /v1/runs + Authorization: Bearer <jwt>
    Note over JWT: research/prod: validate signature + claims;<br/>dev: passthrough with anonymous claims
    JWT->>TC: forward (request.state.auth_claims)
    TC->>TC: validate X-Tenant-Id; emit tenant_context spine event
    TC->>IM: forward (request.state.tenant_context)
    IM->>IM: reserve_or_replay(tenant_id, key, body)
    IM->>RH: forward (new key) or short-circuit (replay/conflict)
    RH->>RF: run_facade.start(ctx, RunRequest)
    RF->>RKB: start_run(tenant_id, profile_id, goal, ...)
    RKB->>RM: create_run + start_run(executor)
    RM-->>RKB: ManagedRun(state=queued)
    RKB-->>RF: dict (kernel-shaped)
    RF-->>RH: RunResponse
    RH-->>IM: 201 + JSON
    IM->>IM: mark_complete(tenant_id, key, body, 201)
    IM-->>C: 201 Created {run_id, state=queued}

    Note over RM,RUN: Background TRACE execution

    RM->>RUN: execute(task_contract)
    RUN->>OBS: record_run_started + record_stage_started(S1)
    loop TRACE stages S1 -> S5
        RUN->>LLM: chat_completion(task_view)
        LLM-->>RUN: LLMResponse
        RUN->>OBS: record_action_executed / record_stage_completed
    end
    RUN->>OBS: record_run_completed(state=done)

    C->>RH: GET /v1/runs/{run_id}/events (SSE)
    RH->>RKB: iter_events(tenant_id, run_id)
    RKB-->>RH: live event stream
    RH-->>C: text/event-stream chunks until terminal
```

**Cancellation contract:** `POST /v1/runs/{id}/cancel` on a known live run returns 200 and
drives the run to a terminal state. On an unknown run ID it returns 404 (not 200).

**SSE live-stream contract (W33-C.5):** `GET /v1/runs/{id}/events` keeps the connection
open and yields events as they are appended to the event store; the stream closes once the
run reaches a terminal state. Snapshot-and-close behaviour was retired in W33.

---

## 7. Deployment View

```mermaid
flowchart LR
    subgraph host["Host (Linux / Windows)"]
        PM2["PM2 / systemd\nprocess supervisor"]
        subgraph proc["agent-server process"]
            ASRV["agent_server\nuvicorn :8000"]
            BRAIN["hi_agent runtime"]
            KERN["agent_kernel\n(in-process LocalFSM\nor HTTP client)"]
        end
        subgraph data["Data directories"]
            SQLDB[(SQLite\nrun_store / event_log)]
            CDIR["config/\nllm_config.json\nprofiles/ tools.json"]
        end
    end
    EXT["LLM Provider\n(external network)"]
    DS2["Downstream\nResearch App"]

    PM2 -->|"supervises"| proc
    DS2 -->|"HTTP :8000\n/v1/*"| ASRV
    ASRV --> BRAIN
    BRAIN --> KERN
    KERN --> SQLDB
    BRAIN --> CDIR
    BRAIN -->|"HTTPS"| EXT
```

**Standard startup:**

```bash
# 1. Install
pip install -e ".[llm]"

# 2. Configure
export HI_AGENT_POSTURE=research
export HI_AGENT_LLM_MODE=real
export OPENAI_API_KEY=<key>

# 3. Serve (foreground)
agent-server serve --host 0.0.0.0 --port 8000

# 4. Serve under PM2 (production)
pm2 start "agent-server serve" --name hi-agent
```

**Runtime modes:**

| `HI_AGENT_ENV` | `HI_AGENT_LLM_MODE` | Mode | kernel | LLM fallback |
|---|---|---|---|---|
| `dev` (default) | `heuristic` | dev-smoke | in-process LocalFSM | allowed |
| `dev` | `real` | local-real | LocalFSM or HTTP | allowed |
| `prod` | `real` | prod-real | HTTP client (requires `HI_AGENT_KERNEL_BASE_URL`) | **disabled**, 503 |

**Readiness endpoints:**

| Endpoint | Purpose |
|---|---|
| `GET /ready` | 200 when ready for traffic, 503 otherwise |
| `GET /health` | Per-subsystem status |
| `GET /diagnostics` | Compact fingerprint of resolved env/config (always 200) |
| `GET /metrics` | Prometheus metrics |

---

## 8. Cross-Cutting Concepts

### Logging

All log output uses Python `logging` with structured fields. Every fallback branch emits at
`WARNING` or higher with `run_id` and trigger reason (Rule 7). Silent `except: pass` blocks
are forbidden; every catch either re-raises, logs at `WARNING+`, or converts to a typed
failure.

### Error Handling

The northbound API uses typed `ContractError` exceptions that map to HTTP status codes.
Internal failures surface through `FailureCode` (11 codes, re-exported from
`agent_kernel.kernel`). Every silent-degradation path must be Countable (Prometheus counter),
Attributable (`WARNING+` log), Inspectable (`fallback_events` in run metadata), and
Gate-asserted (Rule 8 ship gate).

### Posture

`HI_AGENT_POSTURE={dev,research,prod}` (default `dev`) is read by `hi_agent/config/posture.py
::Posture.from_env()` at every enforcement call site. `dev` is permissive; `research` and
`prod` are fail-closed: `project_id` required on every run, persistence must be durable,
schema validation raises on error.

### Security

- Tenant isolation is enforced by `TenantContextMiddleware` in `agent_server`; route handlers
  read `request.state.tenant_context` and never the request body for identity.
- RBAC and JWT validation live in `hi_agent/auth/`.
- Workspace isolation uses a `(tenant_id, user_id, session_id)` three-dimensional key; path
  traversal is blocked in `hi_agent/server/workspace_path.py`.
- `shell=True` subprocess calls are forbidden (Rule 3 security boundary check).

### Async/Sync Boundary

The codebase is async-first. Sync-facing callers route through
`hi_agent.runtime.sync_bridge` (persistent loop on a dedicated thread, marshalled via
`asyncio.run_coroutine_threadsafe`). Direct `asyncio.run(` outside entry points (`__main__`,
CLI, test) is a rule violation enforced by `scripts/check_rules.py`.

### Idempotency

`agent_server` middleware deduplicates requests by `idempotency_key`. The underlying store is
`agent_server/facade/idempotency_facade.py` backed by `hi_agent/server/idempotency.py`.

---

## 9. Architecture Decisions

| Decision | Wave | Rationale |
|---|---|---|
| Inline `agent_kernel` into `hi_agent/server/` | W11 | Atomic versioning; eliminates git-submodule coordination overhead |
| Introduce `agent_server` as a separate northbound package | W11 | Hard platform/business boundary; frozen v1 contract independent of internal refactors |
| Freeze v1 contract with digest check at SHA `8c6e22f1` | W24 | Downstream must not be broken by platform upgrades; breaking changes require `v2/` sub-package |
| Three-posture system (`dev`/`research`/`prod`) | W9 | Single binary deployable safely in all environments; Rule 11 |
| TierRouter with active calibration signals | W27 | Dynamic routing adapts to quality feedback without manual tuning (P-6 closed) |
| `RunEventEmitter` with 12 typed event methods | W27 | Structured observability spine for runs; replaces ad-hoc log scraping |
| Reject Neo4j in favour of SQLite-backed KG | W10 | JSON-backed L3 covers all graph operations at current scale; Neo4j adds service dependency |
| Rule 8 operator-shape gate mandatory before delivery | W12 | Prevents green-pytest-but-broken-in-prod class of failures |
| Architectural 7×24 (5-assertion check) replaces wall-clock soak | W28 | Architectural property assertable in seconds; W33 re-confirmed 5/5 PASS |
| Promote `agent_server/runtime/` to second R-AS-1 seam (`RealKernelBackend`) | W32 | Real-kernel binding without bloating `bootstrap.py` |
| Add `JWTAuthMiddleware` outermost; reuse `hi_agent.auth` primitives via `runtime/auth_seam` | W33 | Unauthenticated traffic rejected before tenant/idempotency layers; R-AS-1 preserved |
| SSE `iter_events` becomes a true live stream | W33 | Streaming contract honoured end-to-end; snapshot-and-close retired |
| Unify `HI_AGENT_ENV` reads through `Posture.resolve_runtime_mode` | W33 | Rule 11 posture-aware defaults; CI gate `check_no_hi_agent_env_direct_read.py` |

---

## 10. Quality Requirements

| Quality attribute | Target | Enforcement |
|---|---|---|
| Test pass rate | 9,256+ offline tests, 0 failures (W33 manifest) | `default-offline` CI profile; `scripts/verify_clean_env.py` |
| Verified readiness | 75.0 (Wave 33; cap held by `soak_evidence_not_real` waiver) | Release manifest + `scripts/build_release_manifest.py` |
| 7x24 operational readiness | 90.0 (W33) — architectural property, 5/5 PASS at HEAD `ac37383` | `scripts/run_arch_7x24.py` (5 assertions, runs in seconds) |
| T3 invariance | Gate valid only at recorded SHA; hot-path commits invalidate until re-run | `scripts/check_manifest_freshness.py` |
| LLM fallback count | 0 for all T3 runs | Rule 8 step 3; `llm_fallback_count == 0` asserted |
| Cancellation round-trip | known-id: 200+terminal; unknown-id: 404 | Rule 8 step 6; `tests/integration/` |
| `current_stage` visibility | non-`None` within 30s on non-terminal run | Rule 8 step 5 |
| Lint | ruff exits 0; no `# noqa` without `expiry_wave` annotation | `scripts/check_rules.py`; CI |
| Contract spine | every persistent record carries `tenant_id` | `scripts/check_contract_spine_completeness.py` |
| Posture coverage | 100% (all validation sites posture-aware) | posture coverage gate; W27 Lane 5 |
| Auth boundary | research/prod rejects malformed/expired/missing JWT with 401 | `tests/integration/test_v1_jwt_auth_middleware.py` (W33-C.4) |
| Spine lineage | event/run records carry `parent_run_id` + `attempt_id` + `phase_id` | Rule 12; `tests/unit/test_spine_lineage_fields.py` (W33-F.1) |

---

## 11. Risks and Technical Debt

| Item | Risk | Status | Target |
|---|---|---|---|
| 7x24 wall-clock soak | Used to penalise 7x24 tier | RETIRED W28 | Replaced by architectural 5-assertion check `scripts/run_arch_7x24.py` |
| Observability spine `provenance:real` | Spine evidence is `structural`, not from real run | Subsumed by arch-7x24 assertion #4 (PASS) | Optional W29 enhancement: live-run spine evidence |
| Chaos runtime coupling | 2 of 10 scenarios skip on Windows (architecturally coupled, OS-limited) | Subsumed by arch-7x24 assertion #5 (PASS, provenance=runtime_partial) | Linux runner enables remaining 2 |
| Score ceiling at 94.55 | Bounded by capability matrix weights, not gate failures | Information only | W29+ with dimension lifts |
| `HI_AGENT_KERNEL_BASE_URL` required in prod | Missing env var causes silent LocalFSM fallback | Documented; `/doctor` warns | No change planned |

---

## 12. Glossary

| Term | Definition |
|---|---|
| TRACE | Task -> Route -> Act -> Capture -> Evolve; the five-phase run execution model |
| Run | A single durable execution entity, identified by `run_id`; survives process restart |
| Stage | A named phase within a run's TRACE lifecycle (S1 through S5) |
| StageDirective | A runtime instruction that modifies stage execution: `skip_to`, `insert_stage`, `replan` |
| Task | A formal contract (13 fields) capturing goal, constraints, and budget for a run |
| Task View | The minimal sufficient context rebuilt before each LLM call; avoids full context window usage |
| Branch | A logical trajectory within the exploration space; used in DAG execution mode |
| TierRouter | Routes LLM calls to `strong`/`medium`/`light` model tiers based on active calibration signals |
| FailoverChain | Ordered sequence of LLM providers; falls back on error, emits `hi_agent_llm_fallback_total` counter |
| Memory | Three-tier agent experience store: L0 Raw -> L1 STM -> L2 Dream -> L3 LongTerm graph |
| Knowledge | Stable facts: wiki + knowledge graph + four-layer retrieval (grep -> BM25 -> graph -> embedding) |
| Skill | A reusable process unit with a 5-stage lifecycle and A/B version management |
| Posture | Execution safety level: `dev` (permissive) / `research` (fail-closed) / `prod` (strictest) |
| TenantContext | Authenticated identity context injected by middleware; carries `tenant_id`, `user_id`, `project_id` |
| KernelFacade | The sole legal entry point into `agent_kernel`; enforces the platform contract |
| GatePendingError | Exception raised when a run reaches a human-gate checkpoint and must wait for a `/v1/gates/{id}/decide` call |
| RunEventEmitter | Structured observability component with 12 typed `record_*` methods for run lifecycle events |
| Operator-shape gate | Rule 8 requirement: the artifact must pass a full PM2/real-LLM/N>=3 run validation before delivery |
| Docs-only gap | Every commit between manifest HEAD and current HEAD modifies only `docs/**` (excluding governance configs) |
| T3 invariance | A gate pass is valid only at the SHA it was recorded; hot-path commits invalidate it |
