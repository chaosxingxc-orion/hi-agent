# ARCHITECTURE: System Overview (L0)

> **Architecture hierarchy**
> - L0 system boundary: this file
> - L1 hi-agent detail: [`hi_agent/ARCHITECTURE.md`](hi_agent/ARCHITECTURE.md)
> - L1 agent-kernel detail: [`agent_kernel/ARCHITECTURE.md`](agent_kernel/ARCHITECTURE.md)

---

## System Boundary

```text
hi-agent repository
  ├─ hi_agent/        — agent brain (orchestration, cognition, memory, skills)
  ├─ agent_kernel/    — durable runtime substrate (inlined; was external git dep)
  └─ agent-core       — reusable capability modules (integrated into hi_agent/)
```

External dependencies:
- **LLM providers**: Anthropic Claude, OpenAI, Volces Ark (doubao / minimax / glm / deepseek / kimi) — configured via `config/llm_config.json`
- **Workflow substrate**: Local FSM (default) or Temporal (optional)
- **Storage**: SQLite (default) or PostgreSQL (optional)

---

## Component Roles

| Package | Role |
|---------|------|
| `hi_agent` | Agent brain: task understanding, route decisions, execution orchestration, memory/knowledge/skills, continuous evolution |
| `agent_kernel` | Durable runtime: run lifecycle, event-fact log, idempotency, six-authority governance, failure recovery |

### hi_agent — subsystems

| Module | Responsibility |
|--------|---------------|
| `runner.py` / `execution/` | RunExecutor: linear, DAG, async execution modes; gate blocking; reflection injection |
| `middleware/` | 4-phase pipeline: Perception → Control → Execution → Evaluation |
| `route_engine/` | Rule / LLM / Hybrid / Skill-aware routing; DecisionAuditStore |
| `task_mgmt/` | AsyncTaskScheduler, BudgetGuard, RestartPolicyEngine, ReflectionOrchestrator |
| `context/` | ContextManager (7-section budget, 4 thresholds, compression chain) |
| `memory/` | L0 Raw → L1 STM → L2 MidTerm (Dream) → L3 LongTerm (graph) |
| `knowledge/` | Wiki, knowledge graph, four-layer retrieval (grep→BM25→graph→embedding) |
| `skill/` | SkillLoader, SkillVersionManager (A/B), SkillEvolver |
| `harness/` | Dual-dimension governance, PermissionGate, EvidenceStore |
| `llm/` | LLMGateway, TierRouter, ModelRegistry, budget tracker; HttpLLMGateway for OpenAI-compatible endpoints |
| `server/` | HTTP API (20+ endpoints), EventBus, SSE streaming, RunManager, DreamScheduler |
| `runtime_adapter/` | 22-method RuntimeAdapter protocol; KernelFacadeAdapter (sync); AsyncKernelFacadeAdapter; ResilientKernelAdapter |

### agent_kernel — subsystems

| Module | Responsibility |
|--------|---------------|
| `adapters/facade/` | `KernelFacade` — sole legal platform entry point |
| `kernel/` | Six authorities: RuntimeEventLog, DecisionProjection, DispatchAdmission, ExecutorService, RecoveryGate, DedupeStore |
| `kernel/cognitive/` | LLMGateway (Anthropic, OpenAI), ScriptRuntime |
| `kernel/persistence/` | SQLite and PostgreSQL backends for event log, dedupe store, projection cache |
| `kernel/recovery/` | Circuit breaker, compensation registry, reflection-and-retry |
| `runtime/` | AgentKernelRuntimeBundle — component assembly and observability |
| `substrate/` | LocalFSMAdaptor (default) / TemporalAdaptor (optional) |
| `service/` | HTTP API server (Starlette), auth middleware; source of truth for all kernel endpoint definitions |

---

## Integration Point

`hi_agent` calls `agent_kernel` exclusively through two layers:

```python
# High-level: KernelFacade (direct in-process)
from agent_kernel.adapters.facade.kernel_facade import KernelFacade

# HTTP: KernelFacadeAdapter (when kernel runs as a separate service)
from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter
```

**Contract lock (Rule 7):** `agent_kernel/service/http_server.py` is the single authority for all endpoint definitions. `hi_agent/runtime_adapter/kernel_facade_client.py` is the single HTTP client. Both files must be audited together on every change; a side-by-side path/method table is required in every PR touching either file.

---

## Execution Modes

| Mode | Entry | Description |
|------|-------|-------------|
| Linear | `RunExecutor.execute()` | Sequential stage execution |
| DAG | `RunExecutor.execute_graph()` | Graph traversal with backtrack |
| Async | `RunExecutor.execute_async()` | Full asyncio concurrent execution |

---

## Deployment Configuration (runtime_mode)

`runtime_mode` is derived by `hi_agent/server/runtime_mode_resolver.py` from `HI_AGENT_ENV` plus the live readiness snapshot; all downstream checks (`/ready`, `/manifest`, `/diagnostics`, auth middleware posture) converge on this single function.

| runtime_mode | Trigger | kernel routing | LLM | Heuristic fallback |
|--------------|---------|----------------|-----|---------------------|
| `dev-smoke`  | default (no env) | in-process LocalFSM | heuristic if API key absent | allowed |
| `local-real` | `HI_AGENT_LLM_MODE=real` + `HI_AGENT_KERNEL_MODE=http` | LocalFSM or HTTP client | real LLM | allowed |
| `prod-real`  | `HI_AGENT_ENV=prod` | HTTP client (when `HI_AGENT_KERNEL_BASE_URL` is set) or LocalFSM (warned) | real LLM required | **disabled**, fail-fast 503 |

### Canonical env surface (authoritative list: [`docs/deployment-env-matrix.md`](docs/deployment-env-matrix.md))

