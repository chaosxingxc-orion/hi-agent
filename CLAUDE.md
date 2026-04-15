# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Language Rule

**Translate all instructions into English before any model call.** Never pass Chinese, Japanese, or other non-English text into an LLM prompt, tool argument, or task goal.

---

## Project Status

**Active implementation — production engineering phase.** All 6 engineering gates passed. Full design baseline at `architecture-review/` (V2.0).

---

## AI Engineering Rules

Six non-negotiable rules. No exceptions.

### Rule 1 — Think Before Coding
Surface assumptions, name confusion, state tradeoffs before writing a single line. If multiple valid interpretations exist, present them — never pick one silently. If the requirement is unclear, stop and ask.

### Rule 2 — Simplicity First
Minimum code that solves the problem. No speculative features, one-use abstractions, unrequested configurability, or impossible-scenario error handling. If 50 lines solve it, don't write 200.

### Rule 3 — Surgical Changes
Touch only what the task requires. Do not improve or reformat adjacent code. Match surrounding style exactly. Remove only imports/variables/functions that **your** change made unused — leave pre-existing dead code untouched.

### Rule 4 — Goal-Driven Execution
Convert vague instructions into falsifiable goals before starting. For multi-step tasks, publish a numbered plan with per-step verification criteria and confirm before executing. Do not proceed past a step until its verification passes.

### Rule 5 — Pre-Commit Systematic Inspection
Before every commit, audit every touched file across six dimensions:

| Dimension | Check |
|-----------|-------|
| **Contract truth** | No `pass`, `raise NotImplementedError`, or stub bodies. |
| **Orphan config** | Every parameter/config field/env var is consumed downstream. |
| **Orphan return values** | Every non-`None` return is consumed by the caller. |
| **Subsystem connectivity** | No broken wiring, missing DI, or unattached components. |
| **Driver–result alignment** | Every decision-driving field produces an observable effect. |
| **Error visibility** | No silent `except: pass` — every catch re-raises, logs, or converts to typed failure. |

Fix defects before committing. No "I'll fix it later."

### Rule 6 — Three-Layer Testing After Every Implementation
All three layers must be green before a feature is shipped:

- **Layer 1 — Unit**: one function/method per test; mock only external network calls or fault injection (document reason in docstring).
- **Layer 2 — Integration**: real components wired together, no internal mocking; skip with `@pytest.mark.skip(reason="awaiting real implementation")` if dependency is absent.
- **Layer 3 — E2E**: drive through the public interface (HTTP, CLI, top-level API); assert on observable outputs, not internal variables.

---

## First Principles

| | |
|---|---|
| **P1** | The agent must continuously evolve. |
| **P2** | The cost of driving the agent must continuously decrease. |
| **P3** | No Mock implementations in production — production integrity constraint. |

### Production Integrity Constraint (P3)

Using mocks to bypass real failures is **strictly forbidden**.

| Rule | Description |
|------|-------------|
| No mock bypass | Do not use Mock/Stub/Fake to conceal missing components or broken wiring. |
| Tests reflect reality | A passing test must mean the real path works. |
| Missing = exposed | Unimplemented dependencies → `skip`/`xfail`, never faked. |
| Legitimate mock uses | (1) external HTTP calls in unit tests; (2) fault injection; (3) performance benchmark stand-ins. Document reason in docstring. |
| Zero mocks in integration | Integration and E2E tests use real components only. |

---

## System Overview

**hi-agent** is an enterprise-grade intelligent agent built around the **TRACE** framework:

```
TRACE = Task → Route → Act → Capture → Evolve
```

Three-repository architecture:

| Repo | Role |
|------|------|
| `hi-agent` (this repo) | Agent brain: all cognitive + decision logic |
| `agent-kernel` | Durable runtime: run lifecycle, event log, idempotency |
| `agent-core` | Reusable capability modules: tools, retrieval, MCP |

### Architecture Layers

```
Model-Driven Management
  ModelRegistry → TierRouter (strong/medium/light) → ModelSelector (budget-aware)
  LLMGateway (sync) + AsyncLLMGateway (async/httpx)

Middleware Pipeline (~86% cost reduction via independent contexts)
  Perception(light) → Control(medium) → Execution(dynamic) → Evaluation(light)
  5-phase lifecycle: pre_create → pre_execute → execute → post_execute → pre_destroy

Task Management (asyncio-native)
  AsyncTaskScheduler(Semaphore) → GraphFactory → BudgetGuard
  RestartPolicyEngine(retry/reflect/escalate) → ReflectionOrchestrator
  RunContext(per-run isolation) → RunContextManager(concurrent runs)

Context OS
  ContextManager → Session → Memory(3-tier) → Knowledge(wiki+graph) → Skill(evolution)

Execution Modes
  execute()        — linear stage traversal
  execute_graph()  — dynamic graph with backtrack + multi-successor routing
  execute_async()  — full asyncio with AsyncTaskScheduler + KernelFacade
```

