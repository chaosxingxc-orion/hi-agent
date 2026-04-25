# ARCHITECTURE: hi-agent (L1 Detail)

> **Architecture hierarchy**
> - L0 system boundary: [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
> - L1 hi-agent detail: this file
> - L1 agent-kernel detail: [`../agent_kernel/ARCHITECTURE.md`](../agent_kernel/ARCHITECTURE.md)

> Last updated: 2026-04-25 (Wave 9 — platform contract hardening). Full sprint history in git log.

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

## 1.1 平台姿态（Posture）

`HI_AGENT_POSTURE={dev,research,prod}` (default `dev`) — see `hi_agent/config/posture.py`. Research/prod: project_id required, durable queue/registry/ledger, fail-closed schema validation, auth-scoped idempotency. Owner tracks: CO/RO/DX/TE/GOV (see CLAUDE.md).

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

---

## 13. 质量门禁

```bash
python -m ruff check hi_agent tests scripts examples
python -m pytest -q        # 3858 passed, 13 skipped, 0 failures

# LLM 端到端冒烟（streaming / thinking / multimodal）
python scripts/verify_llm.py [--thinking] [--multimodal <image_path>]
```

当前文档对应代码形态已通过全量测试回归（2026-04-25，Wave 9 pass）。

---

## 12. 安全加固与工作区隔离（W13 + Workspace Isolation）

**W13 安全加固 (已合并):** GovernedToolExecutor (harness/executor.py), CapabilityDescriptor risk metadata (risk_class/requires_approval/provenance_required), PathPolicy/URLPolicy (harness/policies.py), shell_exec prod-default-disabled, FallbackTaxonomy, ToolCallAuditEvent, JSON-backed RetrievalEngine cache.

**WorkspaceIsolation (已合并):** WorkspaceKey/WorkspacePathHelper (workspace/), SessionStore/SessionMiddleware (server/session_middleware.py), workspace-scoped memory paths (L0–L3 + checkpoints), TeamEventStore (server/team_event_store.py), TeamSpace.publish(), GET /team/events, opt-in RunFinalizer auto-sync.

**Wave 9 平台合约加固 (已合并):** Posture enum (config/posture.py), project_id/profile_id posture-required, RunQueue/TeamRunRegistry durable under research/prod, ArtifactLedger quarantine+metric+WARNING (artifacts/ledger.py), canonical CapabilityDescriptor (capability/registry.py, DF-50 closed), TeamRunSpec (contracts/team_runtime.py), ReasoningTrace schema (contracts/reasoning_trace.py), per-kind fallback Counters (hi_agent_{llm,heuristic,capability,route}_fallback_total), structured HTTP error categories (server/error_categories.py), auth-scoped idempotency, init CLI (cli_commands/init.py).

See `docs/downstream-responses/2026-04-25-wave9-delivery-notice.md` for full Wave 9 delivery evidence.
