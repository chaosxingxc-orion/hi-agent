# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Highest Principle — Language

**Before calling any model, translate all input instructions into English.**

Regardless of the language the user writes in, the instruction passed to the model must be in English. This applies to task goals, prompts, tool arguments, and any text that will be processed by an LLM. Do not pass Chinese, Japanese, or any other non-English text directly into a model call.

---

## Project Status

This repository is in **active implementation — production engineering phase**. All 6 engineering gates passed. The `architecture-review/` directory contains the full design baseline (V2.0).

## AI Engineering Behavior

Six non-negotiable rules for every task. No exceptions, no shortcuts.

---

### Rule 1 — Think Before Coding

**Surface assumptions. Name confusion. State tradeoffs.**

Before writing a single line:
- Write down your assumptions explicitly. If uncertain, ask first.
- If multiple valid interpretations exist, present them — never pick one silently.
- If a simpler approach exists, propose it and push back when warranted.
- If the requirement is unclear, stop and name exactly what is confusing.

Diving in without clarity wastes more time than asking upfront.

---

### Rule 2 — Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was explicitly asked.
- No abstractions for code that is only used once.
- No added "flexibility" or "configurability" that wasn't requested.
- No error handling for scenarios that cannot happen.
- If 50 lines solve it, don't write 200.

Test: would a senior engineer call this overcomplicated? If yes, cut it down.

---

### Rule 3 — Surgical Changes

**Touch only what the task requires. Clean up only your own mess.**

When modifying existing code:
- Do not improve, reformat, or rename things adjacent to your change.
- Do not refactor code that isn't broken.
- Match the surrounding style exactly, even if you'd write it differently.
- If you spot unrelated dead code, call it out in a comment — don't delete it.

When your changes leave orphans:
- Remove any import, variable, or function that YOUR change made unused.
- Leave pre-existing dead code untouched unless removal was explicitly requested.

Test: every changed line must trace directly back to the user's request.

---

### Rule 4 — Goal-Driven Execution

**Translate tasks into verifiable success criteria before starting.**

Convert vague instructions into falsifiable goals:
- "Add validation" → "Tests for invalid inputs pass; valid inputs still work."
- "Fix the bug" → "A test that reproduces the bug now passes."
- "Refactor X" → "All tests pass before and after; behavior is identical."

For multi-step tasks, publish the plan first and confirm before executing:
```
1. [Step] → verify: [how you will confirm it worked]
2. [Step] → verify: [how you will confirm it worked]
3. [Step] → verify: [how you will confirm it worked]
```

Do not proceed past a step until its verification passes.

---

### Rule 5 — Pre-Commit Systematic Inspection

**Before every commit, audit the change set for structural defects.**

Run the following six-dimension inspection on every file you touched:

| Dimension | What to check |
|-----------|--------------|
| **Contract truth** | Every declared interface, method signature, and protocol method is fully implemented — no `pass`, `raise NotImplementedError`, or stub body masquerading as real logic. |
| **Orphan config / parameters** | Every constructor parameter, config field, and environment variable is read by at least one downstream consumer. Parameters that are accepted but never used are dead weight and must be removed or wired up. |
| **Orphan return values** | Every non-`None` return value is consumed by the caller. Functions that compute a result and discard it silently are logic errors waiting to surface. |
| **Subsystem connectivity** | Trace the call graph from entry point to each subsystem you modified. Confirm there are no broken links — missing wiring, forgotten dependency injection, or components that are instantiated but never attached. |
| **Driver–result alignment** | For every input parameter or internal computation that drives a decision, verify the decision outcome is actually returned, stored, or acted upon. A field that changes internal state but whose effect is never observable is a silent no-op. |
| **Error visibility** | Every exception catch either re-raises, logs with full context, or converts to a typed failure. Silent `except: pass` blocks hide bugs. |

If any dimension reveals a defect, fix it before committing. Do not rationalize "I'll fix it later."

---

### Rule 6 — Three-Layer Testing After Every Implementation

**Unit tests are necessary but not sufficient. Run all three layers.**

After implementing any feature or fix, complete the full testing stack in order:

**Layer 1 — Unit tests**
- Cover the new logic in isolation.
- Each test targets one function or class method.
- Mocking is only allowed for external network calls or fault injection. Document the reason in the docstring.

**Layer 2 — Integration tests**
- Verify that the new code is reachable from its real callers through the real call chain.
- No mocking of internal modules. Instantiate real components and wire them together.
- Confirm the feature produces its side effects (state changes, events emitted, records written).
- If a real dependency is not yet available, mark the test `@pytest.mark.skip(reason="awaiting real implementation")` — never fake it.

**Layer 3 — End-to-end tests**
- Simulate how a real user or upstream system would invoke this capability.
- Design the scenario by asking: *"What would someone do the first time they tried to use this?"*
- Drive the system through its public interface (HTTP endpoints, CLI, or the top-level Python API).
- Assert on observable outputs: response bodies, persisted state, emitted events — not on internal variables.

