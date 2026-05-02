# ARCHITECTURE: agent_server (L1 Detail)

> **Architecture hierarchy**
> - L0 system boundary: [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
> - L1 hi-agent detail: [`../hi_agent/ARCHITECTURE.md`](../hi_agent/ARCHITECTURE.md)
> - L1 agent-server detail: this file
> - L1 agent-kernel detail: [`../agent_kernel/ARCHITECTURE.md`](../agent_kernel/ARCHITECTURE.md)
>
> Last updated: 2026-05-02 (Wave 28)

This document describes the `agent_server` package — the versioned northbound API facade that downstream business-layer applications use to interact with the hi-agent platform.

---

## 1. Purpose and Positioning

`agent_server` provides a stable, versioned HTTP API surface over the `hi_agent` runtime. It enforces the platform/business-layer boundary so that downstream teams (e.g., research applications) never import `hi_agent` types directly.

| Concern | Owner |
|---------|-------|
| Business logic, prompts, domain schemas | Research team (outside this repo) |
| Northbound HTTP contract + versioning | `agent_server/` (this package) |
| Agent execution, memory, cognition | `hi_agent/` |
| Durable run lifecycle, event log, idempotency | `agent_kernel/` |

**Key invariant (R-AS-1):** Route handlers import only from `agent_server.contracts` and `agent_server.facade`. No `hi_agent.*` imports appear in `agent_server/api/`.

---

## 2. Package Structure

```
agent_server/
├── config/          — Configuration dataclasses (Settings, version.py)
├── contracts/       — Frozen northbound type schemas (v1)
├── facade/          — Adapters from contract types to hi_agent callables
├── api/             — FastAPI route handlers + middleware
│   └── middleware/  — Idempotency + tenant context injection
├── cli/             — CLI entry point (serve / run / cancel / tail-events)
├── mcp/             — MCP integration hooks (stub, Wave 28+)
├── tenancy/         — Multi-tenancy support utilities
├── workspace/       — Workspace isolation utilities
└── observability/   — Observability hooks
```

---

## 3. Layered Architecture

```mermaid
graph TB
  subgraph DOWNSTREAM["Downstream Clients"]
    HTTP["HTTP Client\n(Research App / SDK)"]
    CLI_CLIENT["CLI\nagent_server.cli"]
  end

  subgraph API["API Layer (agent_server/api/)"]
    MIDTC["TenantContextMiddleware\nmiddleware/tenant_context.py"]
    MIDEM["IdempotencyMiddleware\nmiddleware/idempotency.py"]
    R_RUNS["RunsRouter\nroutes_runs.py\nPOST/GET /v1/runs"]
    R_RUNSX["RunsExtendedRouter\nroutes_runs_extended.py\nPOST /cancel, GET /events"]
    R_ART["ArtifactsRouter\nroutes_artifacts.py\nGET/POST /v1/artifacts"]
    R_GATE["GatesRouter\nroutes_gates.py\nPOST /v1/gates/{id}/decide"]
    R_MANI["ManifestRouter\nroutes_manifest.py\nGET /v1/manifest"]
    R_SKM["SkillsMemoryRouter\nroutes_skills_memory.py\nPOST /v1/skills, /v1/memory/write"]
    R_MCP["MCPToolsRouter\nroutes_mcp_tools.py\nGET/POST /v1/mcp/tools"]
  end

  subgraph FACADE["Facade Layer (agent_server/facade/)"]
    F_RUN["RunFacade\nfacade/run_facade.py"]
    F_EVT["EventFacade\nfacade/event_facade.py"]
    F_ART["ArtifactFacade\nfacade/artifact_facade.py"]
    F_MANI["ManifestFacade\nfacade/manifest_facade.py"]
    F_IDEM["IdempotencyFacade\nfacade/idempotency_facade.py"]
  end

  subgraph CONTRACTS["Contract Layer (agent_server/contracts/)"]
    C_RUN["run.py\nRunRequest / RunResponse / RunStatus / RunStream"]
    C_SKILL["skill.py\nSkillSpec / SkillResult"]
    C_GATE["gate.py\nGateRequest / GateDecision"]
    C_MEM["memory.py\nMemoryWriteRequest"]
    C_LLM["llm_proxy.py\nLLMProxyRequest"]
    C_STREAM["streaming.py\nSSEEvent"]
    C_TEN["tenancy.py\nTenantContext"]
    C_WS["workspace.py\nWorkspaceContext"]
    C_ERR["errors.py\nContractError"]
  end

  subgraph HI_AGENT["hi_agent Runtime (hi_agent/)"]
    HA_SRV["hi_agent.server.app\nHTTP Server"]
    HA_RUN["hi_agent.server.run_manager\nRunManager"]
    HA_ART["hi_agent.artifacts.registry\nArtifactRegistry"]
  end

  HTTP --> MIDTC
  CLI_CLIENT --> MIDTC
  MIDTC --> MIDEM
  MIDEM --> R_RUNS
  MIDEM --> R_RUNSX
  MIDEM --> R_ART
  MIDEM --> R_GATE
  MIDEM --> R_MANI
  MIDEM --> R_SKM
  MIDEM --> R_MCP

  R_RUNS --> F_RUN
  R_RUNSX --> F_EVT
  R_ART --> F_ART
  R_MANI --> F_MANI

  F_RUN --> C_RUN
  F_EVT --> C_STREAM
  F_ART --> C_RUN
  F_IDEM --> C_TEN

  F_RUN --> HA_RUN
  F_EVT --> HA_RUN
  F_ART --> HA_ART
  F_MANI --> HA_SRV
```

---

## 4. Contract Layer (`agent_server/contracts/`)

The contract layer defines the v1 northbound API schemas. These types are frozen after v1 release; breaking changes require `agent_server/contracts/v2/`.

| Module | Key Types | Description |
|--------|-----------|-------------|
| `run.py` | `RunRequest`, `RunResponse`, `RunStatus`, `RunStream` | Run lifecycle: create, query, event stream |
| `skill.py` | `SkillSpec`, `SkillResult` | Skill registration and invocation |
| `gate.py` | `GateRequest`, `GateDecision` | Human-in-the-loop gate approval |
| `memory.py` | `MemoryWriteRequest` | Memory write operations |
| `llm_proxy.py` | `LLMProxyRequest`, `LLMProxyResponse` | Proxied LLM calls |
| `streaming.py` | `SSEEvent` | Server-Sent Events payload |
| `tenancy.py` | `TenantContext` | Authenticated tenant context (set by middleware) |
| `workspace.py` | `WorkspaceContext` | Workspace isolation context |
| `errors.py` | `ContractError` | Typed error with `http_status`, `tenant_id`, `detail` |

**Rule (R-AS-3):** After v1 release, contract files are digest-snapshotted by `scripts/check_contract_freeze.py`. Modifications invalidate the freeze and require release-captain sign-off.

---

## 5. Facade Layer (`agent_server/facade/`)

Facades translate contract types to `hi_agent` callables. Each facade receives callables via constructor injection, enabling incremental kernel binding and clean test stubs.

```mermaid
classDiagram
  class RunFacade {
    +start_run: StartRunFn
    +get_run: GetRunFn
    +signal_run: SignalRunFn
    +start(ctx, req) RunResponse
    +status(ctx, run_id) RunStatus
    +signal(ctx, run_id, signal) dict
  }

  class EventFacade {
    +get_events_fn: GetEventsFn
    +cancel_run_fn: CancelRunFn
    +cancel(ctx, run_id) dict
    +stream(ctx, run_id) AsyncIterator~SSEEvent~
  }

  class ArtifactFacade {
    +list_artifacts_fn: ListArtifactsFn
    +get_artifact_fn: GetArtifactFn
    +write_artifact_fn: WriteArtifactFn
    +list(ctx, run_id) list~dict~
    +get(ctx, artifact_id) dict
    +write(ctx, req) dict
  }

  class ManifestFacade {
    +get_manifest_fn: GetManifestFn
    +manifest(ctx) dict
  }

  class IdempotencyFacade {
    +check(ctx, key) Optional~dict~
    +record(ctx, key, response) None
  }
```

**LOC budget (R-AS-8):** Each facade module must stay ≤200 LOC.

---

## 6. API Route Inventory

All routes are prefixed with `/v1/` and registered via `build_router()` factory functions that accept facade instances as dependencies.

| Method | Path | Handler File | Description |
|--------|------|-------------|-------------|
| `POST` | `/v1/runs` | `routes_runs.py` | Submit a new run |
| `GET` | `/v1/runs/{run_id}` | `routes_runs.py` | Query run status |
| `POST` | `/v1/runs/{run_id}/signal` | `routes_runs.py` | Send control signal to a run |
| `POST` | `/v1/runs/{run_id}/cancel` | `routes_runs_extended.py` | Cancel a live run |
| `GET` | `/v1/runs/{run_id}/events` | `routes_runs_extended.py` | SSE event stream for a run |
| `GET` | `/v1/runs/{run_id}/artifacts` | `routes_artifacts.py` | List artifacts for a run |
| `GET` | `/v1/artifacts/{artifact_id}` | `routes_artifacts.py` | Get a specific artifact |
| `POST` | `/v1/artifacts` | `routes_artifacts.py` | Write an artifact |
| `POST` | `/v1/gates/{gate_id}/decide` | `routes_gates.py` | Post a gate decision |
| `GET` | `/v1/manifest` | `routes_manifest.py` | Get capability manifest |
| `POST` | `/v1/skills` | `routes_skills_memory.py` | Register a skill |
| `POST` | `/v1/memory/write` | `routes_skills_memory.py` | Write to agent memory |
| `GET` | `/v1/mcp/tools` | `routes_mcp_tools.py` | List available MCP tools |
| `POST` | `/v1/mcp/tools/{tool_name}` | `routes_mcp_tools.py` | Invoke an MCP tool |

**Rule (R-AS-5):** Every new route handler requires a `# tdd-red-sha: <sha>` annotation referencing the RED-test commit SHA.

---

## 7. Middleware Pipeline

Requests pass through two middleware layers before reaching route handlers:

```mermaid
sequenceDiagram
  participant Client
  participant TenantContextMiddleware
  participant IdempotencyMiddleware
  participant RouteHandler
  participant Facade
  participant hi_agent

  Client->>TenantContextMiddleware: HTTP Request
  TenantContextMiddleware->>TenantContextMiddleware: Resolve tenant_id from auth header
  TenantContextMiddleware->>TenantContextMiddleware: Build TenantContext → request.state
  TenantContextMiddleware->>IdempotencyMiddleware: Pass request
  IdempotencyMiddleware->>IdempotencyMiddleware: Check Idempotency-Key header
  IdempotencyMiddleware->>IdempotencyMiddleware: Look up cached response
  alt Cache hit
    IdempotencyMiddleware->>Client: Cached 200 response
  else Cache miss
    IdempotencyMiddleware->>RouteHandler: Pass request
    RouteHandler->>Facade: Call facade method
    Facade->>hi_agent: Call kernel callable
    hi_agent->>Facade: Return result dict
    Facade->>RouteHandler: Return contract type
    RouteHandler->>IdempotencyMiddleware: Response
    IdempotencyMiddleware->>IdempotencyMiddleware: Cache response by key+tenant
    IdempotencyMiddleware->>Client: 200 Response
  end
```

**Tenant isolation (R-AS-4):** Route handlers read `TenantContext` from `request.state` exclusively — never from the request body. The middleware is the single source of tenant identity.

---

## 8. Run Lifecycle Sequence

```mermaid
sequenceDiagram
  participant Client
  participant RunsRouter
  participant RunFacade
  participant hi_agent.RunManager
  participant agent_kernel.EventLog

  Client->>RunsRouter: POST /v1/runs {goal, profile_id, idempotency_key}
  RunsRouter->>RunsRouter: _ctx(request) → TenantContext
  RunsRouter->>RunFacade: start(ctx, RunRequest)
  RunFacade->>RunFacade: Validate idempotency_key + profile_id
  RunFacade->>hi_agent.RunManager: start_run(tenant_id, profile_id, goal, ...)
  hi_agent.RunManager->>agent_kernel.EventLog: Record RunCreated event
  hi_agent.RunManager->>hi_agent.RunManager: Enqueue to RunQueue
  hi_agent.RunManager-->>RunFacade: {run_id, state="queued", ...}
  RunFacade-->>RunsRouter: RunResponse
  RunsRouter-->>Client: 200 {run_id, state="queued"}

  Note over hi_agent.RunManager: Background execution begins

  Client->>RunsRouter: GET /v1/runs/{run_id}
  RunsRouter->>RunFacade: status(ctx, run_id)
  RunFacade->>hi_agent.RunManager: get_run(tenant_id, run_id)
  hi_agent.RunManager-->>RunFacade: {state="running", current_stage=...}
  RunFacade-->>RunsRouter: RunStatus
  RunsRouter-->>Client: 200 {state="running", ...}
```

---

## 9. Configuration and Version

| File | Purpose |
|------|---------|
| `config/settings.py` | `AgentServerSettings` — server host/port, CORS, auth mode |
| `config/version.py` | `V1_RELEASED` flag, `V1_FROZEN_HEAD` (contract freeze SHA) |

The `V1_RELEASED` flag gates `check_contract_freeze.py` from advisory to blocking mode. Once set to `True`, any modification to `agent_server/contracts/` invalidates the SHA digest snapshot.

---

## 10. CLI (`agent_server/cli/`)

```
agent-server serve    — Start the northbound HTTP API server
agent-server run      — Submit a run and wait for completion
agent-server cancel   — Cancel a running job by run_id
agent-server tail-events — Stream SSE events for a run to stdout
```

The CLI uses the same facades and contracts as the HTTP layer, providing identical tenant isolation and error semantics.

---

## 11. Multi-tenancy

Tenant isolation is enforced at every layer:

1. **Middleware** — `TenantContextMiddleware` resolves `tenant_id` from the auth header and injects `TenantContext` into `request.state`.
2. **Facade** — All facade methods accept `TenantContext` as first argument; `tenant_id` is passed to every `hi_agent` callable.
3. **Contract spine (Rule 12)** — Contract dataclasses carry `tenant_id` fields; cross-tenant access is structurally impossible via the facade interface.
4. **Idempotency** — `IdempotencyFacade` scopes keys by `tenant_id`; idempotency records from tenant A are invisible to tenant B.

---

## 12. Testing Standards

Per Rule 4, each route handler requires three test layers:

| Layer | Location | Description |
|-------|----------|-------------|
| Unit | `tests/unit/test_*_facade.py` | Facade logic with injected stub callables |
| Integration | `tests/integration/test_routes_*.py` | FastAPI `TestClient` with real facade wiring |
| E2E | `tests/e2e/test_e2e_agent_server_*.py` | Full HTTP stack against a running server |

Every new route handler commit must include a `# tdd-red-sha: <sha>` annotation in the handler source referencing the commit where the failing test was first written (R-AS-5).

---

## 13. Governance Gates

| Gate Script | What It Enforces |
|-------------|-----------------|
| `scripts/check_contract_freeze.py` | Digest-based freeze of all `agent_server/contracts/` files after v1 release (R-AS-3) |
| `scripts/check_tdd_evidence.py` | Every route handler has a `# tdd-red-sha:` annotation (R-AS-5) |
| `scripts/check_layering.py` | No `hi_agent.*` imports in `agent_server/api/` (R-AS-1) |
| `scripts/check_facade_loc.py` | Each facade module ≤200 LOC (R-AS-8) |

---

## 14. Deployment View

```mermaid
flowchart LR
  subgraph Client["Downstream Client Process"]
    SDK["Research App SDK / curl / agent-server CLI"]
  end
  subgraph Server["agent-server Process (uvicorn)"]
    PORT[":8000"]
    APP["FastAPI app instance"]
    MIDS["TenantContextMiddleware<br/>+ IdempotencyMiddleware"]
    ROUTES["7 Routers<br/>routes_runs / runs_extended / artifacts /<br/>gates / manifest / skills_memory / mcp_tools"]
  end
  subgraph Backend["hi_agent Runtime (in-process or HTTP)"]
    RUN["RunManager"]
    ART["ArtifactRegistry"]
    EVT["EventBus + RunEventEmitter"]
  end
  subgraph Persistence["Durable State"]
    SQL[("SQLite / PostgreSQL<br/>run_store · event_log<br/>idempotency · artifacts")]
  end

  SDK -->|"HTTP /v1/*<br/>+ Idempotency-Key<br/>+ Authorization"| PORT
  PORT --> APP
  APP --> MIDS
  MIDS --> ROUTES
  ROUTES --> RUN
  ROUTES --> ART
  ROUTES --> EVT
  RUN --> SQL
  ART --> SQL
  EVT --> SQL
```

**Standard startup:**

```bash
# Foreground
agent-server serve --host 0.0.0.0 --port 8000

# PM2 (recommended for production)
pm2 start "agent-server serve --host 0.0.0.0 --port 8000" --name hi-agent

# systemd (Linux production)
systemctl start hi-agent.service
```

**Posture-aware behaviour:**

| `HI_AGENT_POSTURE` | Tenant context | Idempotency-Key | Project ID |
|--------------------|----------------|-----------------|------------|
| `dev` | optional, defaults to `tenant_dev` | optional | optional |
| `research` | required (raises 401 if missing) | required for write routes | required on `/v1/runs` |
| `prod` | required + JWT validation | required for write routes | required on `/v1/runs` |

---

## 15. Quality Requirements

| Quality attribute | Target | Enforcement |
|-------------------|--------|-------------|
| v1 contract stability | 0 breaking changes after release | `scripts/check_contract_freeze.py` (digest snapshot) |
| Layering integrity | No `hi_agent.*` import in `agent_server/api/` | `scripts/check_layering.py` |
| Test discipline | Every new route handler has TDD evidence | `scripts/check_tdd_evidence.py` |
| Facade conciseness | ≤200 LOC per facade module | `scripts/check_facade_loc.py` |
| Tenant isolation | `TenantContext` resolved by middleware exclusively | `scripts/check_route_scope.py` |
| Idempotency safety | Same `Idempotency-Key` + tenant returns identical response | unit + integration tests under `tests/integration/test_idempotency_*.py` |
| Cancellation contract | `POST /cancel` -> 200 live, 404 unknown | covered by `scripts/run_arch_7x24.py` assertion #3 |

---

## 16. Risks and Technical Debt

| Item | Status | Mitigation |
|------|--------|-----------|
| MCP integration is stub | `agent_server/mcp/` carries placeholder routes | Wave 28+ work; no production caller depends on it |
| Streaming SSE backpressure | Long-running runs may emit > buffer size | `_generator()` cooperates with event loop via `await asyncio.sleep(0)`; downstream sets `X-Accel-Buffering: no` |
| Idempotency cache TTL | Unbounded growth without TTL pruner | `IdempotencyFacade` accepts a `prune_after_seconds` argument; ops sets via env in research/prod |
| Workspace path traversal | User-controlled `workspace_id` could escape | `agent_server/workspace/` validates and `hi_agent/server/workspace_path.py` enforces; covered by security tests |

---

## 17. Glossary

| Term | Definition |
|------|-----------|
| Northbound | Direction *toward* downstream consumers; the public API surface that downstream apps depend on |
| Southbound | Direction *toward* `hi_agent` runtime; internal to this repo |
| Facade | A thin adapter that translates contract types to `hi_agent` callables; injected via constructor for testability |
| Contract | A frozen v1 schema in `agent_server/contracts/`; breaking changes require a `v2/` sub-package |
| `TenantContext` | Authenticated identity injected by middleware into `request.state`; carries `tenant_id`, `user_id`, `project_id` |
| `Idempotency-Key` | Client-provided header that scopes a write to "exactly once per tenant"; cached by middleware |
| ContractError | Typed error hierarchy with `http_status`; subclasses include `NotFoundError(404)`, `ConflictError(409)`, `RateLimitedError(429)` |
| Route handler | FastAPI endpoint function; invoked by middleware after tenant + idempotency resolution |
| TDD-red-sha | Annotation on every new route handler pointing to the commit SHA where the failing test was first written (R-AS-5) |