---

## Module Index

### Model-Driven Management
| Module | Description |
|--------|-------------|
| `hi_agent/llm/` | LLMGateway + AsyncLLMGateway, HttpLLMGateway (sync), HTTPGateway (async/httpx), AnthropicGateway, ModelRegistry, TierRouter, ModelSelector, budget tracker |

### Middleware
| Module | Description |
|--------|-------------|
| `hi_agent/middleware/` | Perception → Control → Execution → Evaluation; 5-phase lifecycle hooks; extensible MiddlewareOrchestrator (add/replace/remove, custom routes) |

### Task Management
| Module | Description |
|--------|-------------|
| `hi_agent/task_mgmt/` | AsyncTaskScheduler, BudgetGuard, RestartPolicyEngine, ReflectionOrchestrator, TaskMonitor, TaskHandle (8-state), PlanTypes (Sequential/Parallel/DAG/Speculative) |
| `hi_agent/trajectory/` | TrajectoryGraph (chain/tree/DAG/general), StageGraph, Superstep execution, conditional edges, Mermaid export |

### Context OS
| Module | Description |
|--------|-------------|
| `hi_agent/context/` | ContextManager (7-section budget, 4 thresholds, compression fallback chain), RunContext, RunContextManager |
| `hi_agent/session/` | RunSession (L0 JSONL, checkpoint save/resume), CostCalculator |
| `hi_agent/memory/` | L0 Raw → L1 STM → L2 MidTerm (Dream) → L3 LongTerm (graph); AsyncMemoryCompressor; MemoryLifecycleManager |
| `hi_agent/knowledge/` | Wiki (`[[wikilinks]]`), knowledge graph, four-layer retrieval (grep→BM25→graph→embedding), 6 API endpoints |
| `hi_agent/skill/` | SKILL.md format, SkillLoader (multi-source, token-budget binary search), SkillVersionManager (A/B), SkillEvolver, 7 API endpoints |

### TRACE Runtime
| Module | Description |
|--------|-------------|
| `hi_agent/runner.py` | RunExecutor: execute(), execute_graph(), execute_async(), resume(); SubRunHandle, SubRunResult, dispatch_subrun(), await_subrun(), register_gate(); dead-end detection; checkpoint resume; skill observation; LLM cost tracking |
| `hi_agent/contracts/` | TaskContract (13 fields, ACTIVE/PASSTHROUGH/QUEUE_ONLY annotations), PolicyVersionSet, CTSBudget |
| `hi_agent/route_engine/` | Rule / LLM / Hybrid / Skill-aware / Conditional routing; DecisionAuditStore |
| `hi_agent/task_view/` | TaskView builder, token budgets, auto-compress (snip→window→compress) |
| `hi_agent/config/` | TraceConfig (95+ params), SystemBuilder (full subsystem wiring) |

### Governance & Evolution
| Module | Description |
|--------|-------------|
| `hi_agent/harness/` | Dual-dimension governance (EffectClass + SideEffectClass), PermissionGate, EvidenceStore |
| `hi_agent/evolve/` | PostmortemAnalyzer, SkillExtractor, RegressionDetector, ChampionChallenger |
| `hi_agent/failures/` | FailureCode (11 codes, re-exported from agent-kernel TraceFailureCode), FailureCollector, ProgressWatchdog |
| `hi_agent/state_machine/` | Generic StateMachine + 6 TRACE definitions |

### Infrastructure
| Module | Description |
|--------|-------------|
| `hi_agent/server/` | HTTP API (20+ endpoints), EventBus, SSE streaming, RunManager, DreamScheduler |
| `hi_agent/runtime_adapter/` | 22-method RuntimeAdapter protocol; KernelFacadeAdapter (sync); AsyncKernelFacadeAdapter; ResilientKernelAdapter (retry + circuit breaker) |
| `hi_agent/capability/` | CapabilityRegistry; CapabilityInvoker (timeout+retry); AsyncCapabilityInvoker; CircuitBreaker |
| `hi_agent/observability/` | MetricsCollector, tracing, notifications |
| `hi_agent/auth/` | RBAC, JWT, SOC guard |
| `hi_agent/mcp/` | MCPServer, MCPHealth, MCPBinding; StdioMCPTransport + MultiStdioTransport (transport_status: not_wired until plugin registers mcp_servers) |
| `hi_agent/executor_facade.py` | RunExecutorFacade (start/run/stop), RunFacadeResult, check_readiness(), ReadinessReport |
| `hi_agent/gate_protocol.py` | GateEvent dataclass (gate_id, gate_type, phase_name, recommendation, output_summary, opened_at) |

---

## 10 First-Class Concepts

