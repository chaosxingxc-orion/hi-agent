# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repository is in **active implementation — production engineering phase**. All 6 engineering gates passed. The `architecture-review/` directory contains the full design baseline (V2.0).

## First Principles

- **P1**: The agent must continuously evolve
- **P2**: The cost of driving the agent must continuously decrease
- **P3**: No Mock implementations allowed — production integrity constraint

## Production Integrity Constraint (P3)

本项目已进入生产态。**严禁使用任何 Mock 实现来规避问题以达到测试通过的标准。**

具体要求：

| 规则 | 说明 |
|------|------|
| **禁止 Mock 绕过** | 不得通过 Mock/Stub/Fake 实现来掩盖真实组件缺失、接口未对齐、依赖未连通等问题 |
| **测试必须反映真实** | 测试通过必须代表真实执行路径可用，而非 Mock 路径可用 |
| **缺失即暴露** | 如果某个组件尚未实现（如真实工具后端、MCP transport），测试应明确标记为 `@pytest.mark.skip(reason="awaiting real implementation")` 或 `xfail`，而非用 Mock 伪装通过 |
| **Mock 的合法用途** | 仅限于：(1) 隔离外部网络服务（如 HTTP API 调用）的单元测试 (2) 测试错误处理路径时注入故障 (3) 性能基准测试中的受控替身。这些场景必须在测试 docstring 中标注 Mock 理由 |
| **集成测试零 Mock** | 集成测试和端到端测试必须使用真实组件，不得 Mock 任何内部模块 |

> **原则**：Mock 通过的测试 ≠ 系统可用。只有真实路径跑通，才算通过。

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
| `hi_agent/failures/` | FailureCode re-exported from agent-kernel TraceFailureCode (11 codes), FAILURE_RECOVERY_MAP/GATE_MAP (hi-agent mappings), FailureCollector, ProgressWatchdog, typed exceptions |
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
python -m hi_agent resume --checkpoint .checkpoint/checkpoint_run-001.json

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

2067 tests, all passing. One external dependency: `agent-kernel` (via GitHub). 252 source modules, ~34k lines.

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

`missing_evidence`, `invalid_context`, `harness_denied`, `model_output_invalid`, `model_refusal`, `callback_timeout`, `no_progress`, `contradictory_evidence`, `unsafe_action_blocked`, `exploration_budget_exhausted`, `execution_budget_exhausted`

Defined in agent-kernel as `TraceFailureCode` (StrEnum), re-exported by `hi_agent.failures.taxonomy` as `FailureCode`.

## Release Quality Protocol

每个版本完成后，工程工艺验证（单元测试、语法检查、接口对齐）只是必要条件，不是充分条件。还必须完成**客户视角端到端验证**，才能认定版本可用。

### 验证顺序

1. **工程工艺门** — 单元测试全绿、语法检查无误、接口协议对齐
2. **客户视角门** — 站在真实使用者的立场，设计端到端使用场景并跑通

### 客户视角门的标准做法

设计场景时必须问：**"一个刚拿到这个系统的人，第一件事会怎么做？"**

最小验证路径（每次发版必跑）：

```bash
# 1. 启动服务
python -m hi_agent serve --port 8080

# 2. 提交一个真实任务
curl -s -X POST http://localhost:8080/runs \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarize the TRACE framework in one paragraph"}' \
  | jq .run_id

# 3. 轮询直到 state=done（或 failed）
curl -s http://localhost:8080/runs/{run_id} | jq '{state, result}'

# 4. 验证结果可读、无崩溃、无脏状态残留

# 5. 第二次提交同一任务（验证无 duplicate run_id、无状态污染）
```

扩展场景（按功能模块按需选跑）：

- **失败恢复**：提交一个必然失败的任务，确认 retry/abort 路径正常，服务不崩
- **并发**：同时提交 3 个任务，确认彼此隔离、互不干扰
- **Memory/Knowledge**：提交任务后查询 `/memory/dream`、`/knowledge/query`，确认数据落盘
- **Skill 演化**：调用 `/skills/evolve`，确认无异常

### 判定标准

| 现象 | 判定 |
|------|------|
| POST /runs → 200，GET /runs/{id} → state=done | ✅ 通过 |
| 任意一步返回 5xx 或进程崩溃 | ❌ 不通过，不得发版 |
| 第二次同任务触发 duplicate run_id | ❌ 不通过 |
| 日志出现未捕获异常 | ❌ 不通过 |

> **原则**：boot 测试通过 ≠ 可用。只有真实执行路径跑通，才算通过。

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
