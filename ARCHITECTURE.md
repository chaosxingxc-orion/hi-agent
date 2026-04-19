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
  ├─ agent_kernel/    — durable runtime substrate (inlined from agent-kernel)
  └─ agent-core       — reusable capability modules (integrated into hi_agent/)
```

External dependencies:
- **LLM providers**: Anthropic Claude, OpenAI (via `agent_kernel/cognitive/`)
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
| `llm/` | LLMGateway, TierRouter, ModelRegistry, budget tracker |
| `server/` | HTTP API (20+ endpoints), EventBus, SSE streaming, RunManager, DreamScheduler |

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
| `service/` | HTTP API server (Starlette), auth middleware |

---

## Integration Point

`hi_agent` calls `agent_kernel` exclusively through `KernelFacade`:

```python
from agent_kernel.adapters.facade.kernel_facade import KernelFacade
```

All run lifecycle operations (start, query, cancel, resume, signal, gate approval) go through this single entry point. No direct access to kernel internals is permitted.

---

## Execution Modes

| Mode | Entry | Description |
|------|-------|-------------|
| Linear | `RunExecutor.execute()` | Sequential stage execution |
| DAG | `RunExecutor.execute_graph()` | Graph traversal with backtrack |
| Async | `RunExecutor.execute_async()` | Full asyncio concurrent execution |

---

## Quality Gate

Current test baseline: **3858 passed, 13 skipped, 0 failures** (2026-04-19).

```bash
python -m pytest tests/ -v        # full suite
python -m ruff check hi_agent/ agent_kernel/   # lint
```
