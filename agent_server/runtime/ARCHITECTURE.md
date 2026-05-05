# agent_server/runtime/ Architecture

> Last refreshed: Wave 33 (2026-05-04). Sub-package shipped in W32 Track A; W33-C.4 added the auth seam, W33-C.5 made `iter_events` a true live stream, W33-C.1 wired the lifespan into FastAPI startup with active watchdog tasks.

---

## 1. Purpose & Position in System

`agent_server/runtime/` is the **second R-AS-1 seam** under `agent_server/`, paired with `bootstrap.py`. It carries three concerns:

1. **Real-kernel binding (W32 Track A)** — `RealKernelBackend` exposes the seven contract-shaped facade callables backed by a live `hi_agent.server.app.AgentServer` whose `run_manager`, `event_store`, `run_store`, `run_queue`, `idempotency_store`, `gate_store`, `team_event_store` are durable SQLite-backed.
2. **Lifespan integration (W32-A + W33-C.1)** — `build_real_kernel_lifespan` builds the AgentServer on FastAPI startup, runs `_rehydrate_runs`, and starts module-level helper tasks (`_lease_expiry_loop`, `_current_stage_watchdog`) that are cancelled cleanly on shutdown.
3. **Auth validation seam (W33-C.4)** — `auth_seam.validate_authorization` reuses the platform's JWT primitives so `agent_server/api/middleware/auth.py` can validate tokens without itself crossing the R-AS-1 boundary.

Before W32, `agent_server/bootstrap.py::_InProcessRunBackend` returned `state="queued"` without ever executing the run — this satisfied the route-level test profile but was a "fake" northbound idempotency claim under research/prod. W32 Track A replaced that stub with `RealKernelBackend` from this sub-package; `AGENT_SERVER_BACKEND=real` is the default under all postures and the only legal setting under research/prod.

What it does NOT own:
- HTTP transport (`agent_server/api/`).
- Contract-shape adaptation (`agent_server/facade/`).
- Run execution itself (`hi_agent/server/run_manager.py`, `hi_agent/runner.py`).
- Durable persistence schema (`hi_agent/server/run_store.py`, `hi_agent/server/event_store.py`).

It is a **thin adapter**: every method returns a contract-shaped dict identical in shape to the kernel's, so the facade layer needs no change.

---

## 2. External Interfaces

The runtime sub-package exposes the following public symbols:

| Symbol | Type | Purpose |
|---|---|---|
| `RealKernelBackend` | class | Wraps an `AgentServer` instance; exposes the seven callables `start_run` / `get_run` / `signal_run` / `cancel_run` / `iter_events` / `list_artifacts` / `get_artifact`. `iter_events` is a true live stream (W33-C.5) — it yields events as they appear in the event store and only closes when the run reaches a terminal state. |
| `build_real_kernel_lifespan` | function | FastAPI lifespan handler factory; constructs `AgentServer` on startup, runs `_rehydrate_runs`, starts watchdog tasks (`_lease_expiry_loop`, `_current_stage_watchdog`), and drains/closes on shutdown (W33-C.1). |
| `validate_authorization` | function | Pure JWT validator (W33-C.4); accepts the raw `Authorization` header, returns `ValidationOutcome(ok, status, reason, claims)`. Used by `agent_server/api/middleware/auth.py`. |
| `ValidationOutcome` | dataclass | Immutable result of `validate_authorization`. |

Callable signatures (all keyword-only, returning `dict[str, Any]` modeled on the existing facade contract):

```python
backend.start_run(*, tenant_id, profile_id, goal, project_id, run_id, idempotency_key, metadata) -> dict
backend.get_run(*, tenant_id, run_id) -> dict
backend.signal_run(*, tenant_id, run_id, signal, payload) -> dict
backend.cancel_run(*, tenant_id, run_id) -> dict
backend.iter_events(*, tenant_id, run_id) -> Iterable[dict]
backend.list_artifacts(*, tenant_id, run_id) -> list[dict]
backend.get_artifact(*, tenant_id, artifact_id) -> dict
```

Construction signature:

```python
RealKernelBackend(*, agent_server: hi_agent.server.app.AgentServer)
```

The constructor takes a fully-built `AgentServer`; this means the sub-package does NOT own the durable-store wiring — `AgentServer.__init__` already does that via `build_durable_backends()`. The runtime adapter simply binds method names.

---

## 3. Internal Components