Every `HI_AGENT_*` field on `TraceConfig` is populated by `TraceConfig.from_env()`. The `AgentServer()` no-config path calls this automatically, so deploy-time env bindings take effect without a config file.

Critical names for prod deploys:

| Variable | Code site | Effect |
|----------|-----------|--------|
| `HI_AGENT_ENV=prod` | `server/app.py`, `server/runtime_mode_resolver.py` | Enables prod-real posture and P1-6 fail-fast executor build |
| `HI_AGENT_KERNEL_BASE_URL=http://…` | `config/runtime_builder.py` → `KernelFacadeClient` | Routes all kernel RPC to the detached agent-kernel service. Empty or `"local"` keeps in-process LocalFSM |
| `HI_AGENT_OPENAI_BASE_URL=https://…/v2` | `llm/http_gateway.py` | Gateway issues `POST {base_url}/chat/completions` (absolute path preserves `/v2` and other non-`/v1` segments — P0-3 fix) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | providers | Presence flips dev-smoke clamp off and satisfies prod `platform_not_ready` gate |

Explicitly **unsupported** aliases (silently ignored — don't set these): `KERNEL_BASE_URL` (missing prefix), `HI_AGENT_KERNEL_URL` (legacy; only `/doctor` has a fallback), `OPENAI_BASE_URL`, `MODEL`.

### Deploy verification endpoints

| Endpoint | Guarantee |
|----------|-----------|
| `GET /diagnostics` | Compact fingerprint of the env/config that hi-agent actually resolved — always 200, never a gate. First check after deploy. |
| `GET /doctor` | Structured `DoctorReport`; in prod performs a real HTTP probe against `HI_AGENT_KERNEL_BASE_URL`. 503 = blocking issue. |
| `GET /health` | Per-subsystem status. `kernel_adapter.status` is `lazy` until first run; `configured_base_url` reflects deploy env binding. |
| `GET /ready` | 200 when ready for traffic, 503 otherwise. |

A Rule-8 smoke matrix ([`.github/workflows/smoke.yml`](.github/workflows/smoke.yml)) pins the 04-21 incident as a regression anchor: the `prod-no-credentials` row must return 503 on `POST /runs` — a regression that lets it return 201+stuck fails CI.

---

## LLM Provider Configuration

All LLM parameters flow through `config/llm_config.json` (gitignored; copy from `config/llm_config.example.json`):

```json
{
  "providers": {
    "anthropic": { "api_key": "...", "api_format": "anthropic" },
    "openai":    { "api_key": "...", "api_format": "openai" },
    "volces":    { "api_key": "...", "base_url": "...", "all_models": ["doubao-seed-2.0-code", ...] }
  }
}
```

`tests/conftest.py` loads this file at session start to populate env vars (`VOLCE_API_KEY`, `VOLCE_BASE_URL`) for live API tests.

---

## Platform Contract (Wave 9)

### Posture System

`HI_AGENT_POSTURE={dev,research,prod}` (default `dev`) controls fail-closed vs permissive defaults. Code: `hi_agent/config/posture.py::Posture.from_env()`.

| Posture | project_id | queue backend | schema validation | idempotency scope |
|---|---|---|---|---|
| `dev` | warn-only | in-memory allowed | warn + skip | body tenant_id |
| `research` | 400 required | SQLite file | ValueError | authenticated TenantContext |
| `prod` | 400 required | SQLite file | ValueError | authenticated TenantContext |

### Owner Tracks

| Track | Owns | Rule |
|---|---|---|
| CO | API/artifact/capability/profile schemas, posture | Any public-dataclass/schema/posture change = CO; include contract-version bump |
| RO | Execution, state machines, persistence boundaries | In-memory state under research/prod = defect; durable-store changes need restart test |
| DX | Developer journey: first contact → upgrade | No L2 without documented quickstart, doctor-check, and structured error category |
| TE | Artifacts, evidence, provenance, evolution | Every silent-degradation path: Countable + Attributable + Inspectable + Gate-asserted |
| GOV | CLAUDE.md, capability matrix, CI, delivery docs | Capability matrix = single source of truth; delivery notice, TODO, matrix agree at every push |

### Capability Maturity (L0–L4)

| Level | Name | Criterion |
|---|---|---|
| L0 | demo code | happy path only, no stable contract |
| L1 | tested component | unit/integration tests exist, not default path |
| L2 | public contract | schema/API/state machine stable, docs + full tests |
| L3 | production default | research/prod default-on, migration + observability |
| L4 | ecosystem ready | third-party can register/extend/upgrade/rollback without source |

Wave 9 contracts: `TeamRunSpec` (`hi_agent/contracts/team_runtime.py`), `ReasoningTrace` (`hi_agent/contracts/reasoning_trace.py`), canonical `CapabilityDescriptor` (`hi_agent/capability/registry.py`), `ArtifactLedger` quarantine (`hi_agent/artifacts/ledger.py`).

---

## Quality Gate

```bash
python -m pytest tests/ -q --ignore=tests/integration/test_live_llm_api.py   # full offline suite
python -m pytest tests/integration/test_live_llm_api.py -m live_api -v       # live API (33 tests, 8 models)
python -m ruff check hi_agent/ agent_kernel/                                  # lint
```

Current baseline: **4,100 passed (unit+integration, Wave 9)** (2026-04-25, offline suite excluding live API and prod E2E; all xfail/xpass stubs deleted).

Live API test suite (`@pytest.mark.live_api`): 33 tests × 5 scenarios (smoke, multi-turn, code generation, state isolation, latency) parameterized over all 8 Volces Ark models. Auto-skipped when `VOLCE_API_KEY` is absent; config loaded from `config/llm_config.json` (gitignored) — copy from `config/llm_config.example.json`.
