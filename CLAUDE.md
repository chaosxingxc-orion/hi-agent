# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repository is in **active implementation — production engineering phase**. All 6 engineering gates passed. The `architecture-review/` directory contains the full design baseline (V2.0).

## First Principles

- **P1**: The agent must continuously evolve
- **P2**: The cost of driving the agent must continuously decrease

## Current Implementation

### Model-Driven Management

| Module | Description |
|---|---|
| `hi_agent/llm/` | LLMGateway + AsyncLLMGateway protocols, HttpLLMGateway (sync/urllib), HTTPGateway (async/httpx with connection pool), AnthropicGateway, MockGateway, ModelRegistry (runtime registration with capability tags), TierRouter (purpose→tier: strong/medium/light), ModelSelector (budget-aware selection with downgrade/upgrade), budget tracker |

### Middleware Layer (Four Middlewares + 5-Phase Lifecycle)

| Module | Description |
|---|---|
| `hi_agent/middleware/` | Perception (multimodal parse, entity extraction, summarization) → Control (TrajectoryGraph decomposition, resource binding) → Execution (minimal context, idempotent) → Evaluation (quality assess, reflection, escalation). 5-phase lifecycle hooks (pre_create→pre_execute→execute→post_execute→pre_destroy). Extensible orchestrator (add/replace/remove middlewares, custom routes, Mermaid visualization) |

### Task Management

| Module | Description |
|---|---|
| `hi_agent/task_mgmt/` | AsyncTaskScheduler (asyncio + Semaphore backpressure, O(1) pending_count), TaskScheduler (Superstep + Yield/Resume), GraphFactory (complexity-driven graph templates), BudgetGuard (tier downgrade + optional node skip), RestartPolicyEngine (retry/reflect/escalate/abort decisions), ReflectionOrchestrator + ReflectionBridge (LLM-driven failure recovery), TaskCommunicator (notifications, signals, broadcast), TaskMonitor (heartbeat, deadlock detection, timeline), TaskHandle (8-state lifecycle), PlanTypes (Sequential/Parallel/Conditional/DAG/Speculative with plan_to_graph()) |
| `hi_agent/trajectory/` | TrajectoryGraph (unified: chain/tree/DAG/general with backtrack edges), StageGraph (dynamic successors + backtrack), Superstep execution, conditional edges, Mermaid serialization, LLM plan import |

### Context OS (5 Sub-modules)

| Module | Description |
|---|---|
| `hi_agent/context/` | ContextManager (7-section budget allocation, 4-level thresholds GREEN→RED, compression fallback chain snip→compact→trim→block, circuit breaker, diminishing returns detection), RunContext (per-run mutable state container with serialize/deserialize), RunContextManager (concurrent run state management) |
| `hi_agent/session/` | RunSession (unified state, compact boundary dedup, L0 JSONL persistence, checkpoint save/resume), CostCalculator (per-model USD pricing) |
| `hi_agent/memory/` | Three-tier (short/mid/long-term), Dream consolidation (short→mid), LongTermConsolidator (mid→long graph), AsyncMemoryCompressor (LLM-powered L1 summarization with concat fallback), auto STM creation, RetrievalEngine→routing injection, MemoryLifecycleManager, unified retriever |
| `hi_agent/knowledge/` | Wiki (Karpathy pattern, `[[wikilinks]]`), user knowledge, graph renderer (Mermaid), four-layer retrieval (grep→BM25→graph→embedding), TF-IDF/BM25 engine, granularity model (Fact/Chunk/Page/Subgraph), auto-ingest from session, 6 API endpoints |
| `hi_agent/skill/` | SKILL.md definition (frontmatter+eligibility), SkillLoader (multi-source discovery, token-budget binary search full/compact), SkillObserver (async JSONL), SkillVersionManager (champion/challenger A/B), SkillEvolver (textual gradient optimization, pattern→new skill creation), 5-stage lifecycle, 7 API endpoints |

### TRACE Runtime