```mermaid
graph TD
    subgraph runtime["agent_server/runtime/ (R-AS-1 seam #2)"]
        ADAPTER["kernel_adapter.py<br/>RealKernelBackend"]
        LIFESPAN["lifespan.py<br/>build_real_kernel_lifespan()<br/>+ _lease_expiry_loop<br/>+ _current_stage_watchdog"]
        AUTH["auth_seam.py (W33-C.4)<br/>validate_authorization()<br/>ValidationOutcome"]
    end

    subgraph hi_agent_umbrella["hi_agent.server.app.AgentServer (umbrella)"]
        AS["AgentServer (instance)"]
        RM["run_manager: RunManager"]
        RS["_run_store: SQLiteRunStore"]
        RQ["_run_queue: RunQueue"]
        ES["_event_store: SQLiteEventStore"]
        IS["_idempotency_store: IdempotencyStore"]
        GS["_gate_store: GateStore"]
        TS["_team_event_store: TeamEventStore"]
        REHYDRATE["_rehydrate_runs()"]
    end

    subgraph hi_agent_auth["hi_agent.auth + server.auth_middleware"]
        JWTPRIM["validate_jwt_claims<br/>_verify_jwt<br/>_decode_jwt_payload"]
    end

    BOOTSTRAP["agent_server/bootstrap.py<br/>build_production_app()"]
    APIMW["agent_server/api/middleware/auth.py<br/>JWTAuthMiddleware"]

    BOOTSTRAP -->|"AGENT_SERVER_BACKEND=real (default)"| ADAPTER
    BOOTSTRAP --> LIFESPAN
    LIFESPAN --> AS
    ADAPTER --> AS
    AS --> RM
    AS --> RS
    AS --> RQ
    AS --> ES
    AS --> IS
    AS --> GS
    AS --> TS
    LIFESPAN --> REHYDRATE
    APIMW --> AUTH
    AUTH -. "r-as-1-seam: JWT primitives" .-> JWTPRIM
```

| Component | Responsibility |
|---|---|
| `kernel_adapter.py::RealKernelBackend` | Binds AgentServer's run_manager / event_store callables to the seven contract-shaped facade entry points; converts `ManagedRun` objects to dicts via `RunManager.to_dict`; `iter_events` is a live stream (W33-C.5) |
| `lifespan.py::build_real_kernel_lifespan` | Returns an async context manager that: (a) constructs `AgentServer`, (b) triggers `_rehydrate_runs`, (c) starts module-level watchdog tasks (`_lease_expiry_loop`, `_current_stage_watchdog`) — W33-C.1, (d) drains in-flight work and cancels watchdogs on shutdown |
| `auth_seam.py::validate_authorization` | W33-C.4: pure function returning `ValidationOutcome`; passthrough under dev posture, fail-closed (401) under research/prod; bridges `hi_agent.auth.jwt_middleware` and `hi_agent.server.auth_middleware` JWT primitives |
| `__init__.py` | Public surface — `__all__ = ["RealKernelBackend", "build_real_kernel_lifespan"]` and the R-AS-1 seam annotation comment |

---

## 4. Data Flow

Representative `POST /v1/runs` flow through the real kernel:

```mermaid
sequenceDiagram
    participant Client
    participant Route as routes_runs.post_run
    participant RunFacade
    participant Backend as RealKernelBackend
    participant RunMgr as RunManager
    participant Queue as RunQueue
    participant Executor
    participant EvtEmitter as RunEventEmitter
    participant EvtStore as SQLiteEventStore

    Client->>+Route: POST /v1/runs {goal, profile_id, idempotency_key}
    Route->>+RunFacade: start(ctx, RunRequest)
    RunFacade->>+Backend: start_run(tenant_id=..., profile_id=..., goal=..., ...)
    Backend->>Backend: build TaskContract dict
    Backend->>+RunMgr: create_run(task_contract_dict, workspace=tenant_id)
    RunMgr->>RunMgr: idempotency dedup (SQLite)
    RunMgr->>RunMgr: persist to RunStore
    RunMgr->>+Queue: enqueue
    Queue-->>-RunMgr: lease assigned
    RunMgr-->>-Backend: ManagedRun(run_id="run_abc", state="queued")
    Backend->>+RunMgr: start_run(run_id, executor_fn)
    Note over RunMgr,Executor: background asyncio.Task
    RunMgr-->>-Backend: None (background)
    Backend->>Backend: RunManager.to_dict(run) -> dict
    Backend-->>-RunFacade: {tenant_id, run_id, state="queued", ...}
    RunFacade-->>-Route: RunResponse
    Route-->>-Client: 201 Created {run_id, state="queued"}

    par Background execution
        Executor->>EvtEmitter: record_stage_started(...)
        EvtEmitter->>EvtStore: append(StoredEvent)
    and Client polling
        Client->>Route: GET /v1/runs/{run_id}/events
        Route->>EvtStore: list_since(run_id, sequence=0)
        EvtStore-->>Route: [StoredEvent, ...]
        Route-->>Client: SSE stream
    end
```

