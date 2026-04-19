# CLAUDE.md

## Language Rule

**Translate all instructions into English before any model call.** Never pass Chinese, Japanese, or other non-English text into an LLM prompt, tool argument, or task goal.

---

## Project Status

**Active implementation — production engineering phase.** Full design baseline at `architecture-review/`.

---

## AI Engineering Rules

Eight non-negotiable rules. No exceptions.

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
| **HTTP path truth** | Every `_http_post(path)` / `_http_get(path)` in `kernel_facade_client.py` matches a `Route(path, method)` in `agent_kernel/service/http_server.py`. Enumerate all endpoints side-by-side in the PR description. |
| **ID uniqueness** | Runtime identifiers (`run_id`, `stage_id`, `branch_id`) come from the caller or are generated via `uuid.uuid4()`. Fallback to semantic labels (`run_kind`, `'default'`, `'trace'`) as an ID is forbidden. |

Fix defects before committing. No "I'll fix it later."

### Rule 6 — Three-Layer Testing After Every Implementation
All three layers must be green before a feature is shipped:

- **Layer 1 — Unit**: one function/method per test; mock only external network calls or fault injection (document reason in docstring).
- **Layer 2 — Integration**: real components wired together, no internal mocking; skip with `@pytest.mark.skip(reason="awaiting real implementation")` if dependency is absent.
- **Layer 3 — E2E**: drive through the public interface (HTTP, CLI, top-level API); assert on observable outputs, not internal variables.

### Rule 7 — Kernel HTTP Contract Lock

`agent_kernel/service/http_server.py` is the **single authority** for all endpoint definitions.  
`hi_agent/runtime_adapter/kernel_facade_client.py` is the **single HTTP client** for those endpoints.

**When either file changes, both must be audited together in the same commit:**

1. Produce a side-by-side table for every kernel operation:

   | Operation | Client call (path · method · body fields) | Server Route (path · method) | Match? |
   |-----------|------------------------------------------|------------------------------|--------|
   | `start_run` | `POST /runs · {run_kind, input_json}` | `POST /runs` | ✅ |
   | … | … | … | … |

2. Every row must be ✅. Any ❌ is a blocker — fix before merging.

3. If a server route is added or renamed, the client must be updated **in the same PR**. Split PRs that leave client/server out of sync are rejected.

**Incident record** (why this rule exists):
- 2026-04-19: `POST /runs/start` (wrong) vs `POST /runs` (actual); `POST /runs/spawn_child` vs `POST /runs/{run_id}/children`; `POST /stages/open` vs `POST /runs/{run_id}/stages/open` — caused 100% POST /runs failure on downstream deploy. Client was written against a draft spec and never cross-verified against the live Route table.

### Rule 8 — Downstream Delivery Gate

Before any package (zip / pip / docker image) is delivered to a downstream system, the following smoke test **must pass** in a clean environment (Python 3.12, empty `.hi_agent/`):

```bash
# Step 1 — import gate (catches syntax errors, BOM, missing deps)
python -c "import hi_agent; import agent_kernel"

# Step 2 — sequential run creation (catches hardcoded ID bugs)
for i in 1 2 3; do
  curl -sf -X POST http://127.0.0.1:8080/runs \
    -H 'Content-Type: application/json' \
    -d "{\"goal\":\"smoke $i\",\"task_family\":\"quick_task\",\"risk_level\":\"low\"}" \
    | jq -c '{run_id, state}'
done
# Assert: 3 distinct run_ids, all HTTP 200/201

# Step 3 — run-to-terminal (catches path mismatch, stuck-running bugs)
RUN_ID=$(curl -sf -X POST http://127.0.0.1:8080/runs \
  -H 'Content-Type: application/json' \
  -d '{"goal":"smoke final","task_family":"quick_task","risk_level":"low"}' | jq -r .run_id)
for i in $(seq 1 30); do
  STATE=$(curl -sf http://127.0.0.1:8080/runs/$RUN_ID | jq -r .state)
  [ "$STATE" = "done" -o "$STATE" = "failed" ] && echo "OK: $STATE" && break
  sleep 2
done
```

**Pass criteria — all three must hold:**
- Step 1 exits 0 with no error output
- Step 2 produces 3 distinct `run_id` values, no 4xx/5xx
- Step 3 reaches `done` or `failed` within 60 s; error log shows no 404/405/400/duplicate

**Incident record** (why this rule exists):
- 2026-04-11: Step 1 failed (17× Python 2 `except A, B:` syntax + 12× UTF-8 BOM).
- 2026-04-19: Step 1 passed but Steps 2–3 failed (`/runs/start` 405; duplicate `run_id='default'`).

---

## Production Integrity (P3)

No Mock implementations in production. Using mocks to bypass real failures is **strictly forbidden**.

| Rule | Detail |
|------|--------|
| No mock bypass | Do not use Mock/Stub/Fake to conceal missing components or broken wiring. |
| Tests reflect reality | A passing test must mean the real path works. |
| Missing = exposed | Unimplemented dependencies → `skip`/`xfail`, never faked. |
| Legitimate mock uses | (1) external HTTP calls in unit tests; (2) fault injection; (3) performance benchmarks. Document reason in docstring. |
| Zero mocks in integration | Integration and E2E tests use real components only. |

