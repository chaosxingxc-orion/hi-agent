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

## Quality Gate

```bash
python -m pytest tests/ -q --ignore=tests/integration/test_live_llm_api.py   # full offline suite
python -m pytest tests/integration/test_live_llm_api.py -m live_api -v       # live API (33 tests, 8 models)
python -m ruff check hi_agent/ agent_kernel/                                  # lint
```

Current baseline: **11,109 passed, 1 skipped, 1 xfailed, 0 failures** (2026-04-20, offline suite; prod E2E included via Volces Ark credentials in `config/llm_config.json`).

Live API test suite (`@pytest.mark.live_api`): 33 tests × 5 scenarios (smoke, multi-turn, code generation, state isolation, latency) parameterized over all 8 Volces Ark models. Auto-skipped when `VOLCE_API_KEY` is absent; config loaded from `config/llm_config.json` (gitignored) — copy from `config/llm_config.example.json`.
