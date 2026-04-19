# ARCHITECTURE: hi-agent (L1 Detail)

> **Architecture hierarchy**
> - L0 system boundary: [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
> - L1 hi-agent detail: this file
> - L1 agent-kernel detail: [`../agent_kernel/ARCHITECTURE.md`](../agent_kernel/ARCHITECTURE.md)

## Refresh Notes (2026-04-19 — Workspace Isolation update)

- Updated quality-gate verification snapshot to `3858 passed, 13 skipped, 0 failures`.
- Added Workspace Isolation (§25): WorkspaceKey/WorkspacePathHelper, SessionStore/SessionMiddleware, RunManager workspace enforcement, workspace-scoped memory paths (L0–L3 + checkpoints), TeamEventStore, TeamSpace.publish(), GET /team/events, opt-in RunFinalizer auto-sync, acceptance tests 1–20.
- Preserved W13 security hardening (§23): GovernedToolExecutor, CapabilityDescriptor risk metadata, PathPolicy, URLPolicy, auth posture degraded signal, shell_exec prod-default-disabled, FallbackTaxonomy, ToolCallAuditEvent, JSON-backed RetrievalEngine cache.
- Preserved W13 engineering quality (§24): AsyncBridgeService, HttpLLMGateway deprecation, ContextManager section cache, RetrievalEngine index governance, routes_tools_mcp extraction, public API surface cleanup (snapshot/iter_nodes/stats/set_context_provider), memory store manifest index, SqliteEvidenceStore batch API.
- Preserved W1–W12 sprint deliverables: §13 ExecutionProvenance, §14 Evolve Tri-State Policy, §15 RBAC/SOC Auth, §16 SystemBuilder Sub-Builder Split, §17 StageOrchestrator Extraction, §18 Capability Governance, §19 Audit & Observability, §20 MCP Schema Drift & Restart Backoff, §21 ProfileDirectoryManager & Config Stack, §22 Release Gate & Runbooks.

本文档描述 `hi-agent` 当前代码实现（as-is），涵盖分层架构视图、接口关系、使用关系、时序图与数据流图。  
所有图表均基于代码实际实现，与工程实现严格对齐。

---

## 1. 系统边界

```text
hi-agent (agent brain / orchestration)
  ├─ agent-kernel (durable runtime substrate)
  └─ agent-core   (capability ecosystem)
```

| 仓库 | 职责 |
|------|------|
| `hi-agent` | 智能体大脑：任务理解、路由决策、执行编排、记忆/知识/技能、持续进化 |
| `agent-kernel` | 持久化运行时：run 生命周期、事件事实、幂等与恢复治理 |
| `agent-core` | 通用能力模块：工具、检索、MCP 等（agent-core 集成到 hi-agent） |

---

## 2. 分层架构视图（含全组件标注）

```mermaid
graph TB
  subgraph API["API & CLI Layer"]
    CLI["CLI<br/>hi_agent/__main__.py"]
    SRV["HTTP Server<br/>server/app.py"]
    RLM["RunManager<br/>server/run_manager.py"]
    EBUS["EventBus<br/>server/event_bus.py"]
    DSCH["DreamScheduler<br/>server/dream_scheduler.py"]
    RLIM["RateLimiter<br/>server/rate_limiter.py"]
  end

  subgraph EXEC["Execution Layer"]
    REXEC["RunExecutor<br/>runner.py"]
    STORCH["StageOrchestrator<br/>execution/stage_orchestrator.py"]
    STAGE["StageExecutor<br/>runner_stage.py"]
    LIFE["RunLifecycle<br/>runner_lifecycle.py"]
    TELE["RunTelemetry<br/>runner_telemetry.py"]
    PROV["ExecutionProvenance<br/>contracts/execution_provenance.py"]
    RMRES["RuntimeModeResolver<br/>server/runtime_mode_resolver.py"]
  end

  subgraph MW["Middleware Pipeline"]
    MWORCH["MiddlewareOrchestrator<br/>middleware/orchestrator.py"]
    PERC["PerceptionMiddleware<br/>middleware/perception.py"]
    CTRL["ControlMiddleware<br/>middleware/control.py"]
    EXMW["ExecutionMiddleware<br/>middleware/execution.py"]
    EVAL["EvaluationMiddleware<br/>middleware/evaluation.py"]
    HOOKS["HookSystem<br/>middleware/hooks.py"]
  end

  subgraph ROUTE["Route Engine"]
    HROUT["HybridRouteEngine<br/>route_engine/hybrid_engine.py"]
    RROUT["RuleRouteEngine<br/>route_engine/rule_engine.py"]
    LROUT["LLMRouteEngine<br/>route_engine/llm_engine.py"]
    SROUT["SkillAwareRouteEngine<br/>route_engine/skill_aware_engine.py"]
    DACIT["DecisionAuditStore<br/>route_engine/decision_audit.py"]
    ACCP["AcceptancePolicy<br/>route_engine/acceptance.py"]
  end

  subgraph HARN["Harness & Governance"]
    HEXEC["HarnessExecutor<br/>harness/executor.py"]
    GOV["GovernanceEngine<br/>harness/governance.py"]
    PERM["PermissionGate<br/>harness/permission_rules.py"]
    EVID["EvidenceStore<br/>harness/evidence_store.py"]
  end

  subgraph TASKMGMT["Task Management"]
    TSCH["TaskScheduler<br/>task_mgmt/scheduler.py"]
    ATSCH["AsyncTaskScheduler<br/>task_mgmt/async_scheduler.py"]
    THND["TaskHandle<br/>task_mgmt/handle.py"]
    BGRD["BudgetGuard<br/>task_mgmt/budget_guard.py"]
    RPOL["RestartPolicyEngine<br/>task_mgmt/restart_policy.py"]
    REFL["ReflectionOrchestrator<br/>task_mgmt/reflection.py"]
    TMON["TaskMonitor<br/>task_mgmt/monitor.py"]
    GFACT["GraphFactory<br/>task_mgmt/graph_factory.py"]
  end

  subgraph LLM["LLM Subsystem"]
    TIER["TierAwareLLMGateway<br/>llm/tier_router.py"]
    FAIL["FailoverChain<br/>llm/failover.py"]
    CACHE["PromptCacheInjector<br/>llm/cache.py"]
    STREAM["StreamingGateway<br/>llm/streaming.py"]
    HTTPLM["HttpLLMGateway<br/>llm/http_gateway.py"]
    ANTHLM["AnthropicGateway<br/>llm/anthropic_gateway.py"]
    MREG["ModelRegistry<br/>llm/registry.py"]
    BUDG["LLMBudgetTracker<br/>llm/budget_tracker.py"]
  end

  subgraph MEM["Memory Subsystem (3-Tier)"]
    L0["RawMemoryStore (L0)<br/>memory/l0_raw.py"]
    STM["ShortTermMemoryStore (L1)<br/>memory/short_term.py"]
    MTM["MidTermMemoryStore (L2)<br/>memory/mid_term.py"]
    LTM["LongTermMemoryGraph (L3)<br/>memory/long_term.py"]
    COMP["AsyncMemoryCompressor<br/>memory/async_compressor.py"]
    STRCOMP["StructuredCompressor<br/>memory/structured_compression.py"]
    MRET["UnifiedMemoryRetriever<br/>memory/unified_retriever.py"]
  end

  subgraph KNOW["Knowledge Subsystem"]
    KMGR["KnowledgeManager<br/>knowledge/knowledge_manager.py"]
    WIKI["KnowledgeWiki<br/>knowledge/wiki.py"]
    KGRAPH["KnowledgeGraph<br/>knowledge/store.py"]
    RETR["RetrievalEngine<br/>knowledge/retrieval_engine.py"]
    TFIDF["TF-IDF/BM25<br/>knowledge/tfidf.py"]
    EMBD["EmbeddingIndex<br/>knowledge/embedding.py"]
    GREND["GraphRenderer<br/>knowledge/graph_renderer.py"]
  end

  subgraph SKILL["Skill Subsystem"]
    SREG["SkillRegistry<br/>skill/registry.py"]
    SLDR["SkillLoader<br/>skill/loader.py"]
    SMATCH["SkillMatcher<br/>skill/matcher.py"]
    SEVO["SkillEvolver<br/>skill/evolver.py"]
    SVER["SkillVersionManager<br/>skill/version.py"]
    SOBS["SkillObserver<br/>skill/observer.py"]
    SREC["SkillUsageRecorder<br/>skill/recorder.py"]
  end

  subgraph EVO["Evolve Engine"]
    ENG["EvolveEngine<br/>evolve/engine.py"]
    POST["PostmortemAnalyzer<br/>evolve/postmortem.py"]
    SEXT["SkillExtractor<br/>evolve/skill_extractor.py"]
    REG["RegressionDetector<br/>evolve/regression_detector.py"]
    CC["ChampionChallenger<br/>evolve/champion_challenger.py"]
    DSET["DatasetEvaluator<br/>evolve/dataset_evaluator.py"]
  end

  subgraph CTX["Context OS"]
    CTXMGR["ContextManager<br/>context/manager.py"]
    RCTX["RunContext<br/>context/run_context.py"]
    RCTXMGR["RunContextManager<br/>context/run_context.py"]
    NUDGE["NudgeStrategy<br/>context/nudge.py"]
  end

  subgraph CAP["Capability System"]
    CREG["CapabilityRegistry<br/>capability/registry.py"]
    CINV["CapabilityInvoker<br/>capability/invoker.py"]
    ACINV["AsyncCapabilityInvoker<br/>capability/async_invoker.py"]
    CB["CircuitBreaker<br/>capability/circuit_breaker.py"]
    GTEXEC["GovernedToolExecutor<br/>capability/governance.py"]
    PPOL["PathPolicy<br/>security/path_policy.py"]
    UPOL["URLPolicy<br/>security/url_policy.py"]
    ABRG["AsyncBridgeService<br/>runtime/async_bridge.py"]
  end

  subgraph TRAJ["Trajectory"]
    TRGPH["TrajectoryGraph<br/>trajectory/graph.py"]
    STGPH["StageGraph<br/>trajectory/stage_graph.py"]
    OPT["GreedyOptimizer<br/>trajectory/optimizers.py"]
    DEAD["DeadEndDetector<br/>trajectory/dead_end.py"]
  end

  subgraph OBS["Observability"]
    MET["MetricsCollector<br/>observability/collector.py"]
    NOTIF["NotificationService<br/>observability/notification.py"]
    TRAJEXP["TrajectoryExporter<br/>observability/trajectory_exporter.py"]
    EVEM["EventEmitter<br/>events/emitter.py"]
    EVST["EventStore<br/>events/store.py"]
  end

  subgraph SESS["Session"]
    RSESS["RunSession<br/>session/run_session.py"]
    COST["CostCalculator<br/>session/cost_tracker.py"]
  end

  subgraph ADP["Runtime Adapter"]
    KADP["KernelFacadeAdapter<br/>runtime_adapter/kernel_facade_adapter.py"]
    AKADP["AsyncKernelFacadeAdapter<br/>runtime_adapter/async_kernel_facade_adapter.py"]
    KCLI["KernelFacadeClient<br/>runtime_adapter/kernel_facade_client.py"]
    RESADP["ResilientAdapter<br/>runtime_adapter/resilient_adapter.py"]
    MOCK["MockKernel<br/>runtime_adapter/mock_kernel.py"]
  end

  subgraph KERNEL["agent-kernel"]
    KR["KernelRuntime<br/>TurnEngine / EventLog / IdempotencyStore"]
  end

  subgraph SEC["Security & Auth"]
    AUTH["AuthMiddleware<br/>auth/"]
    RBAC["RBAC<br/>auth/rbac_enforcer.py"]
    JWT["JWTService<br/>auth/jwt_middleware.py"]
    OPOL["OperationPolicy<br/>auth/operation_policy.py"]
    ACTX["AuthorizationContext<br/>auth/authorization_context.py"]
    SOC["SOCGuard<br/>auth/soc_guard.py"]
  end

  subgraph OPS["Ops & Observability"]
    AUDIT["AuditLog<br/>observability/audit.py"]
    RGATE["ReleaseGateReport<br/>ops/release_gate.py"]
    PROFMGR["ProfileDirectoryManager<br/>profile/manager.py"]
    CFGSTACK["ProfileAwareConfigStack<br/>config/stack.py"]
    TRACER["Tracer<br/>observability/tracing.py"]
    SCHMREG["MCPSchemaRegistry<br/>mcp/schema_registry.py"]
  end

  %% Top-down connections
  CLI --> RLM
  SRV --> RLM
  SRV --> EBUS
  SRV --> DSCH
  SRV --> AUTH
  RLM --> REXEC

  REXEC --> STORCH
  STORCH --> STAGE
  REXEC --> LIFE
  REXEC --> TELE
  REXEC --> RCTX
  REXEC --> RSESS
  REXEC --> MWORCH
  REXEC --> TSCH
  REXEC --> KADP
  REXEC --> PROV
  RMRES --> PROV
  REXEC --> AUDIT

  OPOL --> ACTX
  OPOL --> SOC
  OPOL --> AUDIT
  SRV --> OPOL

  PROFMGR --> CFGSTACK
  CFGSTACK --> RGATE

  STAGE --> HROUT
  STAGE --> HEXEC
  STAGE --> RETR
  STAGE --> SLDR

  MWORCH --> PERC
  MWORCH --> CTRL
  MWORCH --> EXMW
  MWORCH --> EVAL
  MWORCH --> HOOKS

  HROUT --> RROUT
  HROUT --> LROUT
  HROUT --> SROUT
  HROUT --> DACIT

  HEXEC --> GOV
  HEXEC --> PERM
  HEXEC --> CINV
  HEXEC --> EVID

  TSCH --> ATSCH
  TSCH --> BGRD
  TSCH --> RPOL
  TSCH --> REFL
  TSCH --> TMON
  TSCH --> GFACT

  TIER --> FAIL
  TIER --> CACHE
  TIER --> STREAM
  FAIL --> HTTPLM
  FAIL --> ANTHLM
  TIER --> MREG
  TIER --> BUDG

  L0 --> STM
  STM --> MTM
  MTM --> LTM
  COMP --> STM
  STRCOMP --> COMP
  MRET --> STM
  MRET --> MTM
  MRET --> LTM

  KMGR --> WIKI
  KMGR --> KGRAPH
  KMGR --> RETR
  RETR --> TFIDF
  RETR --> EMBD
  KMGR --> GREND

  SREG --> SLDR
  SREG --> SMATCH
  SREG --> SVER
  SLDR --> SOBS
  SEVO --> SREG
  SREC --> SOBS

  ENG --> POST
  ENG --> SEXT
  ENG --> REG
  ENG --> CC
  ENG --> DSET
  SEXT --> SREG

  RCTXMGR --> RCTX
  CTXMGR --> RCTX
  CTXMGR --> NUDGE

  CREG --> CINV
  CINV --> CB
  CINV --> ACINV

  TRGPH --> STGPH
  TRGPH --> OPT
  TRGPH --> DEAD

  EVEM --> EVST
  EVEM --> MET
  EVEM --> EBUS
  NOTIF --> EBUS
  TRAJEXP --> EVST

  LIFE --> ENG
  LIFE --> STM
  LIFE --> KMGR
  LIFE --> RSESS

  TELE --> EVEM
  TELE --> MET
  TELE --> SOBS

  KADP --> KR
  AKADP --> KADP
  RESADP --> KADP
  KCLI --> KR

  RSESS --> COST
```

---

## 3. 接口关系图（Protocol 与实现）

```mermaid
classDiagram
  class LLMGateway {
    <<Protocol>>
    +complete(request: LLMRequest) LLMResponse
    +supports_model(model: str) bool
  }
  class TierAwareLLMGateway {
    +complete(request) LLMResponse
    +acomplete(request) Coroutine[LLMResponse]
    +supports_model(model) bool
    -tier_router: TierRouter
    -budget_tracker: LLMBudgetTracker
  }
  class FailoverChain {
    +complete(request) LLMResponse
    -gateways: list[LLMGateway]
    -credential_pool: list[str]
  }
  class HttpLLMGateway {
    +complete(request) LLMResponse
    -base_url: str
    -api_key: str
  }
  class AnthropicGateway {
    +complete(request) LLMResponse
  }
  LLMGateway <|.. TierAwareLLMGateway
  LLMGateway <|.. FailoverChain
  LLMGateway <|.. HttpLLMGateway
  LLMGateway <|.. AnthropicGateway
  TierAwareLLMGateway --> FailoverChain : delegates
  FailoverChain --> HttpLLMGateway : rotates

  class RuntimeAdapter {
    <<Protocol>>
    +start_run(task_id) str
    +query_run(run_id) dict
    +cancel_run(run_id, reason) void
    +resume_run(run_id) void
    +signal_run(run_id, signal, payload) void
    +open_stage(stage_id) void
    +mark_stage_state(stage_id, state) void
    +open_branch(run_id, stage_id, branch_id) void
    +mark_branch_state(run_id, stage_id, branch_id, state) void
    +record_task_view(task_view_id, content) str
    +bind_task_view_to_decision(task_view_id, decision_ref) void
    +open_human_gate(request) void
    +submit_approval(request) void
    +resolve_escalation(run_id, resolution_notes, caused_by) void
    +stream_run_events(run_id) AsyncIterator
    +query_trace_runtime(run_id) dict
    +query_run_postmortem(run_id) Any
    +get_manifest() dict
    +spawn_child_run(parent_run_id, task_id, config) str
    +query_child_runs(parent_run_id) list
    +spawn_child_run_async(parent_run_id, task_id, config) str
    +query_child_runs_async(parent_run_id) list
  }
  class KernelFacadeAdapter {
    +start_run(task_id) str
    +open_stage(stage_id) void
    -kernel_facade: KernelFacade
  }
  class AsyncKernelFacadeAdapter {
    +start_run(task_id) str
    -sync_adapter: KernelFacadeAdapter
  }
  class ResilientAdapter {
    +start_run(task_id) str
    -retry_policy: RetryPolicy
    -circuit_breaker: CircuitBreaker
  }
  RuntimeAdapter <|.. KernelFacadeAdapter
  RuntimeAdapter <|.. AsyncKernelFacadeAdapter
  RuntimeAdapter <|.. ResilientAdapter
  AsyncKernelFacadeAdapter --> KernelFacadeAdapter : wraps
  ResilientAdapter --> KernelFacadeAdapter : wraps

  class Middleware {
    <<Protocol>>
    +process(message: MiddlewareMessage) MiddlewareMessage
    +on_create(config) void
    +on_destroy() void
  }
  class PerceptionMiddleware {
    +process(message) MiddlewareMessage
    -entity_extractor: EntityExtractor
  }
  class ControlMiddleware {
    +process(message) MiddlewareMessage
    -skill_matcher: SkillMatcher
    -route_engine: RouteEngine
  }
  class ExecutionMiddleware {
    +process(message) MiddlewareMessage
    -harness_executor: HarnessExecutor
  }
  class EvaluationMiddleware {
    +process(message) MiddlewareMessage
    -quality_threshold: float
  }
  Middleware <|.. PerceptionMiddleware
  Middleware <|.. ControlMiddleware
  Middleware <|.. ExecutionMiddleware
  Middleware <|.. EvaluationMiddleware

  class RouteEngine {
    <<Protocol>>
    +propose(stage_id, run_id, seq) list~BranchProposal~
  }
  class HybridRouteEngine {
    +propose(stage_id, run_id, seq) list~BranchProposal~
    -rule_engine: RuleRouteEngine
    -llm_engine: LLMRouteEngine
  }
  class RuleRouteEngine {
    +propose(stage_id, run_id, seq) list~BranchProposal~
  }
  class LLMRouteEngine {
    +propose(stage_id, run_id, seq) list~BranchProposal~
    -llm_gateway: LLMGateway
  }
  RouteEngine <|.. HybridRouteEngine
  RouteEngine <|.. RuleRouteEngine
  RouteEngine <|.. LLMRouteEngine
  HybridRouteEngine --> RuleRouteEngine : delegates
  HybridRouteEngine --> LLMRouteEngine : delegates

  class CapabilityInvoker {
    +invoke(name, payload) dict
    -registry: CapabilityRegistry
    -circuit_breaker: CircuitBreaker
  }
  class AsyncCapabilityInvoker {
    +async_invoke(name, payload) dict
    -invoker: CapabilityInvoker
    -timeout: float
  }
  CapabilityInvoker --> AsyncCapabilityInvoker : async variant
```

---

## 4. 使用关系图（模块依赖）

```mermaid
graph LR
  REXEC["RunExecutor"]
  STAGE["StageExecutor"]
  LIFE["RunLifecycle"]
  TELE["RunTelemetry"]
  MWORCH["MiddlewareOrchestrator"]
  HROUT["HybridRouteEngine"]
  HEXEC["HarnessExecutor"]
  TIER["TierAwareLLMGateway"]
  RETR["RetrievalEngine"]
  KMGR["KnowledgeManager"]
  SREG["SkillRegistry"]
  SLDR["SkillLoader"]
  STM["ShortTermMemory"]
  COMP["AsyncMemoryCompressor"]
  ENG["EvolveEngine"]
  KADP["KernelFacadeAdapter"]
  CINV["CapabilityInvoker"]
  MET["MetricsCollector"]
  EVEM["EventEmitter"]
  RSESS["RunSession"]
  RCTX["RunContext"]
  TSCH["TaskScheduler"]
  TRGPH["TrajectoryGraph"]

  REXEC -->|delegates stage| STAGE
  REXEC -->|delegates lifecycle| LIFE
  REXEC -->|delegates telemetry| TELE
  REXEC -->|uses| MWORCH
  REXEC -->|uses| TSCH
  REXEC -->|uses| KADP
  REXEC -->|uses| RSESS
  REXEC -->|uses| RCTX

  STAGE -->|gets proposals| HROUT
  STAGE -->|dispatches action| HEXEC
  STAGE -->|retrieves knowledge| RETR
  STAGE -->|injects skills| SLDR

  MWORCH -->|runs pipeline| HEXEC
  MWORCH -->|uses| HROUT
  MWORCH -->|uses| TIER

  HROUT -->|calls| TIER
  HEXEC -->|calls| CINV
  CINV -->|executes| CAP["Capability"]

  LIFE -->|triggers| ENG
  LIFE -->|stores| STM
  LIFE -->|ingests| KMGR

  TELE -->|emits| EVEM
  TELE -->|records| MET

  COMP -->|compresses to| STM
  RETR -->|queries| KMGR
  RETR -->|uses| TIER

  ENG -->|extracts skills| SREG
  ENG -->|updates| SREG

  TIER -->|routes to| LLM["LLM API"]
  KADP -->|calls| KERNEL["agent-kernel"]
```

---

## 5. 任务执行时序图（Sequence Diagram）

```mermaid
sequenceDiagram
  autonumber
  participant Client as Client (CLI/API)
  participant Server as HTTP Server<br/>server/app.py
  participant RunMgr as RunManager
  participant Exec as RunExecutor<br/>runner.py
  participant Stage as StageExecutor<br/>runner_stage.py
  participant MW as MiddlewareOrchestrator
  participant Route as HybridRouteEngine
  participant Harness as HarnessExecutor
  participant Gov as GovernanceEngine
  participant Cap as CapabilityInvoker
  participant LLM as TierAwareLLMGateway
  participant Know as KnowledgeManager
  participant Skill as SkillLoader
  participant Mem as AsyncMemoryCompressor
  participant Kernel as RuntimeAdapter→agent-kernel
  participant Evolve as EvolveEngine

  Client->>Server: POST /runs {TaskContract}
  Server->>RunMgr: submit_run(contract)
  RunMgr->>Exec: RunExecutor(contract, builder)
  RunMgr-->>Client: {run_id, status: ACTIVE}

  Exec->>Kernel: start_run(task_id) → run_id
  Exec->>Exec: build stage_graph (S1→S5)

  loop For each Stage in TRACE (S1 Understand → S5 Deliver)
    Exec->>Stage: execute_stage(stage_id)
    Stage->>Kernel: open_stage(stage_id)
    Stage->>Know: query(stage_context) → KnowledgeResult
    Stage->>Skill: build_prompt() → skill_context
    Stage->>MW: process(MiddlewareMessage)

    MW->>MW: Perception: extract entities, build context
    MW->>LLM: complete(control_request) [medium tier]
    LLM-->>MW: ExecutionPlan
    MW->>MW: Control: skill matching, resource binding

    MW->>Route: propose(stage_id, run_id, seq)
    Route->>LLM: complete(route_request) [if LLM route]
    LLM-->>Route: BranchProposal[]
    Route-->>MW: BranchProposal[]

    loop For each BranchProposal
      MW->>Kernel: open_branch(run_id, stage_id, branch_id)
      MW->>Harness: execute(ActionSpec)
      Harness->>Gov: can_execute(spec) → bool
      Gov-->>Harness: approved
      Harness->>Cap: invoke(capability_name, payload)
      Cap-->>Harness: ActionResult
      Harness->>Harness: store evidence
      Harness-->>MW: ActionResult + evidence_refs
      MW->>Kernel: mark_branch_state(branch_id, outcome)
    end

    MW->>MW: Evaluation: quality_score ≥ threshold?
    MW-->>Stage: MiddlewareResult

    alt Quality accepted
      Stage->>Kernel: mark_stage_state(stage_id, COMPLETED)
      Stage->>Mem: compress_stage(stage_summary)
      Mem->>LLM: complete(compress_request) [light tier]
      LLM-->>Mem: CompressedSummary
      Mem->>Mem: store to ShortTermMemory (L1)
    else Quality rejected / dead-end
      Stage->>Stage: detect backtrack edge
      Stage->>Exec: request_recovery(stage_id)
      Exec->>Kernel: mark_stage_state(stage_id, FAILED)
    end

    Stage-->>Exec: StageResult {findings, decisions}
  end

  Exec->>Evolve: on_run_completed(RunPostmortem)
  Evolve->>Evolve: PostmortemAnalyzer.analyze()
  Evolve->>Evolve: SkillExtractor.extract() → SkillCandidate[]
  Evolve->>Evolve: RegressionDetector.record()
  Evolve->>Evolve: ChampionChallenger.update_metrics()

  Exec->>Kernel: close_run(run_id, outcome)
  Exec-->>RunMgr: RunResult {run_id, findings, cost}
  RunMgr->>Server: emit RUN_COMPLETED event (SSE)
  Server-->>Client: GET /runs/{run_id}/events (SSE stream)
```

---

## 6. 数据流图（Data Flow Diagram）

```mermaid
flowchart TD
  INPUT["用户输入<br/>TaskContract<br/>{goal, constraints, budget}"]

  subgraph INGRESS["入口层"]
    API["POST /runs"]
    RUN_CTX["RunContext 创建<br/>run_context.py"]
    SESS["RunSession 初始化<br/>session/run_session.py"]
  end

  subgraph PREPROCESS["预处理层"]
    KNOW_QUERY["Knowledge Query<br/>retrieval_engine.retrieve()"]
    SKILL_INJECT["Skill Injection<br/>skill_loader.build_prompt()"]
    TASK_VIEW["Task View 构建<br/>task_view/builder.py"]
  end

  subgraph PIPELINE["中间件管道"]
    PERC_DATA["Perception Data<br/>entity_map, context_str"]
    CTRL_DATA["Control Data<br/>ExecutionPlan, resource_bindings"]
    EXEC_DATA["Execution Data<br/>ActionSpec, capability_name"]
    EVAL_DATA["Evaluation Data<br/>quality_score, retry_flag"]
  end

  subgraph LLM_LAYER["LLM 调用层"]
    LLM_REQ["LLMRequest<br/>{messages, model, max_tokens}"]
    TIER_ROUTE["TierRouter<br/>purpose→strong/medium/light"]
    CACHE_CHK["PromptCacheInjector<br/>cache_control anchors"]
    LLM_RESP["LLMResponse<br/>{content, usage, finish_reason}"]
  end

  subgraph EXECUTION["执行层"]
    ACTION_SPEC["ActionSpec<br/>{action_id, capability_name, payload}"]
    GOV_CHECK["GovernanceEngine<br/>EffectClass + SideEffectClass 分级"]
    CAP_RESULT["Capability Result<br/>{output, metadata}"]
    EVIDENCE["EvidenceRecord<br/>{action_id, result, timestamp}"]
  end

  subgraph CAPTURE["捕获层"]
    STAGE_SUM["StageSummary<br/>{findings, decisions, outcome}"]
    RAW_EVT["RawEventRecord (L0)<br/>JSONL uncompressed"]
    COMPRESS["CompressedMemory<br/>LLM summarized"]
    STM_REC["ShortTermMemory (L1)<br/>per-session working set"]
  end

  subgraph KERNEL_LAYER["Kernel 层"]
    K_EVENTS["Kernel Event Log<br/>immutable facts"]
    K_STATE["Run/Stage/Branch State<br/>state machine"]
    K_IDEM["Idempotency Store<br/>dedup key"]
  end

  subgraph EVOLVE_LAYER["进化层"]
    POSTMORT["RunPostmortem<br/>{run_id, stage_results, metrics}"]
    SKILL_CAND["SkillCandidate<br/>{name, prompt_template, trigger}"]
    REGR_DATA["RegressionPoint<br/>{metric, baseline, delta}"]
    CC_DATA["ChampionChallenger<br/>A/B metrics comparison"]
  end

  subgraph OUTPUT["输出层"]
    RUN_RESULT["RunResult<br/>{run_id, status, findings, cost}"]
    SSE_STREAM["SSE Events<br/>/runs/{id}/events"]
    KNOW_UPDATE["Knowledge Update<br/>wiki + graph auto-ingest"]
    SKILL_UPDATE["Skill Registry Update<br/>new/promoted skills"]
  end

  INPUT --> API
  API --> RUN_CTX
  API --> SESS

  RUN_CTX --> KNOW_QUERY
  RUN_CTX --> SKILL_INJECT
  KNOW_QUERY --> TASK_VIEW
  SKILL_INJECT --> TASK_VIEW

  TASK_VIEW --> PERC_DATA
  PERC_DATA --> CTRL_DATA
  CTRL_DATA --> EXEC_DATA
  EXEC_DATA --> EVAL_DATA

  CTRL_DATA --> LLM_REQ
  LLM_REQ --> TIER_ROUTE
  TIER_ROUTE --> CACHE_CHK
  CACHE_CHK --> LLM_RESP
  LLM_RESP --> CTRL_DATA

  EXEC_DATA --> ACTION_SPEC
  ACTION_SPEC --> GOV_CHECK
  GOV_CHECK --> CAP_RESULT
  CAP_RESULT --> EVIDENCE

  EVAL_DATA --> STAGE_SUM
  EVIDENCE --> STAGE_SUM
  STAGE_SUM --> RAW_EVT
  STAGE_SUM --> COMPRESS
  COMPRESS --> STM_REC

  ACTION_SPEC --> K_EVENTS
  STAGE_SUM --> K_STATE
  K_STATE --> K_IDEM

  STAGE_SUM --> POSTMORT
  POSTMORT --> SKILL_CAND
  POSTMORT --> REGR_DATA
  SKILL_CAND --> CC_DATA

  STAGE_SUM --> RUN_RESULT
  K_STATE --> SSE_STREAM
  STM_REC --> KNOW_UPDATE
  CC_DATA --> SKILL_UPDATE

  RUN_RESULT --> OUTPUT
  SSE_STREAM --> OUTPUT
  KNOW_UPDATE --> OUTPUT
  SKILL_UPDATE --> OUTPUT
```

---

## 7. 记忆系统数据流（Memory Consolidation Flow）

```mermaid
flowchart LR
  subgraph SESSION["Session"]
    ACT["Action Events<br/>RawEventRecord"]
    STAGE_DONE["Stage Completion<br/>StageSummary"]
  end

  subgraph L0["L0: Raw Store"]
    RAW["JSONL append-only<br/>memory/l0_raw.py"]
  end

  subgraph L1["L1: Short-Term (per session)"]
    STM["ShortTermMemory<br/>LLM-compressed summaries<br/>memory/short_term.py"]
    CTX_WINDOW["Context Window<br/>last N turns"]
  end

  subgraph L2["L2: Mid-Term (daily dream)"]
    DREAM["DreamConsolidator<br/>memory/mid_term.py"]
    DAILY["DailySummary<br/>{date, key_facts, decisions}"]
  end

  subgraph L3["L3: Long-Term (graph)"]
    LTMG["LongTermMemoryGraph<br/>memory/long_term.py"]
    NODES["MemoryNode<br/>{id, content, type, embedding}"]
    EDGES["MemoryEdge<br/>{source, target, relation}"]
  end

  subgraph RETRIEVAL["检索层"]
    URET["UnifiedMemoryRetriever<br/>memory/unified_retriever.py"]
    RENG["RetrievalEngine<br/>knowledge/retrieval_engine.py"]
  end

  ACT --> RAW
  STAGE_DONE --> STM
  RAW --> STM
  STM --> CTX_WINDOW

  STM -->|nightly dream| DREAM
  DREAM --> DAILY
  DAILY --> LTMG
  LTMG --> NODES
  LTMG --> EDGES

  URET --> STM
  URET --> DAILY
  URET --> LTMG
  RENG --> URET
```

---

## 8. 进化引擎流程（Evolve Engine Flow）

```mermaid
flowchart TD
  RUN_END["Run Completed<br/>RunPostmortem"]

  POST["PostmortemAnalyzer<br/>evolve/postmortem.py<br/>分析成功/失败模式"]
  SEXT["SkillExtractor<br/>evolve/skill_extractor.py<br/>提取可复用技能候选"]
  DSET["DatasetEvaluator<br/>evolve/dataset_evaluator.py<br/>benchmark 评测"]
  REG["RegressionDetector<br/>evolve/regression_detector.py<br/>检测性能退化"]
  CC["ChampionChallenger<br/>evolve/champion_challenger.py<br/>A/B 版本对比"]

  CAND["SkillCandidate<br/>{name, prompt, trigger, score}"]
  SREG["SkillRegistry<br/>skill/registry.py"]
  SVER["SkillVersionManager<br/>champion/challenger"]
  SEVO["SkillEvolver<br/>textual gradient 优化"]

  ALERT["RegressionAlert<br/>observability/notification.py"]

  RUN_END --> POST
  POST --> SEXT
  POST --> DSET
  POST --> REG
  SEXT --> CAND
  CAND --> SREG
  SREG --> SVER
  SVER --> CC
  CC --> SEVO
  SEVO --> SREG
  REG --> ALERT
  DSET --> REG
```

---

## 9. 关键模块接口说明

### 9.1 RunExecutor — 主执行入口

| 方法 | 签名 | 职责 |
|------|------|------|
| `execute` | `() → dict` | 线性 stage 遍历执行（TRACE S1→S5） |
| `execute_graph` | `(stage_graph: TrajectoryGraph) → dict` | 动态图遍历含回溯与多后继路由 |
| `execute_async` | `() → Coroutine[dict]` | asyncio 全异步模式（AsyncTaskScheduler） |
| `resume_from_checkpoint` | `(checkpoint: dict) → dict` | 从 checkpoint 恢复运行 |

### 9.2 LLMGateway Protocol

| 方法 | 签名 | 职责 |
|------|------|------|
| `complete` | `(request: LLMRequest) → LLMResponse` | 同步模型调用 |
| `stream` | `(request: LLMRequest) → Iterator[LLMStreamChunk]` | SSE 流式调用（httpx chunked transfer） |
| `supports_model` | `(model: str) → bool` | 检查模型兼容性（`AnthropicGateway` 始终返回 True，支持代理端点） |

**LLMRequest 扩展字段**：
- `messages: list[dict[str, Any]]` — content 支持字符串或 content block 列表（multimodal）
- `thinking_budget: int | None` — per-request 思考预算，覆盖 gateway 级默认值；`> 0` 开启，`0` 强制关闭

**LLMStreamChunk**（`llm/protocol.py`）：
```
delta: str              # 本次文字增量
thinking_delta: str     # 思考过程增量（Anthropic extended thinking）
finish_reason: str|None # 最终块携带停止原因
usage: TokenUsage|None  # 最终块携带 token 用量
model: str              # message_start 块携带模型 ID
```

**实现链路**：`TierAwareLLMGateway` → `FailoverChain` → `AnthropicLLMGateway`（Anthropic API / 兼容代理）或 `HttpLLMGateway`（OpenAI API）

- `TierAwareLLMGateway` 同时提供同步 `complete()`、异步 `acomplete()`、流式 `stream()`；无流式能力的后端自动降级为单 chunk 包装。
- `AnthropicLLMGateway` 支持自定义 `base_url`，可接入 DashScope 等 Anthropic 协议兼容代理；`default_thinking_budget` 配置 gateway 级思考预算。
- 思考模式开启时自动强制 `temperature=1`（Anthropic API 要求）。

**provider 配置（`config/llm_config.json`）**：
```json
{
  "default_provider": "dashscope",
  "providers": {
    "dashscope": {
      "api_key": "sk-...",
      "base_url": "https://...",
      "api_format": "anthropic",
      "models": {"strong": "...", "medium": "...", "light": "..."},
      "features": {"stream": true, "thinking_budget": null, "multimodal": false}
    }
  }
}
```
`build_gateway_from_config()` 读取此文件，按 `api_format` 选择 `AnthropicLLMGateway` 或 `HttpLLMGateway`，注入 `thinking_budget`，并包装进 `TierAwareLLMGateway` 返回。`SystemBuilder.build_llm_gateway()` 在 env var 未命中时自动回落到此配置文件。

### 9.3 RuntimeAdapter Protocol（22 方法）

| 方法组 | 方法 | 职责 |
|--------|------|------|
| Run 生命周期 | `start_run`, `query_run`, `cancel_run`, `resume_run`, `signal_run` | run 全生命周期管理 |
| Stage | `open_stage`, `mark_stage_state` | stage 状态推进 |
| Branch | `open_branch`, `mark_branch_state` | branch 状态管理 |
| Task View | `record_task_view`, `bind_task_view_to_decision` | 任务视图持久化与决策绑定 |
| Human Gate | `open_human_gate`, `submit_approval`, `resolve_escalation` | 人类审批 + escalation 恢复 |
| Events / Trace | `stream_run_events`, `query_trace_runtime` | 事件流与 trace 快照 |
| Diagnostics | `query_run_postmortem`, `get_manifest` | 事后分析与能力清单 |
| Child Runs | `spawn_child_run`, `query_child_runs`, `spawn_child_run_async`, `query_child_runs_async` | 子 run 管理（同步 + 异步） |

`resolve_escalation(run_id, *, resolution_notes, caused_by)` — 当 run 因 `human_escalation` 恢复决策进入 `waiting_external` 状态时，通过此方法发送 `recovery_succeeded` 信号令工作流继续执行。对应 agent-kernel `POST /runs/{id}/resolve-escalation`。

**KernelFacadeClient**（`runtime_adapter/kernel_facade_client.py`）：concrete dual-mode 实现，同时支持 `direct`（in-process KernelFacade）和 `http`（REST over KernelFacade HTTP）两种模式。全部 22 个协议方法均实现 direct/http 双分支；`resolve_escalation` 因 keyword-only 参数直接调用 facade，绕过通用 `_direct_call()` 辅助方法。

### 9.4 Middleware Protocol

| 生命周期 | 方法 | 职责 |
|---------|------|------|
| 创建 | `on_create(config)` | 中间件初始化 |
| 处理 | `process(message: MiddlewareMessage) → MiddlewareMessage` | 核心管道处理 |
| 销毁 | `on_destroy()` | 资源清理 |

**HookAction**: `CONTINUE` / `MODIFY` / `SKIP` / `BLOCK` / `RETRY`

**线程安全**：`MiddlewareOrchestrator` 的所有结构变更方法（`add/replace/remove_middleware`、`add/remove_hook`、`add_global_hook`）均在 `threading.Lock` 保护下执行。`run()` 入口持锁创建管道快照（`_mw_snapshot`），整个 pipeline 遍历使用快照，消除并发 run 与结构修改之间的竞态条件。

### 9.5 Server API 端点

| 路径 | 方法 | 职责 |
|------|------|------|
| `/runs` | `POST` | 提交任务，返回 run_id |
| `/runs` | `GET` | 列出活跃 run |
| `/runs/{id}` | `GET` | 查询 run 状态 |
| `/runs/{id}/signal` | `POST` | 发送信号（pause/resume/cancel） |
| `/runs/{id}/resume` | `POST` | 从 checkpoint 恢复 |
| `/runs/{id}/events` | `GET` | SSE 事件流 |
| `/knowledge/ingest` | `POST` | 文本摄取到 wiki |
| `/knowledge/ingest-structured` | `POST` | 结构化事实摄取到图谱 |
| `/knowledge/query` | `GET` | 知识查询 |
| `/knowledge/status` | `GET` | 知识库状态 |
| `/knowledge/lint` | `POST` | 知识健康检查 |
| `/memory/dream` | `POST` | 触发 dream 整合（mid-term） |
| `/memory/consolidate` | `POST` | 触发长期图整合 |
| `/memory/status` | `GET` | 记忆系统状态 |
| `/skills/list` | `GET` | 技能列表 |
| `/skills/evolve` | `POST` | 触发 champion/challenger 轮次 |
| `/skills/{id}/optimize` | `POST` | 优化技能 prompt |
| `/skills/{id}/promote` | `POST` | challenger → champion |
| `/context/health` | `GET` | 上下文预算健康 |
| `/health` | `GET` | 全系统健康 |
| `/ready` | `GET` | 平台就绪检查（200=ready，503=not ready，返回 capabilities 列表） |
| `/manifest` | `GET` | 系统能力清单（`contract_field_status`、MCP 状态、e2e 端点目录） |
| `/tools` | `GET` | 注册的能力列表 |
| `/tools/call` | `POST` | 按名称调用能力 |
| `/mcp/tools/list` | `POST` | MCP 工具枚举（含 JSON Schema） |
| `/mcp/tools/call` | `POST` | MCP 工具调用 |
| `/sessions` | `GET` | 列出当前用户的活跃 session |
| `/sessions/{id}/runs` | `GET` | 列出 session 内所有 run |
| `/sessions/{id}` | `PATCH` | 归档或重命名 session |
| `/team/events` | `GET` | 列出 team space 事件（支持 since_id） |
| `/metrics` | `GET` | Prometheus 指标 |
| `/metrics/json` | `GET` | JSON 指标快照 |

### 9.6 Public API Surface

Top-level symbols exported from `hi_agent` for external callers:

| Symbol | Description |
|--------|-------------|
| `hi_agent.RunExecutorFacade` | `start(run_id, profile_id, model_tier, skill_dir)` / `run(prompt) → RunFacadeResult` / `stop()` |
| `hi_agent.check_readiness()` | Returns `ReadinessReport` — per-subsystem health check |
| `hi_agent.GateEvent` | Human gate lifecycle event dataclass |
| `hi_agent.GatePendingError` | Raised when stage execution hits a pending gate |
| `hi_agent.SubRunHandle` / `SubRunResult` | Nested sub-run dispatch / collection |
| `hi_agent.llm.tier_presets.apply_research_defaults(router)` | Research tier preset — configures TierRouter with research-optimized defaults |

---

## 10. 配置与组件装配（SystemBuilder）

```mermaid
flowchart LR
  CFG["TraceConfig<br/>95+ 参数<br/>JSON/env/code"]
  STACK["ProfileAwareConfigStack<br/>config/stack.py<br/>5 层合并"]
  PROFMGR["ProfileDirectoryManager<br/>profile/manager.py<br/>HI_AGENT_HOME"]

  subgraph SB["SystemBuilder<br/>config/builder.py"]
    subgraph CB["CognitionBuilder<br/>config/cognition_builder.py"]
      LLM["build_llm_gateway()<br/>→ TierAwareLLMGateway"]
      EVO["build_evolve_engine()<br/>→ EvolveEngine"]
      REFL["build_reflection_orchestrator()"]
    end
    subgraph RB["RuntimeBuilder<br/>config/runtime_builder.py"]
      KRN["build_kernel()<br/>→ RuntimeAdapter"]
      MW["build_middleware_orchestrator()<br/>→ MiddlewareOrchestrator"]
      MET["build_metrics_collector()"]
    end
    MEM["build_memory_manager()<br/>→ 3-tier stack"]
    KNOW["build_knowledge_manager()<br/>→ KnowledgeManager"]
    SKL["build_skill_registry()<br/>→ SkillRegistry"]
    HARN["build_harness_executor()<br/>→ HarnessExecutor"]
    SCHED["build_task_scheduler()<br/>→ TaskScheduler"]
    SRV["build_http_server()<br/>→ AgentServer"]
  end

  STACK --> CFG
  PROFMGR --> STACK
  CFG --> SB
  SB --> REXEC["RunExecutor<br/>(assembled, no post-construction mutation)"]
```

**TraceConfig 核心参数**：

| 类别 | 参数示例 |
|------|---------|
| Kernel | `kernel_base_url` ("local" / HTTP URL) |
| LLM | `llm_api_key`, `llm_default_model`, `llm_budget_max_calls` |
| 缓存 | `prompt_cache_enabled`, `prompt_cache_anchor_messages` |
| 记忆 | `memory_tier_enabled`, `memory_consolidation_interval_seconds`, `memory_compress_max_findings`, `memory_compress_max_decisions`, `memory_compress_max_entities`, `memory_compress_max_tokens` |
| 知识 | `knowledge_storage_dir` |
| 技能 | `skill_registry_dir`, `skill_evolution_enabled` |
| 上下文预算 | `context_skill_prompts_budget`（默认 2000），`context_knowledge_context_budget`，`context_system_prompt_budget` |
| AutoCompress | `compress_snip_threshold`, `compress_window_threshold`, `compress_compress_threshold`, `compress_default_budget_tokens` |
| 中间件 | `middleware_enabled`, `gate_quality_threshold` |
| 服务器 | `server_host`, `server_port`, `server_workers` |

---

## 11. 失败处理与恢复机制

```mermaid
flowchart TD
  FAIL_EVT["Action/Stage 失败"]

  subgraph DETECT["检测层"]
    FC["FailureCollector<br/>failures/collector.py"]
    WD["ProgressWatchdog<br/>failures/watchdog.py"]
    DD["DeadEndDetector<br/>trajectory/dead_end.py"]
  end

  subgraph CLASSIFY["分类层<br/>failures/taxonomy.py"]
    MISSING["missing_evidence"]
    HARNESS_D["harness_denied"]
    MODEL_INV["model_output_invalid"]
    NO_PROG["no_progress"]
    BUDGET_X["execution_budget_exhausted"]
  end

  subgraph RECOVER["恢复层"]
    RPOL["RestartPolicyEngine<br/>task_mgmt/restart_policy.py"]
    REFL["ReflectionOrchestrator<br/>task_mgmt/reflection.py"]
    BACK["Backtrack Edge<br/>trajectory/graph.py"]
    GATE["HumanGate<br/>runtime_adapter → kernel"]
  end

  FAIL_EVT --> FC
  FAIL_EVT --> WD
  FAIL_EVT --> DD

  FC --> MISSING
  FC --> HARNESS_D
  FC --> MODEL_INV
  WD --> NO_PROG
  DD --> BUDGET_X

  MISSING --> RPOL
  HARNESS_D --> GATE
  MODEL_INV --> REFL
  NO_PROG --> BACK
  BUDGET_X --> RPOL

  RPOL --> RECOVER_ACTION["retry / reflect / escalate / abort"]
  REFL --> LLM_REFL["LLM 生成恢复建议"]
  LLM_REFL --> RPOL
```

---

## 12. 已知工程边界

- `agent-kernel` 通过固定 commit 引用（git submodule），未来建议切换可发布制品（wheel/index）。
- `TaskAttemptRecord` 保留兼容入口（带弃用提示），新代码仅使用 `TaskAttempt`。
- Windows 环境代理绕行依赖运行环境配置（P0）。
- MCP 传输层（`mcp/transport.py`）当前 `transport_status = not_wired`：MCPServer 包裹能力注册表可正常枚举工具，但外部 JSON-RPC/SSE 传输尚未接入，`/manifest` 中 `capability_mode = infrastructure_only` 明确标注。

**2026-04-14 自审修复归档（全部已关闭）：**

| 缺口 | 修复内容 |
|------|---------|
| SSE 推流断路 | `RunExecutor._record_event()` 现直接调用 `event_bus.publish()`，将运行事件实时推入 SSE 流。 |
| KernelFacadeClient HTTP 模式不完整 | `query_run_postmortem`、`query_child_runs` 补全 HTTP 分支；新增 `spawn_child_run` 完整实现。 |
| HybridRouteEngine 审计空转 | `propose_with_provenance()` 两个返回路径均调用 `persist_route_decision_audit()`，决策写入 `DecisionAuditStore`。 |
| 异步路径绕过 tier 路由 | `TierAwareLLMGateway` 新增 `acomplete()`；`DelegationManager` 异步路径经由该方法统一 tier 选择。 |
| SkillEvolver 空指针 | `analyze_skill / optimize_prompt / deploy_optimization / discover_patterns / evolve_cycle` 全部加 `_observer` / `_version_manager` 空值守卫。 |
| RestartPolicyEngine 状态写入空操作 | `update_state` lambda 现写入 `_state_store` 字典，状态持久有效。 |

## 12.1 TaskContract 字段消费边界

`POST /runs` 接受 13 个 TaskContract 字段，消费级别如下（`/manifest` 的 `contract_field_status` 节动态返回）：

| 字段 | 消费级别 | 说明 |
|------|---------|------|
| `goal` | **ACTIVE** | 驱动 TaskView 构建与 LLM prompt |
| `task_family` | **ACTIVE** | 选择路由配置 |
| `risk_level` | **ACTIVE** | Harness 治理决策 |
| `constraints` | **ACTIVE** | 解析 `fail_action:*`、`action_max_retries:*`、`invoker_role:*` 前缀 |
| `acceptance_criteria` | **ACTIVE** | run 完成后检查 `required_stage:*`、`required_artifact:*` 是否满足 |
| `budget` | **ACTIVE** | BudgetGuard tier 降级与 deadline 执行 |
| `deadline` | **ACTIVE** | wall-clock deadline 检查（过期立即失败） |
| `profile_id` | **ACTIVE** | SystemBuilder profile 解析 |
| `decomposition_strategy` | **ACTIVE** | TaskOrchestrator 分解模式 |
| `priority` | **QUEUE_ONLY** | RunManager 队列排序，不进入 stage 执行 |
| `environment_scope` | **PASSTHROUGH** | 存储并回传，执行层不消费 |
| `input_refs` | **PASSTHROUGH** | 存储并回传，执行层不消费 |
| `parent_task_id` | **PASSTHROUGH** | 存储并回传，执行层不消费 |

PASSTHROUGH 字段的消费由调用层（business agent / profile）负责。

## 12.2 2026-04-15 自审修复归档（全部已关闭）

| 缺口 | 修复内容 |
|------|---------|
| WikiStore 单页损坏崩溃 | `wiki.py` `load()` 对每个 `.json` 文件单独 try-except `(json.JSONDecodeError, KeyError, ValueError)`，跳过损坏页并记录 warning，整体加载不中断。 |
| `ContextBudget.skill_prompts` 映射错误配置字段 | `context/manager.py` `from_config()` 将 `skill_prompts` 从 `cfg.compress_default_budget_tokens`（task-view 自动压缩预算 8192）修正为专用字段 `cfg.context_skill_prompts_budget`（默认 2000）。 |
| `context_skill_prompts_budget` 字段缺失 | `trace_config.py` 新增 `context_skill_prompts_budget: int = 2_000`，与 `context_system_prompt_budget`、`context_tool_definitions_budget` 并列管理。 |

---

## 12.3 2026-04-15 agent-kernel 集成闭环（全部已关闭）

| 缺口 | 来源 | 修复内容 |
|------|------|---------|
| `AsyncExecutorService(handler=None)` 缺少 production guard | hi-agent 反馈 P0 | agent-kernel `_enforce_production_safety()` 新增 `enable_activity_backed_executor` 参数；`False` + `"prod"` 环境直接抛 `ValueError` |
| `resolve_escalation()` 调用方协议缺口 | hi-agent 反馈 P1 | agent-kernel 确认为 Public caller-facing API；hi-agent 在 `RuntimeAdapter`（protocol.py）、`KernelFacadeAdapter`、`KernelFacadeClient` 三处实现，direct/http 双路均完整 |
| `InMemoryTaskEventLog` 未纳入 production check | hi-agent 反馈 P2 | agent-kernel 改为 `warnings.warn`（非硬拒绝），标注暂无持久化后端；待持久化后端就绪后升为硬拒绝 |
| RuntimeAdapter 协议方法数文档失实 | 内部发现 | ARCHITECTURE.md Section 9.3 从 17 方法（含错误方法名）修正为 22 方法，逐方法组整理准确 |

---

## 12.4 2026-04-15 调用方审计 + agent-kernel 刷新（全部已关闭）

agent-kernel 升级至 `ff4d25c7`（含 2 个新提交）：

| 缺口 | 来源 | 修复内容 |
|------|------|---------|
| `stream_run_events` Temporal 模式静默空流（P1） | hi-agent 调用方审计 | agent-kernel `ae2acc7`：`_stream_run_events()` 从静默返回空 iterator 改为抛 `RuntimeError`（含 actionable message），消除 SSE / reconcile loop 静默数据丢失风险 |
| `KernelFacadeClient` direct 模式 `stream_run_events` 无异常守卫 | hi-agent 内部发现 | `runtime_adapter/kernel_facade_client.py`：`async for` 循环包裹 `try/except`，将底层 `RuntimeError` 统一转换为 `RuntimeAdapterBackendError`，与 `KernelFacadeAdapter` 行为一致 |
| `spawn_child_run_async` / `query_child_runs_async` 协议缺口 | hi-agent DelegationManager P0 | `KernelFacadeAdapter` 与 `KernelFacadeClient` 均新增两个 async wrapper（`asyncio.to_thread`）；`AsyncKernelFacadeAdapter` 补全 `resolve_escalation` async 委托与 `spawn_child_run` 同步委托 |
| agent-kernel submodule pin | 版本对齐 | `pyproject.toml` 固定 commit 从 `43fda27` 升至 `ff4d25c7` |

---

## 12.6 2026-04-18 W1–W12 sprint 归档（全部已合并到 main）

| Sprint | 票号 | 内容 |
|--------|------|------|
| W1 | D1-001 | 运行时基线冻结文档 |
| W1 | D2-001 | evolve_mode 三态策略（auto/on/off）+ audit.evolve 事件 |
| W1 | D3-001 | RunResult.execution_provenance + runtime_mode_resolver |
| W1 | D3-002 | 基线差异验证 |
| W1 | D4-001 | /manifest 真实 runtime_mode + evolve_policy + provenance_contract_version |
| W1 | D5-001 | @require_operation RBAC/SOC 装饰器 + AuthorizationContext |
| W10 | W10-001 | StageOrchestrator 从 RunExecutor 提取（linear/graph/resume） |
| W10 | W10-002 | CognitionBuilder + RuntimeBuilder 分拆；消除 3 处后置构造突变 |
| W10 | W10-003 | dangerous capability RBAC 双重守卫 |
| W10 | W10-004 | output_budget_tokens 截断强制 |
| W10 | W10-005 | 审计事件类型 + MCP 重启退避 + schema 漂移注册 |
| W11 | W11-001 | HI_AGENT_HOME + ProfileDirectoryManager + ProfileAwareConfigStack |
| W11 | W11-002 | fake server fixtures（LLM/kernel/MCP 测试桩） |
| W12 | W12-001 | dev-smoke 黄金路径 3 层测试 |
| W12 | W12-002 | prod-real 发布门禁（7 门禁，含 prod_e2e_recent） |
| W12 | W12-003 | Runbook 文档（deploy/verify/rollback/incident） |
| W12 | W12-004 | W12 sprint retro + M2 milestone 声明 |

---

## 12.5 2026-04-17 LLM 能力扩展（全部已合并）

| 能力 | 实现内容 |
|------|---------|
| **SSE 流式调用** | `AnthropicLLMGateway.stream()` 和 `HttpLLMGateway.stream()` 均通过 httpx 实现真实分块传输；`LLMStreamChunk` 携带增量文本、思考增量、最终 usage；SSE `data:` 前缀容忍有无空格格式差异（兼容 DashScope）。 |
| **Extended Thinking** | `LLMRequest.thinking_budget` per-request 设置；`AnthropicLLMGateway(default_thinking_budget=N)` gateway 级默认；映射到 Anthropic `{"thinking": {"type": "enabled", "budget_tokens": N}}`，自动强制 `temperature=1`。 |
| **Multimodal 输入** | `LLMRequest.messages[].content` 接受 content block 列表（`{"type": "image", "source": {...}}` + `{"type": "text", ...}`）；`AnthropicLLMGateway._build_payload()` 处理 system 消息中的 content block 提取。 |
| **第三方 Anthropic 兼容代理** | `AnthropicLLMGateway(base_url=...)` 支持自定义端点（DashScope 等）；`llm_config.json` 新增 `api_format`、`features` 字段；`build_gateway_from_config()` 按 `api_format` 分发 gateway 类型。 |
| **SystemBuilder 配置回落** | `build_llm_gateway()` env var 未命中时自动调用 `build_gateway_from_config()`，无需手动设置环境变量即可接入配置文件中的 provider。 |

---

## 13. 质量门禁

```bash
python -m ruff check hi_agent tests scripts examples
python -m pytest -q        # 3858 passed, 13 skipped, 0 failures

# LLM 端到端冒烟（streaming / thinking / multimodal）
python scripts/verify_llm.py [--thinking] [--multimodal <image_path>]
```

当前文档对应代码形态已通过全量测试回归（2026-04-19，Workspace Isolation pass）。

---

## 14. ExecutionProvenance — 结构化执行来源（W1-D3）

每次 `_finalize_run` 时由 `ExecutionProvenance.build_from_stages()` 填充并挂载到 `RunResult.execution_provenance`。

```mermaid
flowchart LR
  STAGES["stage_summaries<br/>list[dict]"]
  CTX["runtime_context<br/>{runtime_mode, mcp_transport}"]
  RESOLVER["resolve_runtime_mode()<br/>server/runtime_mode_resolver.py"]
  PROV["ExecutionProvenance<br/>contracts/execution_provenance.py"]
  RESULT["RunResult.execution_provenance"]

  STAGES --> PROV
  CTX --> PROV
  RESOLVER --> CTX
  PROV --> RESULT
```

**单一真相来源原则**：`runtime_mode` 仅由 `resolve_runtime_mode(env, readiness)` 计算，`/manifest`、`/ready`、`RunResult` 三处均引用此函数，禁止各自独立计算。

| 字段 | 类型 | 说明 |
|------|------|------|
| `contract_version` | `str` | `"2026-04-17"` — 下游 schema 版本检查锚点 |
| `runtime_mode` | `Literal["dev-smoke","local-real","prod-real"]` | 由 resolver 统一计算 |
| `llm_mode` | `Literal["heuristic","real","disabled","unknown"]` | W2 填充 |
| `kernel_mode` | `Literal["local-fsm","http","unknown"]` | W2 填充 |
| `capability_mode` | `Literal["sample","profile","mcp","external","mixed","unknown"]` | W2 填充 |
| `mcp_transport` | `Literal["not_wired","stdio","sse","http"]` | 来自 mcp_transport_status |
| `fallback_used` | `bool` | 是否使用了启发式兜底 |
| `fallback_reasons` | `list[str]` | 去重排序的兜底原因 |
| `evidence` | `dict[str, int]` | `heuristic_stage_count` 等 |

---

## 15. Evolve 三态策略（W1-D2）

`TraceConfig.evolve_mode: Literal["auto","on","off"]`，旧 `evolve_enabled: bool` 保留弃用路径。

```mermaid
flowchart LR
  MODE["evolve_mode<br/>auto / on / off"]
  RM["runtime_mode<br/>dev-smoke / local-real / prod-real"]
  RESOLVER["resolve_evolve_effective()<br/>config/evolve_policy.py"]
  RESULT["(effective: bool, source: str)"]
  AUDIT["audit.evolve.explicit_on<br/>仅 on + prod-real"]

  MODE --> RESOLVER
  RM --> RESOLVER
  RESOLVER --> RESULT
  RESOLVER --> AUDIT
```

| mode | runtime_mode | effective | source |
|------|-------------|-----------|--------|
| `on` | any | `True` | `explicit_on` |
| `off` | any | `False` | `explicit_off` |
| `auto` | `dev-smoke` | `True` | `auto_dev_on` |
| `auto` | `local-real` / `prod-real` | `False` | `auto_prod_off` |

`/manifest` 返回 `evolve_policy: {mode, effective, source}`；`/ready` 返回 `evolve_source`。

---

## 16. RBAC/SOC 操作驱动授权（W1-D5）

```mermaid
flowchart TD
  REQ["HTTP Request"]
  CTX["AuthorizationContext.from_request()<br/>auth/authorization_context.py<br/>role, submitter, approver, runtime_mode"]
  DEC["@require_operation(op_name)<br/>auth/operation_policy.py"]
  BYPASS["dev_bypass<br/>→ audit.auth.bypass"]
  ROLE["role check<br/>required_roles"]
  SOC["SOC separation<br/>submitter ≠ approver"]
  ALLOW["200 OK + audit event"]
  DENY["403 Forbidden<br/>{error, operation, required_roles, reason}"]

  REQ --> CTX
  CTX --> DEC
  DEC -->|non-prod| BYPASS --> ALLOW
  DEC -->|prod| ROLE
  ROLE -->|pass| SOC
  ROLE -->|fail| DENY
  SOC -->|pass| ALLOW
  SOC -->|fail| DENY
```

| 操作 | 所需角色 | SOC 分离 | audit_event |
|------|---------|----------|-------------|
| `skill.promote` | `approver` / `admin` | ✓ | `skill.promote` |
| `skill.evolve` | `approver` / `admin` | ✓ | `skill.evolve` |
| `memory.consolidate` | `approver` / `admin` | ✗ | `memory.consolidate` |

---

## 17. SystemBuilder 子 Builder 分拆（W6 + W10-002）

```mermaid
classDiagram
  class SystemBuilder {
    -_cognition_builder: CognitionBuilder
    -_runtime_builder: RuntimeBuilder
    +build_executor(contract) RunExecutor
    +_get_cognition_builder() CognitionBuilder
    +_get_runtime_builder() RuntimeBuilder
  }
  class CognitionBuilder {
    -config: TraceConfig
    -_lock: RLock
    +build_llm_gateway() TierAwareLLMGateway
    +build_evolve_engine() EvolveEngine
    +build_reflection_orchestrator() ReflectionOrchestrator
    -_build_llm_budget_tracker()
    -_build_regression_detector()
    -_wire_cost_optimizer()
  }
  class RuntimeBuilder {
    -config: TraceConfig
    -_lock: RLock
    -parent: SystemBuilder
    +build_kernel() RuntimeAdapter
    +build_metrics_collector() MetricsCollector
    +build_middleware_orchestrator() MiddlewareOrchestrator
    +build_restart_policy_engine() RestartPolicyEngine
  }
  SystemBuilder --> CognitionBuilder : lazy getter
  SystemBuilder --> RuntimeBuilder : lazy getter
  RuntimeBuilder --> SystemBuilder : parent ref (no circular import)
```

**后置构造突变消除**：`RunExecutor.__init__` 新增 4 个可选参数（`middleware_orchestrator`, `skill_evolver`, `skill_evolve_interval`, `tracer`），builder 在 `_build_executor_impl` 阶段预计算后传入，移除了原有的 3 处 `setattr` 突变。

---

## 18. StageOrchestrator 提取（W10-001）

```mermaid
flowchart LR
  REXEC["RunExecutor.execute()"]
  CTX["StageOrchestratorContext\n{stage_graph, kernel, lifecycle, telemetry, ...}"]
  ORCH["StageOrchestrator\nexecution/stage_orchestrator.py"]
  LINEAR["run_linear()\nS1→S5 顺序遍历"]
  GRAPH["run_graph()\nDAG 含回溯"]
  RESUME["run_resume(checkpoint)\n从断点续跑"]

  REXEC --> CTX
  CTX --> ORCH
  ORCH --> LINEAR
  ORCH --> GRAPH
  ORCH --> RESUME
```

`StageOrchestratorContext` 是只读 dataclass，携带 `stage_graph`、`kernel`、`lifecycle`、`telemetry`、`route_engine` 等所有遍历依赖，消除了 `RunExecutor` 的内部字段访问耦合。

---

## 19. 能力治理扩展（W10-003 / W10-004）

### 危险能力 RBAC（W10-003）

`CapabilityInvoker.invoke()` 在调用前检查 `effect_class = "dangerous"`：调用方角色必须在 `{"approver", "admin"}` 内，否则抛 `PermissionError`，与 policy-level RBAC 叠加形成双重守卫。

### 输出预算截断（W10-004）

`CapabilityDescriptor.output_budget_tokens`（int > 0）设置输出 token 上限。`CapabilityInvoker` 在 `mark_success` 后：
1. 估算输出字符数（≈ budget × 4）
2. 超出则截断 `response["output"]` 或 `response["result"]`
3. 写入 `response["_output_truncated"] = True`

---

## 20. 审计日志与 MCP 可靠性（W10-005）

### 审计日志

```python
# hi_agent/observability/audit.py
emit(event_name: str, payload: dict) -> None
# 追加写入 ${audit_dir}/events.jsonl，每行：
# {"ts": "...", "event": "audit.auth.bypass", "payload": {...}}
```

内置事件前缀：`audit.evolve.*`、`audit.auth.*`、`audit.capability.*`。

### MCP 重启退避（W10-005）

`StdioMCPTransport` 进程崩溃时自动重启，指数退避（基础 1s，最多 5 次），超限后状态转为 `unhealthy` 并触发 release gate 失败。

### Schema 漂移注册（W10-005）

`MCPSchemaRegistry` 缓存工具列表 JSON Schema；当 MCP server 返回的 schema 与缓存不一致时，发出 `WARNING: schema drift detected for tool <name>`，不阻断调用但写入审计日志。

---

## 21. ProfileDirectoryManager 与 5 层配置（W11-001）

```mermaid
flowchart TD
  ARG["--home CLI arg"]
  ENV["HI_AGENT_HOME env"]
  DEFAULT["~/.hi_agent"]

  ARG -->|优先级 1| MGR["ProfileDirectoryManager\nprofile/manager.py"]
  ENV -->|优先级 2| MGR
  DEFAULT -->|优先级 3| MGR

  MGR --> PROFDIR["profile_dir(profile_id)"]
  MGR --> EPDIR["episodic_dir()"]
  MGR --> CKDIR["checkpoint_dir()"]
  MGR --> AUDDIR["audit_dir()"]

  subgraph STACK["ProfileAwareConfigStack\nconfig/stack.py"]
    D1["1. defaults (TraceConfig())"]
    D2["2. file (llm_config.json)"]
    D3["3. profile (profile_id overlay)"]
    D4["4. env vars"]
    D5["5. run_patch (per-run override)"]
  end

  MGR --> STACK
```

`ProfileAwareConfigStack.resolve(run_patch=None) -> TraceConfig` 按优先级从低到高合并，run_patch 为最高优先级（per-run 临时覆盖，不持久化）。

---

## 22. 发布门禁与运维（W12）

### 发布门禁（W12-002）

`build_release_gate_report(builder) -> ReleaseGateReport`，包含 7 个 `GateResult`（状态：`pass` / `fail` / `skipped` / `info`）：

```mermaid
flowchart LR
  G1["readiness\n平台就绪"]
  G2["doctor\n无 blocking issue"]
  G3["config_validation\nconfig 正常加载"]
  G4["current_runtime_mode\ninfo 信息"]
  G5["known_prerequisites\ncapability registry 非空"]
  G6["mcp_health\nMCP server 全部健康"]
  G7["prod_e2e_recent\n24h 内 prod-real 运行\n(仅 HI_AGENT_ENV=prod)"]

  G1 --> G2 --> G3 --> G4 --> G5 --> G6 --> G7
```

`check_prod_e2e_recent(max_age_hours, episodic_dir)` 扫描 `.hi_agent/episodes/*.json`，查找 `runtime_mode=prod-real` 且 `completed_at` 在窗口内的 episode；非 prod 环境 Gate 7 自动 `skipped`，不阻断本地 CI。

### Runbook 文档（W12-003 / W12-004）

`docs/runbook/` 提供以下标准运维文档：

| 文档 | 内容 |
|------|------|
| `deploy.md` | 部署流程、发布门禁检查、蓝绿切换 |
| `verify.md` | 部署后验证 checklist（/ready、/manifest、POST /runs smoke） |
| `rollback.md` | 回滚决策树、回滚步骤、数据安全检查 |
| `incident-mcp-crash.md` | MCP 进程崩溃响应流程、重启退避配置 |
| `incident-evolve-unexpected-mutation.md` | 意外进化触发响应、evolve_mode 紧急关闭 |

### 黄金路径测试（W11-002 / W12-001）

`tests/golden/dev_smoke/` 提供 dev-smoke 黄金路径 3 层测试，使用真实 `SystemBuilder`（无 mock）+ 启发式兜底：

| 层 | 测试 | 验证 |
|----|------|------|
| Unit | `test_execution_provenance.py` | ExecutionProvenance dataclass 合约 |
| Integration | `test_runner_provenance_propagation.py` | RunResult 携带正确 provenance |
| E2E (golden) | `test_dev_smoke_golden.py` | 完整 execute() 返回预期键集合 |

`tests/fixtures/` 提供 `fake_llm_http_server`、`fake_kernel_http_server`、`fake_mcp_stdio_server` — 基于 `ThreadingMixIn + HTTPServer` 绑定端口 0，可用于需要真实 HTTP 交互的集成测试。

---

## 23. 安全加固（W13 — P0/P1）

### GovernedToolExecutor（`capability/governance.py`）

所有工具调用路径的唯一治理入口，涵盖：

| 调用来源 | 路径 |
|----------|------|
| HTTP `/tools/call` | `server/routes_tools_mcp.py → GovernedToolExecutor` |
| HTTP `/mcp/tools/call` | 同上 |
| RunExecutor | `runner.py → _invoke_capability()` |
| CLI | `__main__.py → GovernedToolExecutor` |

执行顺序：CapabilityDescriptor 查找 → 运行时 profile 启用检查 → RBAC → 审批检查 → PathPolicy/URLPolicy 参数校验 → 写入预执行审计记录 → 委托原始调用器 → 写入执行结果审计记录。

### CapabilityDescriptor 风险元数据

```python
@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str
    risk_class: Literal["read_only", "filesystem_read", "filesystem_write", "network", "shell", "credential"]
    prod_enabled_default: bool
    requires_approval: bool
    remote_callable: bool
    output_budget_chars: int
```

`/manifest` 返回每个已注册能力的 `capability_views` 数组（含 `risk_class`）。prod-real 下注册无描述符的能力抛 `MissingDescriptorError`。

### PathPolicy（`security/path_policy.py`）

`safe_resolve(base_dir, user_path)` 拒绝：`../` 穿越、绝对路径（`/etc/passwd`）、符号链接逃逸、Windows UNC 路径（`\\server\share`）、drive-letter 路径（`C:\Windows`）。

### URLPolicy（`security/url_policy.py`）

`URLPolicy.validate(url)` 拒绝：`file://` 及非 http/https scheme、loopback（127.x、::1）、私有段（RFC-1918）、link-local（169.254.x.x）、云元数据 IP（169.254.169.254）、IPv4-mapped IPv6（::ffff:10.x）；重定向后重新校验目标 URL。

### ToolCallAuditEvent（`observability/audit.py`）

每次工具调用（allow/deny 均记录）产生：

```python
@dataclass
class ToolCallAuditEvent:
    event_id: str; session_id: str; run_id: str
    principal: str; tool_name: str; risk_class: str; source: str
    argument_digest: str        # sha256(redacted arguments)
    decision: Literal["allow", "deny", "approval_required"]
    denial_reason: str | None
    result_status: Literal["ok", "error", "timeout"] | None
    duration_ms: float | None; timestamp: str
```

### auth 姿态与 shell_exec 禁用

- `HI_AGENT_API_KEY` 未设置 + `runtime_mode=prod-real`：`/ready` 返回 `degraded`，`/tools/call` 返回 503。
- `prod-real` profile：`shell_exec` 不注册到 CapabilityRegistry；尝试调用返回 `CapabilityNotFoundError`。
- dev-smoke profile：`shell_exec` 可用，manifest 标注 `risk_class: shell`、`prod_enabled_default: false`。

### FallbackTaxonomy（`observability/fallback.py`）

```python
class FallbackTaxonomy(StrEnum):
    EXPECTED_DEGRADATION = "expected_degradation"
    UNEXPECTED_EXCEPTION = "unexpected_exception"
    SECURITY_DENIED = "security_denied"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    HEURISTIC_FALLBACK = "heuristic_fallback"
    POLICY_BYPASS_DEV = "policy_bypass_dev"
```

`MetricsCollector` 暴露 `fallback_count` 按分类统计；prod-real release gate 如检测到 `POLICY_BYPASS_DEV` > 0 则标记 degraded。

---

## 24. 热路径工程质量（W13 — P3/P4）

### AsyncBridgeService（`runtime/async_bridge.py`）

进程级共享 `ThreadPoolExecutor(max_workers=8, thread_name_prefix="async_bridge")`，替代 `capability/invoker.py` 和 `llm/http_gateway.py` 中每次调用创建 `ThreadPoolExecutor(max_workers=1)` 的模式：

```python
# 同步调用（带可选超时）
AsyncBridgeService.run_sync_in_thread(fn, *args, timeout=N)

# 在异步上下文中执行同步函数
await AsyncBridgeService.run_sync(fn, *args, timeout=N)
```

### HttpLLMGateway 弃用路径

`HttpLLMGateway.__init__` 在 `runtime_mode ∈ {"prod-real", "local-real"}` 时发出 `DeprecationWarning`；`TraceConfig.compat_sync_llm=False`（默认）时 `SystemBuilder` 使用异步 `HTTPGateway` 作为主路径。

### ContextManager 分段缓存

- **稳定分段**（`system`、`tools`、`skills`）：内容指纹缓存，内容不变时跳过重建。
- **动态分段**（`memory`、`history`、`reflection`）：脏标志失效机制：`add_history_entry()`、`set_reflection_context()`、`_compact_history()` 触发对应分段失效。
- 缓存命中/未命中上报 `MetricsCollector`；压缩边界重置所有缓存。

### RetrievalEngine 索引治理

新增 `_index_dirty: bool`、`_index_fingerprint: str`；`warm_index_async()` 供 server 启动时后台预热；`mark_index_dirty()` 在文档变更时调用。pickle 缓存已替换为 JSON（指纹校验 + schema 版本检查；不匹配时触发重建）。`_graph._nodes` 私有访问已替换为 `iter_nodes()` 公开接口。

### routes_tools_mcp（`server/routes_tools_mcp.py`）

`/tools`、`/tools/call`、`/mcp/tools`、`/mcp/tools/list`、`/mcp/tools/call` 路由处理器从 `app.py` 提取，治理接线随路由移动：GovernedToolExecutor 实例化在此模块内完成，`app.py` 仅注册路由表项。

### 公开 API 清理（消除跨模块私有字段访问）

| 原私有访问 | 新公开 API |
|-----------|-----------|
| `budget_tracker._max_calls`, `._total_tokens` | `LLMBudgetTracker.snapshot()` → dict |
| `graph._nodes.items()` | `LongTermMemoryGraph.iter_nodes()` → `Iterable[tuple[str, MemoryNode]]` |
| `graph._nodes.__len__` | `LongTermMemoryGraph.stats()` → `{node_count, edge_count, adjacency_keys}` |
| `route_engine._context_provider = ...` | `LLMRouteEngine.set_context_provider(provider)` |

### Memory Store Manifest Index

`ShortTermMemoryStore` 和 `MidTermMemoryStore` 均维护 `_manifest.json`：每条记录 `{id, timestamp, size_bytes}`，按时间戳降序排列，原子写入。`list_recent()` O(k)（manifest 路径），兼容无 manifest 的旧目录（O(n) 扫描回退）。

### SqliteEvidenceStore 批量 API

```python
store.store_many(events: list[EvidenceRecord]) -> None   # 单事务批量写入，失败全部回滚
with store.transaction() as conn: ...                    # 显式事务上下文
```

默认 `store()` 保持立即提交语义（审计持久性保证不变）。

---

## 25. Workspace Isolation（Workspace Isolation — Phase 1–5）

### 25.1 身份模型

```python
WorkspaceKey = NamedTuple("WorkspaceKey", tenant_id=str, user_id=str, session_id=str, team_id=str)
```

三维主键 `(tenant_id, user_id, session_id)`，`team_id` 默认为空字符串（由 `TenantContext.team_id` 填充）。`_safe_slug()` 对路径遍历字符（`..`、`/`、`\\`、`\x00`）进行 SHA-256 截断哈希，避免文件系统注入。

### 25.2 WorkspacePathHelper

```python
WorkspacePathHelper.private(base, key, *parts)
# → {base}/workspaces/{tenant}/users/{user}/sessions/{session}/{*parts}

WorkspacePathHelper.team(base, key, *parts)
# → {base}/workspaces/{tenant}/teams/{team}/{*parts}
```

所有存储层（L0/L1/L2/L3/checkpoints/retrieval-cache）均通过此 helper 计算工作区路径，存储类本身不感知工作区。

### 25.3 SessionStore / SessionMiddleware

| 组件 | 文件 | 职责 |
|------|------|------|
| `SessionStore` | `server/session_store.py` | SQLite 会话持久化（WAL），`(tenant_id, user_id, session_id)` 所有权校验 |
| `SessionMiddleware` | `server/session_middleware.py` | `X-Session-Id` 校验；缺失时自动创建并写入响应头 |
| Session 路由 | `server/routes_sessions.py` | `GET /sessions`、`GET /sessions/{id}/runs`、`PATCH /sessions/{id}` |

### 25.4 RunManager 工作区执行

- `RunManager.create_run()` 从 `WorkspaceContext` 绑定 `tenant_id / user_id / session_id`，不信任请求体中的字段。
- `get_run(run_id, workspace)` — workspace 不匹配返回 `None`（路由层返回 404）。
- `list_runs(workspace)` — 内存 + SQLite 双重过滤。
- 所有 run 路由（`GET/POST/PATCH /runs/*`、SSE `/runs/{id}/events`）均执行工作区所有权校验。

### 25.5 内存存储路径注入链

```
ManagedRun.{tenant_id, user_id, session_id}
  └─ WorkspaceKey
       └─ SystemBuilder._build_executor_impl(workspace_key)
            ├─ MemoryBuilder.build_short_term_store(workspace_key)  → L1 路径
            ├─ MemoryBuilder.build_mid_term_store(workspace_key)    → L2 路径
            ├─ MemoryBuilder.build_long_term_graph(workspace_key)   → L3 路径
            ├─ RawMemoryStore(base_dir=WorkspacePathHelper.private(..., "L0"))
            └─ RunSession(storage_dir=WorkspacePathHelper.private(..., "checkpoints"))
```

`workspace_key` 为 `None`（字段缺失或空值）时回退到原 profile_id 路径，保持向后兼容。

### 25.6 TeamEventStore / TeamSpace

| 组件 | 文件 | 职责 |
|------|------|------|
| `TeamEventStore` | `server/team_event_store.py` | SQLite WAL，`threading.Lock` 并发安全 INSERT，11 字段 `TeamEvent`（含 provenance） |
| `TeamSpace` | `server/team_space.py` | `publish(event_type, payload, ...)` — 生成 UUID event_id，调用 `TeamEventStore.insert()` |
| Team 路由 | `server/routes_team.py` | `GET /team/events?since_id=N` — 需认证，按 `team_space_id` 过滤 |

### 25.7 RunFinalizer opt-in Team Sync

```python
RunFinalizer(share_to_team=False, team_space=None, ...)
# finalize() 结束时:
if self._share_to_team and self._team_space is not None:
    self._team_space.publish(event_type="run_summary", payload={"outcome": outcome}, ...)
```

默认 `share_to_team=False`；私有会话内容不自动写入 Team Space，防止数据泄漏。

### 25.8 验收测试（1–20）

| 测试范围 | 编号 | 覆盖文件 |
|----------|------|---------|
| Run/Event 所有权隔离 | 1–10 | `tests/integration/test_workspace_isolation_phase1.py` |
| 内存存储路径隔离（L1/L2/L3/L0/checkpoint） | 11–15 | `tests/server/test_memory_isolation.py` |
| Team Space 可见性与隔离 | 16–18 | `tests/server/test_team_routes.py` |
| Legacy 行隐藏、路径遍历防护 | 19–20 | `tests/integration/test_workspace_isolation_phase2.py` |
