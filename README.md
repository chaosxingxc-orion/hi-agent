# hi-agent

An enterprise-grade intelligent agent built on the **TRACE framework**: Task, Route, Act, Capture, Evolve.

## First Principles

- **P1**: The agent must continuously evolve
- **P2**: The cost of driving the agent must continuously decrease

## Quick Start

```bash
# Run a task
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# Start API server
python -m hi_agent serve --port 8080

# Resume from checkpoint
python -m hi_agent resume --checkpoint checkpoint_run-001.json

# Memory & knowledge management
curl -X POST http://localhost:8080/memory/dream
curl "http://localhost:8080/knowledge/query?q=revenue+trends"
curl -X POST http://localhost:8080/skills/evolve

# Run tests
python -m pytest tests/ -v
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       hi-agent Architecture                         │
│                                                                     │
│  Model-Driven Management                                            │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ ModelRegistry → TierRouter → ModelSelector (budget-aware)   │     │
│  │ LLMGateway (sync) + AsyncLLMGateway (async/httpx)          │     │
│  │ HttpLLMGateway, HTTPGateway, AnthropicGateway, MockGateway │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Middleware Layer (independent contexts, ~86% cost savings)          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │Perception│→ │ Control  │→ │Execution │→ │Evaluation│           │
│  │ (light)  │  │ (medium) │  │ (dynamic)│  │ (light)  │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
│  5-phase lifecycle + extensible orchestrator                        │
│                                                                     │
│  Task Management (asyncio-native)                                   │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ AsyncTaskScheduler (Semaphore backpressure, 1000+ Runs)    │     │
│  │ GraphFactory (complexity-driven) → BudgetGuard (tier mgmt) │     │
│  │ RestartPolicyEngine (retry/reflect/escalate/abort)         │     │
│  │ ReflectionOrchestrator (LLM-driven failure recovery)       │     │
│  │ TrajectoryGraph (chain/tree/DAG + backtrack edges)         │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Execution Modes                                                    │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ execute()       — linear stage traversal (S1→S5)           │     │
│  │ execute_graph() — dynamic graph with backtrack + routing    │     │
│  │ execute_async() — full asyncio + AsyncTaskScheduler         │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Context OS                                                         │
│  ┌────────┐ ┌────────┐ ┌─────────┐ ┌─────────┐ ┌──────┐          │
│  │Context │ │Session │ │Memory   │ │Knowledge│ │Skill │          │
│  │Manager │ │+Resume │ │3-tier + │ │Wiki +   │ │Evolve│          │
│  │RunCtx  │ │Chkpoint│ │AsyncComp│ │Graph +  │ │A/B   │          │
│  │isolate │ │        │ │ressor  │ │4L-Retr. │ │Test  │          │
│  └────────┘ └────────┘ └─────────┘ └─────────┘ └──────┘          │
│                                                                     │
│  Runtime Adapter                                                    │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ 17-method Protocol → KernelFacadeAdapter (sync)            │     │
│  │ AsyncKernelFacadeAdapter + execute_turn() (async)          │     │
│  │ ResilientAdapter (retry + circuit breaker + event buffer)  │     │
│  └────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
        │                              │
   agent-kernel                   agent-core
   (durable runtime)         (capability modules)
```

## Three-Repository Architecture

| Repository | Role |
|-----------|------|
| **hi-agent** (this repo) | Sole intelligent agent — owns all cognitive logic, decision making, graph scheduling, restart policy, reflection |
| **agent-kernel** | Durable runtime substrate — run lifecycle, TurnEngine, event log, idempotency, state tracking (TaskRegistry, TaskWatchdog) |
| **agent-core** | Reusable capability modules — tools, retrieval, MCP, workflows |

## Model-Driven Management

Models are **registered at runtime by LLM gateways**, not hardcoded. Each model carries capability tags.

```
Gateway registers → ModelRegistry → TierRouter (purpose→tier) → ModelSelector (budget-aware)
```

| Protocol | Implementation | Use Case |
|----------|---------------|----------|
| `LLMGateway` (sync) | `HttpLLMGateway` (urllib) | Synchronous calls |
| `AsyncLLMGateway` (async) | `HTTPGateway` (httpx pool) | Async concurrent calls |
| — | `AnthropicGateway` | Anthropic-specific |

## Task Management

```
AsyncTaskScheduler (asyncio + Semaphore backpressure)
    │
    ├─ GraphFactory → complexity-driven graph templates
    ├─ BudgetGuard → tier downgrade + optional node skip
    ├─ RestartPolicyEngine → retry / reflect / escalate / abort
    │   └─ ReflectionOrchestrator → LLM-driven failure recovery
    │       └─ ReflectionBridge → build failure context for model
    └─ RunContext → per-run state isolation + serialization
        └─ RunContextManager → concurrent run management
```

Three execution modes:

| Mode | Method | Use Case |
|------|--------|----------|
| Linear | `execute()` | Sequential S1→S5 stage traversal |
| Graph-driven | `execute_graph()` | Dynamic traversal with backtrack edges + multi-successor routing |
| Async | `execute_async()` | Full asyncio with AsyncTaskScheduler + KernelFacade |

## Capability Subsystem

| Component | Sync | Async |
|-----------|------|-------|
| Invoker | `CapabilityInvoker` (ThreadPool timeout, retry) | `AsyncCapabilityInvoker` (asyncio.wait_for, exponential backoff) |
| Circuit Breaker | `CircuitBreaker` (closed→open→half_open with cooldown) | Same (shared) |
| Registry | `CapabilityRegistry` (named handlers) | Same (shared) |

## Context OS

### Session (checkpoint/resume)

```
Run → checkpoint every Stage (JSON) → crash → resume → skip completed → continue
```

### Memory (three-tier with async compression)

```
Run ends → auto-build ShortTermMemory
POST /memory/dream → DreamConsolidator → DailySummary
AsyncMemoryCompressor → LLM-powered L1 summarization (fallback: concat)
Next Run → RetrievalEngine (4-layer) → routing context
```

### Knowledge (wiki + graph + four-layer retrieval)

```
Query → L1:grep → L2:BM25 → L3:graph traverse → L4:embedding(optional)
Run ends → auto-ingest findings→wiki, facts→graph, feedback→user profile
```

### Skill (evolution pipeline)

```
SKILL.md discovery → SkillLoader (token-budget binary search)
Execution → SkillObserver (async JSONL) → SkillMetrics
Analysis → SkillEvolver: textual gradient→new prompt / pattern→new skill
Deploy → SkillVersionManager: challenger vs champion (A/B traffic split)
```

## Safety Mechanisms

- **CircuitBreaker**: closed→open→half_open with configurable cooldown
- **Dead-end detection**: Integrated into runner stage loop
- **Runner exception protection**: Top-level try/except wrapping stage execution
- **Exponential backoff**: AsyncCapabilityInvoker with jitter
- **Resilient adapter**: Retry + circuit breaker + event buffer for kernel calls

## Engineering Gates (all passed)

| Gate | Description | Key Deliverables |
|------|-------------|------------------|
| 1 | Async foundation | AsyncTaskScheduler, EventBus, httpx gateway |
| 2 | Kernel integration | AsyncKernelFacadeAdapter, execute_turn() |
| 3 | LLM wiring | AsyncLLMGateway, HTTPGateway.complete(), AsyncMemoryCompressor |
| 4 | Safety mechanisms | AsyncCapabilityInvoker, runner exception protection |
| 5 | Graph-driven execution | execute_graph(), backtrack edges, multi-successor routing |
| 6 | Concurrent isolation | RunContext, RunContextManager, per-run state serialization |

## API Endpoints (20+)

```
Tasks:      POST /runs, GET /runs/{id}, POST /runs/{id}/resume, GET /health
Memory:     POST /memory/dream, POST /memory/consolidate, GET /memory/status
Knowledge:  POST /knowledge/ingest, /ingest-structured, GET /query, POST /sync, /lint, GET /status
Skills:     GET /skills/list, /skills/{id}/metrics, /skills/{id}/versions,
            POST /skills/evolve, /skills/{id}/optimize, /skills/{id}/promote, GET /skills/status
Context:    GET /context/health
SSE:        GET /events/stream (real-time event streaming)
```

## Configuration

All 95+ parameters configurable via three methods:

```python
config = TraceConfig(compress_snip_threshold=100, default_model="claude-sonnet-4")
config = TraceConfig.from_file("production.json")
config = TraceConfig.from_env()  # HI_AGENT_* prefix
```

## Stats

| Metric | Value |
|--------|-------|
| Source modules | 252 |
| Source LOC | ~34,000 |
| Test LOC | ~35,000 |
| Tests | 2,067 passing |
| External deps | 0 (httpx optional) |
| Config params | 95+ |
| API endpoints | 20+ |

## Documentation

| Document | Description |
|----------|-------------|
| `architecture-review/` | Architecture design baseline (V2.0) |
| `docs/superpowers/specs/` | Parallel scalability design spec |
| `docs/superpowers/plans/` | Implementation plans |
| `docs/module-evolution-analysis.md` | Module gap analysis against P1/P2 |
| `docs/agent-kernel-integration-proposal.md` | Kernel integration plan |

## Human Gate Types

- **Gate A** (`contract_correction`) — modify task contract mid-run
- **Gate B** (`route_direction`) — guide path selection
- **Gate C** (`artifact_review`) — review/edit outputs
- **Gate D** (`final_approval`) — gate high-risk final actions

## Standard Failure Codes

`missing_evidence`, `invalid_context`, `harness_denied`, `model_output_invalid`, `model_refusal`, `callback_timeout`, `no_progress`, `contradictory_evidence`, `unsafe_action_blocked`, `budget_exhausted`