The seam-discipline-relevant points:
- The route handler never sees `RunManager` — only `RunFacade`.
- `RunFacade` never sees `RunManager` — only the `start_run` callable injected at construction time.
- `RealKernelBackend` is the only object holding both contract-shaped dict outputs *and* a reference to the kernel `AgentServer` instance.

---

## 5. State & Persistence

`agent_server/runtime/` itself owns **zero state**. All state lives in the `AgentServer` instance it adapts:

| State | Owner | Backend |
|---|---|---|
| Run records | `AgentServer._run_store` | `SQLiteRunStore` (`<state_dir>/runs.db`) |
| Event log | `AgentServer._event_store` | `SQLiteEventStore` (`<state_dir>/events.db`) |
| Run queue + leases | `AgentServer._run_queue` | `RunQueue` (`<state_dir>/queue.db`) |
| Idempotency cache | `AgentServer._idempotency_store` | `IdempotencyStore` (`<state_dir>/idempotency.db`) |
| Team event log | `AgentServer._team_event_store` | `TeamEventStore` (`<state_dir>/team_events.db`) |
| Gate decisions | `AgentServer._gate_store` | `GateStore` (`<state_dir>/gates.db`) |

State directory resolution (via `bootstrap.py::_default_state_dir()`):
1. `AGENT_SERVER_STATE_DIR` env var
2. `HI_AGENT_HOME/.agent_server`
3. `./.agent_server` (CWD-relative fallback)

The lifespan handler does NOT call `mkdir` — that's the bootstrap's job, performed before `build_real_kernel_lifespan` is invoked.

---

## 6. Concurrency & Lifecycle