| Concept | Definition |
|---------|------------|
| **Task** | Formal task contract (13 fields), not raw user input |
| **Run** | Durable long-running execution entity |
| **Stage** | Formal phase in TRACE progression |
| **Branch** | Logical trajectory in exploration space |
| **Task View** | Minimal sufficient context rebuilt before each model call |
| **Action** | External operation executed via Harness |
| **Memory** | Agent experience: short-term (session) → mid-term (dream) → long-term (graph) |
| **Knowledge** | Stable facts: wiki + knowledge graph + four-layer retrieval |
| **Skill** | Reusable process unit: 5-stage lifecycle, A/B versioning, textual gradient evolution |
| **Feedback** | Optimization signals from results, evaluations, and experiments |

---

## Contract Field Consumption

TaskContract fields are annotated with consumption level:

| Level | Meaning |
|-------|---------|
| `ACTIVE` | Drives execution behavior in the default TRACE pipeline |
| `PASSTHROUGH` | Stored and returned; consumption is the business agent's responsibility |
| `QUEUE_ONLY` | Used for scheduling only; not consumed during stage execution |

Fields: `goal`, `task_family`, `risk_level`, `constraints`, `acceptance_criteria`, `budget`, `deadline`, `profile_id`, `decomposition_strategy` → **ACTIVE**  
`environment_scope`, `input_refs`, `parent_task_id` → **PASSTHROUGH**  
`priority` → **QUEUE_ONLY**

---

## Human Gate Types

| Gate | Trigger |
|------|---------|
| **A** `contract_correction` | Modify task contract mid-run |
| **B** `route_direction` | Guide path selection |
| **C** `artifact_review` | Review/edit outputs |
| **D** `final_approval` | Gate high-risk final actions |

## Standard Failure Codes

`missing_evidence` · `invalid_context` · `harness_denied` · `model_output_invalid` · `model_refusal` · `callback_timeout` · `no_progress` · `contradictory_evidence` · `unsafe_action_blocked` · `exploration_budget_exhausted` · `execution_budget_exhausted`

Defined in agent-kernel as `TraceFailureCode` (StrEnum); re-exported as `hi_agent.failures.taxonomy.FailureCode`.

---

## Quick Start

```bash
# Local execution
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# Full contract fields (CLI parity with server)
python -m hi_agent run --goal "Analyze data" --local \
  --risk-level low --task-family quick_task \
  --acceptance-criteria '["required_stage:synthesize"]' \
  --constraints '["no_external_calls"]' \
  --deadline "2099-12-31T23:59:59Z" \
  --budget '{"max_llm_calls": 10}'

# Start API server
python -m hi_agent serve --port 8080

# Resume from checkpoint
python -m hi_agent resume --checkpoint .checkpoint/checkpoint_run-001.json

# Run tests
python -m pytest tests/ -v          # 2878 tests
python -m ruff check .              # lint
```

---

## Release Quality Protocol

Engineering checks (tests + lint) are necessary but **not sufficient**. A customer-perspective E2E verification must also pass.

**Minimum verification path** (every release):

```bash
# 1. Start server
python -m hi_agent serve --port 8080

# 2. Submit a real task
curl -s -X POST http://localhost:8080/runs \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarize the TRACE framework in one paragraph"}' | jq .run_id

# 3. Poll until terminal
curl -s http://localhost:8080/runs/{run_id} | jq '{state, result}'

# 4. Verify: result is readable, no crash, no dirty state
# 5. Submit same task again — confirm no duplicate run_id
```

**Pass/Fail criteria:**

| Observation | Result |
|-------------|--------|
| POST /runs → 201, state reaches `completed` or `failed` | Pass |
| Any step returns 5xx or process crashes | **Fail** |
| Duplicate run_id on second submit | **Fail** |
| Uncaught exception in logs | **Fail** |

---

## Engineering Gates (all passed)

| Gate | Deliverables |
|------|-------------|
| 1. Async foundation | AsyncTaskScheduler, EventBus, httpx gateway |
| 2. Kernel integration | AsyncKernelFacadeAdapter, execute_turn() |
| 3. LLM wiring | AsyncLLMGateway, HTTPGateway.complete(), AsyncMemoryCompressor |
| 4. Safety mechanisms | AsyncCapabilityInvoker, dead-end detection, exception protection |
| 5. Graph-driven execution | execute_graph(), backtrack edges, multi-successor routing |
| 6. Concurrent isolation | RunContext, RunContextManager, per-run state serialization |

---

## Test Coverage

**2878 tests, all passing.** One external dependency: `agent-kernel` (via GitHub). 252 source modules, ~34k lines.

---

## Key Design Documents

| Document | Location |
|----------|----------|
| Architecture design (V2.0) | `architecture-review/` |
| Parallel scalability design | `docs/superpowers/specs/2026-04-08-parallel-scalability-design.md` |
| Module evolution analysis | `docs/module-evolution-analysis.md` |
| Agent-kernel integration proposal | `docs/agent-kernel-integration-proposal.md` |