| Module | Description |
|---|---|
| `hi_agent/runner.py` | RunExecutor with execute() (linear), execute_graph() (dynamic graph traversal with backtrack + multi-successor routing), execute_async() (AsyncTaskScheduler integration), _execute_stage refactor, dead-end detection, exception protection, session resume from checkpoint, auto STM/knowledge creation, retrieval injection, context manager orchestration, skill observation, LLM cost tracking |
| `hi_agent/contracts/` | TaskContract (13 fields), PolicyVersionSet (6 versions), CTSBudget, TaskBudget |
| `hi_agent/route_engine/` | Rule, LLM, Hybrid, Skill-aware, Conditional routing with context-aware prompts |
| `hi_agent/task_view/` | Task view builder, token budgets, auto-compress trigger (snip→window→compress), context processor chain |
| `hi_agent/config/` | TraceConfig (95+ params, JSON/env/code), SystemBuilder (full subsystem wiring incl. memory/knowledge/skill/resume/context) |

### Governance & Evolution

| Module | Description |
|---|---|
| `hi_agent/harness/` | Dual-dimension governance (EffectClass + SideEffectClass), approval enforcement, evidence store |
| `hi_agent/evolve/` | Postmortem analyzer, LLM skill extraction, regression detector, champion/challenger |
| `hi_agent/failures/` | 10 frozen failure codes (enum), FailureCollector, ProgressWatchdog, typed exceptions |
| `hi_agent/state_machine/` | Generic StateMachine + 6 TRACE definitions (Run/Stage/Branch/Action/Wait/Review) |

### Infrastructure

| Module | Description |
|---|---|
| `hi_agent/server/` | HTTP API (20+ endpoints), EventBus (asyncio.Queue fan-out), SSE streaming endpoint, CLI, RunManager, MemoryLifecycleManager, knowledge/skill APIs, resume endpoint |
| `hi_agent/runtime_adapter/` | 17-method RuntimeAdapter protocol, MockKernel, MockKernelFacade (execute_turn contract), KernelFacadeAdapter (sync, 17-method + execute_turn), AsyncKernelFacadeAdapter (async wrapper for all methods), KernelFacadeClient (direct+HTTP), resilient adapter (retry+circuit breaker+event buffer) |
| `hi_agent/capability/` | CapabilityRegistry, CapabilityInvoker (sync, timeout+retry), AsyncCapabilityInvoker (asyncio.wait_for + exponential backoff), CircuitBreaker (closed→open→half_open with cooldown) |
| `hi_agent/events/` | Event emitter and store |
| `hi_agent/recovery/` | Compensation and recovery orchestration |
| `hi_agent/replay/` | Deterministic replay engine |
| `hi_agent/observability/` | Metrics, tracing, notifications |
| `hi_agent/auth/` | RBAC, JWT, SOC guard |
| `hi_agent/management/` | Operations, gates, SLOs, alerts, reconciliation |

## Quick Start

```bash
# Run a task via CLI
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# Start API server
python -m hi_agent serve --port 8080

# Resume a run from checkpoint
python -m hi_agent resume --checkpoint checkpoint_run-001.json

# Trigger memory Dream consolidation
curl -X POST http://localhost:8080/memory/dream

# Query knowledge
curl "http://localhost:8080/knowledge/query?q=revenue+trends&limit=5"

# Trigger skill evolution
curl -X POST http://localhost:8080/skills/evolve

# Run tests
python -m pytest tests/ -v
```

## Test Coverage

2067 tests, all passing. Zero external dependencies. 252 source modules, ~34k lines.

## System Overview

**hi-agent** is an enterprise-grade intelligent agent built around the **TRACE framework**:

```
TRACE = Task → Route → Act → Capture → Evolve
```

The three-repository architecture:

- `D:\chao_workspace\hi-agent` (this repo) — the sole intelligent agent, owns all cognitive logic + all decision logic (restart policy, reflection, graph scheduling)
- `D:\chao_workspace\agent-kernel` — durable runtime substrate (run lifecycle, event log, TurnEngine, idempotency, state tracking)
- `D:\chao_workspace\external\agent-core` — reusable capability modules integrated into hi-agent (tools, retrieval, MCP, workflows)

## Architecture Layers

```
Model-Driven Management
  ModelRegistry → TierRouter → ModelSelector (budget-aware)
  LLMGateway (sync) + AsyncLLMGateway (async/httpx)

Middleware Layer (independent contexts, ~86% cost reduction)
  Perception(light) → Control(medium) → Execution(dynamic) → Evaluation(light)
  5-phase lifecycle: pre_create → pre_execute → execute → post_execute → pre_destroy

Task Management (asyncio-native)
  AsyncTaskScheduler(Semaphore backpressure) → GraphFactory → BudgetGuard
  RestartPolicyEngine(retry/reflect/escalate) → ReflectionOrchestrator
  RunContext(per-run state isolation) → RunContextManager(concurrent runs)

Context OS
  ContextManager → Session → Memory(3-tier + AsyncCompressor) → Knowledge(wiki+graph) → Skill(evolution)

Execution Modes
  execute()        — linear stage traversal (backward compatible)
  execute_graph()  — dynamic graph traversal with backtrack + route selection
  execute_async()  — full asyncio with AsyncTaskScheduler + KernelFacade
```

## 10 First-Class Concepts

| Concept | Definition |
|---|---|
| **Task** | A formal task contract, not raw user input |
| **Run** | A durable long-running task execution entity |
| **Stage** | A formal phase in task progression |
| **Branch** | A logical trajectory in the exploration space |
| **Task View** | Minimal sufficient context rebuilt before each model call |
| **Action** | An external operation executed via Harness |
| **Memory** | What the agent has experienced — three tiers: short-term (session), mid-term (daily/dream), long-term (graph) |
| **Knowledge** | What the agent stably knows — wiki (text), user profile, knowledge graph (structured), four-layer retrieval |
| **Skill** | A reusable process unit with 5-stage lifecycle, version management, and evolution |
| **Feedback** | Optimization signals from results, evaluations, and experiments |

## Human Gate Types

- **Gate A** (`contract_correction`) — modify task contract mid-run
- **Gate B** (`route_direction`) — guide path selection
- **Gate C** (`artifact_review`) — review/edit outputs
- **Gate D** (`final_approval`) — gate high-risk final actions

## Standard Failure Codes

`missing_evidence`, `invalid_context`, `harness_denied`, `model_output_invalid`, `model_refusal`, `callback_timeout`, `no_progress`, `contradictory_evidence`, `unsafe_action_blocked`, `budget_exhausted`

## Engineering Gates (all passed)

| Gate | Description | Key Deliverables |
|------|-------------|------------------|
| 1. Async化 | asyncio foundation | AsyncTaskScheduler, EventBus, httpx gateway |
| 2. Kernel対接 | Real kernel integration | AsyncKernelFacadeAdapter, execute_turn() |
| 3. LLM接入 | Real LLM wiring | AsyncLLMGateway, HTTPGateway.complete(), AsyncMemoryCompressor |
| 4. 安全機構 | Safety mechanisms | AsyncCapabilityInvoker, runner exception protection, dead-end detection |
| 5. Graph駆動 | Graph-driven execution | execute_graph(), backtrack edges, multi-successor routing |
| 6. 並発隔離 | Concurrent run isolation | RunContext, RunContextManager, per-run state serialization |

## Key Design Documents

| Document | Location |
|----------|----------|
| Architecture design (V2.0) | `architecture-review/` |
| Parallel scalability design | `docs/superpowers/specs/2026-04-08-parallel-scalability-design.md` |
| Parallel scalability plan | `docs/superpowers/plans/2026-04-08-parallel-scalability.md` |
| Module evolution analysis | `docs/module-evolution-analysis.md` |
| Agent-kernel integration proposal | `docs/agent-kernel-integration-proposal.md` |