The lifespan handler integrates with the FastAPI `lifespan` ASGI hook (Starlette's `Lifespan`):

```mermaid
sequenceDiagram
    participant Uvicorn
    participant Bootstrap as build_production_app
    participant Lifespan as build_real_kernel_lifespan
    participant AS as AgentServer
    participant Rehydrate as _rehydrate_runs

    Uvicorn->>Bootstrap: import + call build_production_app()
    Bootstrap->>Bootstrap: choose backend (env: AGENT_SERVER_BACKEND)
    Bootstrap->>Lifespan: factory(state_dir, posture)
    Lifespan-->>Bootstrap: lifespan context manager
    Bootstrap-->>Uvicorn: FastAPI app (lifespan attached)

    Uvicorn->>+Lifespan: startup
    Lifespan->>+AS: AgentServer(host, port, config)
    Note over AS: __init__ builds durable backends,<br/>RunManager, EventBus
    AS-->>-Lifespan: server instance
    Lifespan->>+Rehydrate: _rehydrate_runs(server)
    Note over Rehydrate: requeue lease-expired runs<br/>(posture-aware: warn-only in dev,<br/>requeue under research/prod)
    Rehydrate-->>-Lifespan: None
    Lifespan-->>-Uvicorn: ready (yield)

    Note over Uvicorn,AS: serving requests via RealKernelBackend

    Uvicorn->>+Lifespan: shutdown
    Lifespan->>AS: aclose() / shutdown
    AS->>AS: drain in-flight runs (graceful)
    AS->>AS: close run_store / event_store / queue / idempotency
    Lifespan-->>-Uvicorn: clean exit
```

Rule 5 (Async/Sync Resource Lifetime) considerations:
- The `AgentServer` instance is constructed inside the lifespan startup phase, so its `RunManager` event loop matches uvicorn's loop.
- `RealKernelBackend` methods are **synchronous wrappers** that schedule async work on `RunManager` via the kernel's existing threadsafe entry points (no per-method `asyncio.run`).
- The rehydration runs once on startup, not per-request — see `hi_agent/server/app.py:1196`.

---

## 7. Error Handling & Observability

Errors raised by the kernel:
- `hi_agent.server.errors.NotFound` → mapped to `agent_server.contracts.errors.NotFoundError(404)` by `RealKernelBackend.get_run` and `signal_run`.
- `hi_agent.server.errors.IdempotencyConflict` → mapped to `ConflictError(409)`.
- Posture-strict refusal (e.g., missing tenant_id) → mapped to `ContractError(400)` with `error_category="contract_violation"`.

Observability emissions during a run:
| Event type | Source | Purpose |
|---|---|---|
| `tenant_context` | `agent_server` middleware | every request boundary (W31-N N.4) |
| `run_created` | `RunManager` | after `create_run` returns |
| `run_started`, `stage_started`, `stage_completed`, `run_completed` | `RunEventEmitter` | run lifecycle (12 typed events total) |
| `dlq_checked`, `recovery_decision` | `_rehydrate_runs` | startup-time recovery audit |

All events flow through `hi_agent/observability/event_emitter.py::RunEventEmitter` and persist via `SQLiteEventStore`. The agent_server SSE stream (`GET /v1/runs/{id}/events`) reads from the same store.

---

## 8. Security Boundary

`agent_server/runtime/{kernel_adapter,lifespan,auth_seam}.py` each carry the explicit annotation:

```python
# r-as-1-seam: <reason>
```

This is the lint-recognized marker that `scripts/check_layering.py` consults to allow `hi_agent.*` imports. Two seams exist under `agent_server/`:

1. `agent_server/bootstrap.py` — builds the FastAPI app, wires facades.
2. `agent_server/runtime/**` — `kernel_adapter.py` + `lifespan.py` bind the real kernel; `auth_seam.py` (W33-C.4) reuses JWT primitives.

No other module under `agent_server/` is permitted to `from hi_agent...` or `import hi_agent`. The gate fails CI on any third seam.

**Auth seam contract (W33-C.4):**
- Bearer extraction is permissive: a malformed prefix returns `None` so the validator can choose dev-passthrough vs strict-reject.
- Under research/prod, missing `HI_AGENT_JWT_SECRET` is itself a fail-closed condition — forged tokens cannot be rejected without a key, so the validator returns `status=401, reason=jwt_secret_missing`.
- The `HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS` escape hatch is dev-only and short-circuits to `_decode_jwt_payload`; production callers MUST set the secret.

Tenant isolation: `RealKernelBackend` passes `tenant_id` through to the kernel verbatim. Every `RunManager` / `EventStore` call is tenant-scoped at the SQL layer. The adapter does not perform its own access control — that is the kernel's responsibility.

---

## 9. Extension Points

Adding a new backend (e.g., a remote-kernel adapter for sharded deployments):

1. Create `agent_server/runtime/<new_adapter>.py` with the seam annotation `# r-as-1-seam: <reason>`.
2. Implement the same seven callables with identical kwargs and return shapes.
3. Add a discriminator value (e.g., `AGENT_SERVER_BACKEND=remote`) and update `bootstrap.py::build_production_app` to dispatch.
4. Update `scripts/check_layering.py` allow-list if the new module imports a non-`hi_agent` external dependency.
5. Add an integration test under `tests/integration/test_v1_runs_<backend>_binding.py`.

The facade layer requires zero changes — the contract is the seven kwarg-only callables.

---

## 10. Constraints & Trade-offs

What this design assumes:
- A single `AgentServer` instance per process. Multi-tenant deployments scale out horizontally (one process per region/shard), not in-process.
- Durable stores are SQLite. PostgreSQL backends are NOT supported by this adapter; that would require a separate `RealKernelBackend` variant.
- Lifespan-startup rehydration is fire-and-forget. If `_rehydrate_runs` raises, the lifespan still completes; the kernel's own recovery audit logs the failure.

What this design does NOT handle well:
- Hot-reload of the `AgentServer` config. The lifespan builds it once on startup; config-file changes require a uvicorn restart.
- Cross-process run sharing. Two uvicorn workers each get their own `AgentServer` and stores; horizontally scaling demands an external durable backend (out of scope at v1).
- Streaming backpressure on `iter_events`. The current adapter returns a list snapshot; future work moves to async iteration with cursor pagination (tracked in W33).

---

## 11. References

- Sub-package files:
  - `agent_server/runtime/__init__.py`
  - `agent_server/runtime/kernel_adapter.py` — `RealKernelBackend` (W32-A; SSE live stream W33-C.5)
  - `agent_server/runtime/lifespan.py` — `build_real_kernel_lifespan` (W32-A; active watchdogs W33-C.1)
  - `agent_server/runtime/auth_seam.py` — `validate_authorization`, `ValidationOutcome` (W33-C.4)
- Bootstrap: `agent_server/bootstrap.py:188` (`build_production_app`)
- Kernel umbrella: `hi_agent/server/app.py:1645` (`AgentServer`)
- Rehydration: `hi_agent/server/app.py:1196` (`_rehydrate_runs`)
- Run management: `hi_agent/server/run_manager.py` (`RunManager`)
- Event store: `hi_agent/server/event_store.py` (`SQLiteEventStore`)
- Facades served by this adapter: `agent_server/facade/run_facade.py`, `event_facade.py`, `artifact_facade.py`
- Layering gate: `scripts/check_layering.py`
- Integration test: `tests/integration/test_v1_runs_real_kernel_binding.py` (created in W32 Track A)
- Plan: `docs/superpowers/plans/2026-05-03-wave-32-real-kernel-binding-and-cleanup.md` (Track A)
- R-AS-1 rule: `CLAUDE.md` (Ownership Tracks → AS-RO row + Narrow-Trigger Rules)
