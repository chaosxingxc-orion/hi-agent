# Architecture Reference

Extracted from CLAUDE.md for readability. These are stable facts about the codebase — not behavioral rules.

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