A feature that passes only unit tests is not shipped. All three layers must be green.

---

## First Principles

- **P1**: The agent must continuously evolve
- **P2**: The cost of driving the agent must continuously decrease
- **P3**: No Mock implementations allowed — production integrity constraint

## Production Integrity Constraint (P3)

This project is in production. **Using any Mock implementation to bypass real failures in order to make tests pass is strictly forbidden.**

| Rule | Description |
|------|-------------|
| **No mock bypass** | Do not use Mock/Stub/Fake implementations to conceal missing real components, misaligned interfaces, or unconnected dependencies. |
| **Tests must reflect reality** | A passing test must mean the real execution path works — not that a mocked path works. |
| **Missing means exposed** | If a component is not yet implemented (e.g. a real tool backend, MCP transport), mark the test `@pytest.mark.skip(reason="awaiting real implementation")` or `xfail` — do not disguise it as passing with a mock. |
| **Legitimate mock uses** | Only: (1) unit tests isolating external network services (e.g. HTTP API calls); (2) fault injection for error-handling tests; (3) controlled stand-ins in performance benchmarks. All such cases must document the mock reason in the test docstring. |
| **Zero mocks in integration tests** | Integration and end-to-end tests must use real components. No internal module may be mocked. |

> **Principle**: A test that passes via mocks does not mean the system works. Only real paths running green counts as passing.

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

2814 tests, all passing. One external dependency: `agent-kernel` (via GitHub). 252 source modules, ~34k lines.

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

After each release, passing engineering-craft checks (unit tests, linting, interface alignment) is a necessary condition but not sufficient. A **customer-perspective end-to-end verification** must also pass before a release is considered ready.

### Verification Order

1. **Engineering gate** — all unit tests green, no lint errors, interface contracts aligned
2. **Customer-perspective gate** — stand in the shoes of a real user; design and run end-to-end usage scenarios

### Customer-Perspective Gate: Standard Practice

When designing scenarios, always ask: **"What would someone do the very first time they picked up this system?"**

Minimum verification path (must run on every release):

```bash
# 1. Start the server
python -m hi_agent serve --port 8080

# 2. Submit a real task
curl -s -X POST http://localhost:8080/runs \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarize the TRACE framework in one paragraph"}' \
  | jq .run_id

# 3. Poll until state=done (or failed)
curl -s http://localhost:8080/runs/{run_id} | jq '{state, result}'

# 4. Verify: result is readable, no crash, no dirty state left behind

# 5. Submit the same task a second time (verify no duplicate run_id, no state pollution)
```

Extended scenarios (run as needed per module):

- **Failure recovery**: Submit a task that is guaranteed to fail; confirm the retry/abort path works and the server does not crash.
- **Concurrency**: Submit 3 tasks simultaneously; confirm they are isolated and do not interfere with each other.
- **Memory/Knowledge**: After submitting a task, query `/memory/dream` and `/knowledge/query`; confirm data is persisted.
- **Skill evolution**: Call `/skills/evolve`; confirm no exceptions are raised.

### Pass/Fail Criteria

| Observation | Result |
|-------------|--------|
| POST /runs → 200, GET /runs/{id} → state=done | ✅ Pass |
| Any step returns 5xx or process crashes | ❌ Fail — do not release |
| Second identical task triggers duplicate run_id | ❌ Fail |
| Logs contain an uncaught exception | ❌ Fail |

> **Principle**: Passing a boot test does not mean the system is usable. Only a real execution path running to completion counts as passing.

## Engineering Gates (all passed)

| Gate | Description | Key Deliverables |
|------|-------------|------------------|
| 1. Async foundation | asyncio foundation | AsyncTaskScheduler, EventBus, httpx gateway |
| 2. Kernel integration | Real kernel integration | AsyncKernelFacadeAdapter, execute_turn() |
| 3. LLM wiring | Real LLM wiring | AsyncLLMGateway, HTTPGateway.complete(), AsyncMemoryCompressor |
| 4. Safety mechanisms | Safety mechanisms | AsyncCapabilityInvoker, runner exception protection, dead-end detection |
| 5. Graph-driven execution | Graph-driven execution | execute_graph(), backtrack edges, multi-successor routing |
| 6. Concurrent isolation | Concurrent run isolation | RunContext, RunContextManager, per-run state serialization |

## Key Design Documents

| Document | Location |
|----------|----------|
| Architecture design (V2.0) | `architecture-review/` |
| Parallel scalability design | `docs/superpowers/specs/2026-04-08-parallel-scalability-design.md` |
| Parallel scalability plan | `docs/superpowers/plans/2026-04-08-parallel-scalability.md` |
| Module evolution analysis | `docs/module-evolution-analysis.md` |
| Agent-kernel integration proposal | `docs/agent-kernel-integration-proposal.md` |