---

## System Overview

**TRACE = Task → Route → Act → Capture → Evolve**

| Package | Role |
|---------|------|
| `hi_agent/` (this repo) | Agent brain: all cognitive + decision logic |
| `agent_kernel/` (inlined, 2026-04-19) | Durable runtime: run lifecycle, event log, idempotency — source of truth for HTTP endpoints is `agent_kernel/service/http_server.py` |
| `agent-core` | Reusable capability modules: tools, retrieval, MCP |

Execution modes: `execute()` linear · `execute_graph()` DAG with backtrack · `execute_async()` full asyncio.  
Middleware: Perception(light) → Control(medium) → Execution(dynamic) → Evaluation(light); ~86% cost reduction via independent contexts.

---

## Module Index

### Model-Driven Management
| Module | Description |
|--------|-------------|
| `hi_agent/llm/` | LLMGateway + AsyncLLMGateway, ModelRegistry, TierRouter, ModelSelector, budget tracker |

### Middleware
| Module | Description |
|--------|-------------|
| `hi_agent/middleware/` | Perception → Control → Execution → Evaluation; 5-phase lifecycle hooks; MiddlewareOrchestrator |

### Task Management
| Module | Description |
|--------|-------------|
| `hi_agent/task_mgmt/` | AsyncTaskScheduler, BudgetGuard, RestartPolicyEngine (`reflect(N)` injects reflection prompt before each retry), ReflectionOrchestrator, TaskMonitor, TaskHandle (8-state), PlanTypes |
| `hi_agent/trajectory/` | TrajectoryGraph (chain/tree/DAG/general), StageGraph, Superstep execution, conditional edges |

### Context OS
| Module | Description |
|--------|-------------|
| `hi_agent/context/` | ContextManager (7-section budget, 4 thresholds, compression fallback chain), RunContext, RunContextManager |
| `hi_agent/session/` | RunSession (L0 JSONL, checkpoint save/resume), CostCalculator |
| `hi_agent/memory/` | L0 Raw → L1 STM → L2 MidTerm (Dream) → L3 LongTerm (graph, TF-IDF, auto-load); L0Summarizer; AsyncMemoryCompressor; MemoryLifecycleManager |
| `hi_agent/knowledge/` | Wiki (`[[wikilinks]]`), knowledge graph, four-layer retrieval (grep→BM25→graph→embedding), 6 API endpoints |
| `hi_agent/skill/` | SKILL.md format, SkillLoader (multi-source, token-budget binary search), SkillVersionManager (A/B), SkillEvolver, 7 API endpoints |

### TRACE Runtime
| Module | Description |
|--------|-------------|
| `hi_agent/runner.py` | RunExecutor: execute(), execute_graph(), execute_async(), resume(); dispatch_subrun(goal=), await_subrun(), register_gate(); gate blocking (GatePendingError); reflection_prompt injection; `_finalize_run` triggers L0→L2→L3 memory chain + raw_memory.close(); dead-end detection; checkpoint resume; LLM cost tracking |
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
| `hi_agent/gate_protocol.py` | GateEvent dataclass (gate_id, gate_type, phase_name, recommendation, output_summary, opened_at); GatePendingError (carries `gate_id` attribute) |
| `hi_agent/llm/tier_presets.py` | `apply_research_defaults(tier_router)` — research-optimized TierRouter preset |

---

## Key Concepts

| Concept | Definition |
|---------|------------|
| **Task** | Formal task contract (13 fields), not raw user input |
| **Task View** | Minimal sufficient context rebuilt before each model call |
| **Action** | External operation executed via Harness |
| **Memory** | Agent experience: short-term (session) → mid-term (dream) → long-term (graph) |
| **Knowledge** | Stable facts: wiki + knowledge graph + four-layer retrieval |
| **Skill** | Reusable process unit: 5-stage lifecycle, A/B versioning, textual gradient evolution |
| **Feedback** | Optimization signals from results, evaluations, and experiments |

---

## Contract Field Consumption

| Level | Meaning |
|-------|---------|
| `ACTIVE` | Drives execution behavior in the default TRACE pipeline |
| `PASSTHROUGH` | Stored and returned; consumption is the business agent's responsibility |
| `QUEUE_ONLY` | Used for scheduling only; not consumed during stage execution |

`goal`, `task_family`, `risk_level`, `constraints`, `acceptance_criteria`, `budget`, `deadline`, `profile_id`, `decomposition_strategy` → **ACTIVE**  
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

Defined as `hi_agent.failures.taxonomy.FailureCode` (StrEnum).

---

## Quick Start

```bash
python -m hi_agent run --goal "Analyze quarterly revenue data" --local
python -m hi_agent serve --port 8080
python -m hi_agent resume --checkpoint .checkpoint/checkpoint_run-001.json
python -m pytest tests/ -v
python -m ruff check .
```
