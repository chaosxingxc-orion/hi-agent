# Architecture Reference

Extracted from CLAUDE.md for readability. These are stable facts about the codebase — not behavioral rules.

---

## System Overview

**TRACE = Task → Route → Act → Capture → Evolve**

| Package | Role |
|---------|------|
| `hi_agent/` (this repo) | Agent brain: all cognitive + decision logic |
| `agent_kernel/` (inlined, 2026-04-19) | Durable runtime: run lifecycle, event log, idempotency — HTTP endpoints are served by `hi_agent/server/app.py` and `hi_agent/server/routes_*.py` (Arch-7 decomposition, Wave 11) |
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

### Northbound API Facade (agent_server)

Detail: [`agent_server/ARCHITECTURE.md`](../agent_server/ARCHITECTURE.md)

| Module | Description |
|--------|-------------|
| `agent_server/contracts/` | Frozen v1 northbound schemas: `RunRequest`, `RunResponse`, `TenantContext`, `ContractError`, etc. |
| `agent_server/facade/` | `RunFacade`, `EventFacade`, `ArtifactFacade`, `ManifestFacade`, `IdempotencyFacade` — translate contract types to hi_agent callables |
| `agent_server/api/routes_runs.py` | `POST /v1/runs`, `GET /v1/runs/{id}`, `POST /v1/runs/{id}/signal` |
| `agent_server/api/routes_runs_extended.py` | `POST /v1/runs/{id}/cancel`, `GET /v1/runs/{id}/events` (SSE) |
| `agent_server/api/routes_artifacts.py` | `GET/POST /v1/artifacts`, `GET /v1/runs/{id}/artifacts` |
| `agent_server/api/routes_gates.py` | `POST /v1/gates/{id}/decide` |
| `agent_server/api/routes_manifest.py` | `GET /v1/manifest` |
| `agent_server/api/routes_skills_memory.py` | `POST /v1/skills`, `POST /v1/memory/write` |
| `agent_server/api/routes_mcp_tools.py` | `GET /v1/mcp/tools`, `POST /v1/mcp/tools/{name}` |
| `agent_server/api/middleware/` | `TenantContextMiddleware` + `IdempotencyMiddleware` |
| `agent_server/cli/` | `serve`, `run`, `cancel`, `tail-events` subcommands |

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

## Wave 28 Module Additions

| Module | Purpose |
|---|---|
| `scripts/run_arch_7x24.py` | Static 5-assertion architectural verification of 7x24 readiness — runs in seconds, replaces 24h wall-clock soak. Output: `docs/verification/<sha>-arch-7x24.json` |
| `docs/governance/score_caps.yaml` (refactored) | Single `architectural_seven_by_twenty_four` rule for the 7x24 tier; legacy `observability_spine_incomplete` and `chaos_non_runtime_coupled` caps retired |

## Wave 27 Module Additions

| Module | Purpose |
|---|---|
| `agent_server/` | Northbound API facade: versioned HTTP contract (v1 frozen), TDD-driven route handlers, 5 facades, idempotency + tenant middleware |
| `hi_agent/observability/event_emitter.py` | `RunEventEmitter` with 12 typed `record_*` methods for structured run event observability |
| `hi_agent/llm/tier_router.py` (extended) | `ingest_calibration_signal()` — active calibration that updates routing weights from quality signals |
| `hi_agent/evolve/postmortem.py` | `ProjectPostmortem` lifecycle integration with `on_project_completed` hook |
| `hi_agent/observability/alerts.py` | Alert wiring for recurrence-ledger operationally_observable entries |
| `hi_agent/artifacts/registry.py` (extended) | POST write-path for artifact creation via `agent_server` route |

## Wave 9 Module Additions

| Module | Purpose |
|---|---|
| `hi_agent/config/posture.py` | `Posture(StrEnum)` — dev/research/prod execution posture |
| `hi_agent/server/error_categories.py` | `ErrorCategory(StrEnum)` + `error_response()` for /runs structured errors |
| `hi_agent/contracts/team_runtime.py::TeamRunSpec` | Platform-neutral multi-agent team spec |
| `hi_agent/contracts/reasoning_trace.py` | `ReasoningTrace` + `ReasoningTraceEntry` schema |
| `hi_agent/cli_commands/init.py` | `hi-agent init --posture` scaffolding logic |
| `hi_agent/profiles/schema.json` | JSON Schema for profile validation (fail-closed under research/prod) |
| `hi_agent/templates/posture/` | Scaffold templates for dev/research/prod config dirs |

**CapabilityDescriptor unification (DF-50 closed):** canonical definition is `hi_agent/capability/registry.py::CapabilityDescriptor`. The `hi_agent/capability/adapters/descriptor_factory.py` is now a factory function (`build_capability_view`) that returns a dict from the canonical descriptor — it no longer defines a separate class.

**runtime_mode vs Posture:** `runtime_mode` (derived by `server/runtime_mode_resolver.py` from `HI_AGENT_ENV`) governs LLM routing and kernel connection. `Posture` (derived by `config/posture.py` from `HI_AGENT_POSTURE`) governs contract-spine enforcement and persistence durability. These are orthogonal: research posture + dev-smoke runtime_mode is valid (for a research team developing without a real LLM API key).

**Artifact extensibility:** `hi_agent/artifacts/contracts.py` contains only generic, domain-neutral artifact types (`Artifact`, `ResourceArtifact`, `DocumentArtifact`, `StructuredDataArtifact`, `EvidenceArtifact`, `EvaluationArtifact`, `DatasetArtifact`). Domain-specific artifact subclasses must live outside the platform. See `examples/research_overlay/artifacts.py` as the reference pattern for extending platform artifacts for a specific business domain.
