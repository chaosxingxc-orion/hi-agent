# TRACE Architecture — hi-agent

> 本文档严格反映代码库当前实现状态，不包含规划或愿景。
>
> 最后更新：2026-04-08 | 34,425 LOC | 252 模块 | 2,067 tests

---

## 1. 系统定位

```
hi-agent  ← 唯一智能体主体，拥有全部认知逻辑和决策权
    │
    ├── agent-kernel  ← 持久化运行时底座（Run 生命周期、TurnEngine、事件日志、幂等性）
    │                    task_manager 仅保留状态跟踪（TaskRegistry / TaskWatchdog）
    │
    └── agent-core    ← 可复用能力模块（工具、检索、MCP、工作流）
```

hi-agent 不是三个系统之一，而是系统主体。agent-kernel 是它的 durable runtime；agent-core 是它的能力来源。

---

## 2. 核心执行流

```
TRACE = Task → Route → Act → Capture → Evolve
```

```
TaskContract
    │
    ▼
RunExecutor.execute()          ← 线性 S1→S5
RunExecutor.execute_graph()    ← 动态图遍历 + backtrack + 多后继路由
RunExecutor.execute_async()    ← asyncio + AsyncTaskScheduler + KernelFacade
    │
    ├─ _execute_stage(stage_id)
    │    ├─ open_stage → mark_stage_state(ACTIVE)
    │    ├─ auto-compress (lazy compaction)
    │    ├─ knowledge retrieval injection
    │    ├─ route_engine.propose() → BranchProposal[]
    │    ├─ for each branch:
    │    │    ├─ open_branch → _invoke_capability(proposal, payload)
    │    │    ├─ acceptance_policy.decide()
    │    │    └─ mark_branch_state
    │    ├─ detect_dead_end() → 若全部失败则 abort
    │    ├─ mark_stage_state(COMPLETED)
    │    └─ _sync_to_context()  ← RunContext 双向同步
    │
    └─ _finalize_run(outcome)
         ├─ evolve_engine.analyze()
         ├─ knowledge_manager.ingest_from_session()
         └─ 返回 "completed" | "failed"
```

---

## 3. 分层架构

### 3.1 Model-Driven Management (`hi_agent/llm/` — 1,138 LOC)

```
LLMGateway (sync Protocol)        AsyncLLMGateway (async Protocol)
    │                                  │
    ├─ HttpLLMGateway (urllib)         ├─ HTTPGateway (httpx 连接池)
    ├─ AnthropicLLMGateway             └─ MockLLMGateway
    └─ MockLLMGateway
         │
    ModelRegistry (运行时注册, capability tags)
         │
    TierRouter (purpose → strong/medium/light)
         │
    ModelSelector (budget-aware, 自动降级/升级)
         │
    LLMBudgetTracker (累积消耗追踪)
```

### 3.2 Middleware Layer (`hi_agent/middleware/` — 1,226 LOC)

四个 Middleware，各自独立上下文窗口，成本节约 ~86%：

```
Perception(light ~3K) → Control(medium ~5K) → Execution(dynamic ~5K) → Evaluation(light ~2K)
```

5-phase lifecycle per middleware: `pre_create → pre_execute → execute → post_execute → pre_destroy`

Hook actions: CONTINUE | MODIFY | SKIP | BLOCK | RETRY

`MiddlewareOrchestrator` (525 LOC) 管理 add/replace/remove + 自定义路由 + Mermaid 可视化。

### 3.3 Task Management (`hi_agent/task_mgmt/` — 1,369 LOC)

```
AsyncTaskScheduler (asyncio + Semaphore 背压, O(1) pending_count)
    │
    ├─ GraphFactory → 按复杂度生成图模板
    ├─ BudgetGuard → tier 降级 + 可选节点跳过
    │
    ├─ RestartPolicyEngine → retry / reflect / escalate / abort
    │    └─ 依赖注入: get_attempts, get_policy, retry_launcher, reflection_handler
    │
    ├─ ReflectionOrchestrator → LLM 驱动的失败恢复
    │    └─ ReflectionBridge → 从失败历史构建 LLM prompt
    │
    ├─ TaskScheduler (Superstep + Yield/Resume)
    ├─ TaskCommunicator (notifications + signals + broadcast)
    └─ TaskMonitor (heartbeat + deadlock DFS 检测)
```

Plan 类型支持: Sequential / Parallel / Conditional / DependencyGraph / Speculative + `plan_to_graph()` 转换。

### 3.4 Trajectory (`hi_agent/trajectory/` — 1,381 LOC)

```
TrajectoryGraph (877 LOC)
    chain / tree / DAG / general 统一表示
    backtrack 边、条件边、Mermaid 序列化

StageGraph (312 LOC)
    transitions: dict[str, set[str]]
    backtrack_edges: dict[str, str]
    successors() / add_backtrack() / get_backtrack()
    trace_order() ← BFS 线性序
    validate() ← 可达性 + 死端 + 预算检查
```

### 3.5 Context OS

#### ContextManager (`hi_agent/context/` — 1,143 LOC)

```
7-section budget allocation
4-level health thresholds: GREEN → YELLOW → ORANGE → RED
compression fallback chain: snip → compact → trim → block
circuit breaker + diminishing returns detection

RunContext → 每 Run 可变状态容器 (dag, stage_summaries, counters, ...)
    to_dict() / from_dict() ← 序列化/反序列化
RunContextManager → 多 Run 并发状态管理
```

#### Session (`hi_agent/session/` — 494 LOC)

```
RunSession → 统一状态 + compact boundary 去重 + L0 JSONL 持久化 + checkpoint save/resume
CostCalculator → 每模型 USD 计价
```

#### Memory (`hi_agent/memory/` — 2,038 LOC)

```
L0: RawMemoryStore (event 级)
L1: MemoryCompressor (sync 字符串拼接)
    AsyncMemoryCompressor (LLM 摘要 + concat 回退)
L2: RunMemoryIndex (stage pointer)

ShortTermMemory (session 级) → DreamConsolidator → MidTermMemory (daily)
MidTermMemory → LongTermConsolidator → LongTermMemoryGraph (node+edge)

EpisodicMemoryStore → EpisodeBuilder
UnifiedMemoryRetriever → 三层检索统一入口
```

#### Knowledge (`hi_agent/knowledge/` — 1,448 LOC)

```
KnowledgeWiki (Karpathy pattern, [[wikilinks]])
UserKnowledgeStore (user profile)
LongTermMemoryGraph (structured graph)

4-layer retrieval:
  L1: grep → L2: BM25 (TFIDFIndex + HybridRanker)
  L3: graph traverse + Mermaid → L4: embedding (optional)

KnowledgeManager → auto-ingest from session
6 API endpoints
```

#### Skill (`hi_agent/skill/` — 2,063 LOC)

```
SkillDefinition (SKILL.md frontmatter + eligibility)
SkillLoader (multi-source discovery, token-budget binary search full/compact)
SkillMatcher (stage + task_family applicability)
SkillObserver (async JSONL) → SkillMetrics
SkillEvolver (textual gradient optimization, pattern → new skill)
SkillVersionManager (champion/challenger A/B traffic split)
SkillValidator + SkillUsageRecorder
5-stage lifecycle, 7 API endpoints
```

### 3.6 Route Engine (`hi_agent/route_engine/` — 1,158 LOC)

```
RuleRouteEngine → 确定性规则路由 (stage→action 映射 + skill matching)
LLMRouteEngine → LLM 结构化决策 (gateway mode + legacy callable)
HybridRouteEngine → rule first, LLM fallback (confidence threshold)
SkillAwareRouteEngine → skill 优先路由
ConditionalRouter → 条件分支路由

DecisionAuditStore + AuditTimeline → 审计追踪
AcceptancePolicy + ConfidencePolicy → 质量门控
```

### 3.7 Capability (`hi_agent/capability/` — 690 LOC)

```
CapabilityRegistry → named handler 注册表
CapabilitySpec → handler + metadata

CapabilityInvoker (sync)
    ThreadPoolExecutor timeout + max_retries + retry_exceptions
    CircuitBreaker + CapabilityPolicy (RBAC)

AsyncCapabilityInvoker (async)
    asyncio.wait_for(timeout) + 指数退避 (base_delay * 2^attempt + jitter)
    同一 CircuitBreaker + CapabilityPolicy

CircuitBreaker
    closed → open (failure_threshold) → half_open (cooldown_seconds) → closed/open
```

### 3.8 Runtime Adapter (`hi_agent/runtime_adapter/` — 3,497 LOC)

```
RuntimeAdapter Protocol (17 methods):
    Stage: open_stage, mark_stage_state
    TaskView: record_task_view, bind_task_view_to_decision
    Run: start_run, query_run, cancel_run, resume_run, signal_run
    Trace: query_trace_runtime, stream_run_events
    Branch: open_branch, mark_branch_state
    HumanGate: open_human_gate, submit_approval
    Plan: get_manifest, submit_plan

实现层:
    KernelAdapter (in-memory + optional backend, 严格状态转移验证)
    KernelFacadeAdapter (sync, 17-method → facade + execute_turn)
    AsyncKernelFacadeAdapter (async wrapper, asyncio.to_thread)
    KernelFacadeClient (direct + HTTP 双模)
    ResilientKernelAdapter (retry + circuit breaker + event buffer)
    MockKernel / MockKernelFacade (开发/测试用)

ConsistencyReconciler + ReconcileLoop → 一致性修复
AdapterHealthMonitor → 健康检查
```

### 3.9 Governance & Evolution

#### Harness (`hi_agent/harness/` — 651 LOC)

```
EffectClass: read_only | write_local | write_external | irreversible
SideEffectClass: none | internal | external_reversible | external_irreversible

HarnessExecutor → 执行前验证 + 证据采集 + 审批执行
GovernanceEngine → RetryPolicy + 审批流
EvidenceStore → 证据存储
```

#### Evolve (`hi_agent/evolve/` — 977 LOC)

```
PostmortemAnalyzer → Run 结束后分析
SkillExtractor → LLM 自动 skill 提取
RegressionDetector → 回归检测
ChampionChallenger → A/B 实验引擎
EvolveEngine → 统一进化入口
```

#### Failures (`hi_agent/failures/` — 392 LOC)

```
10 frozen failure codes:
    missing_evidence | invalid_context | harness_denied | model_output_invalid
    model_refusal | callback_timeout | no_progress | contradictory_evidence
    unsafe_action_blocked | budget_exhausted

FailureCollector → 按 Run 收集
ProgressWatchdog → 卡死检测
异常层级: TraceFailure → MissingEvidenceError, BudgetExhaustedError, ...
```

### 3.10 Server (`hi_agent/server/` — 1,015 LOC)

```
AgentServer (FastAPI-compatible)
    20+ HTTP endpoints: /runs, /memory, /knowledge, /skills, /context, /health
    EventBus (asyncio.Queue fan-out)
    SSE streaming (GET /events/stream)
    RunManager (ManagedRun lifecycle)
    MemoryLifecycleManager (定时 Dream)
```

### 3.11 Infrastructure

| Package | LOC | 说明 |
|---------|-----|------|
| `state_machine/` | 263 | Generic StateMachine + 6 TRACE 定义 (Run/Stage/Branch/Action/Wait/Review) |
| `state/` | 127 | RunStateSnapshot + RunStateStore (file persistence) |
| `recovery/` | 302 | CompensationHandler + orchestrate_recovery |
| `replay/` | 247 | 确定性重放引擎 + 验证报告 |
| `observability/` | 275 | RunMetrics + InMemoryNotificationBackend + Tracer |
| `auth/` | 252 | RBACEnforcer + JWT middleware + SOC guard |
| `events/` | 162 | EventEmitter + EventEnvelope + file-based store |
| `orchestrator/` | 379 | TaskOrchestrator + ParallelDispatcher + ResultAggregator |
| `task_decomposition/` | 821 | TaskDAG + DAGExecutor + TaskDecomposer + FeedbackLoop |
| `task_view/` | 716 | TaskView builder + token budget + auto-compress + ContextProcessorChain |
| `config/` | 649 | TraceConfig (95+ params) + SystemBuilder (full subsystem wiring) |
| `management/` | 2,693 | Ops dashboard, gate API, SLO, alerts, reconciliation, shutdown |

---

## 4. Human Gate 机制

| Gate | 触发条件 | 人工操作 |
|------|---------|---------|
| Gate A (`contract_correction`) | Task 合同需修正 | 修改 TaskContract |
| Gate B (`route_direction`) | 路径选择不确定 | 指定分支方向 |
| Gate C (`artifact_review`) | 质量分数低于阈值 | 审查/编辑产出物 |
| Gate D (`final_approval`) | 高风险终态动作 | 批准/拒绝执行 |

---

## 5. 三种执行模式

| 模式 | 方法 | 调度 | 适用场景 |
|------|------|------|---------|
| 线性 | `execute()` | `stage_graph.trace_order()` 固定序列 | 简单单 Run |
| 图驱动 | `execute_graph()` | `successors()` 动态遍历 + backtrack + route_engine 选择 | 复杂多分支 |
| 异步并发 | `execute_async()` | AsyncTaskScheduler + Semaphore + KernelFacade | 1000+ 并发 Run |

---

## 6. 模块统计

| 包 | 文件数 | LOC | 核心类 |
|----|--------|-----|--------|
| runner.py | 1 | 2,062 | RunExecutor, RunResult |
| runtime_adapter/ | 21 | 3,497 | KernelAdapter, KernelFacadeAdapter, AsyncKernelFacadeAdapter, ResilientKernelAdapter |
| management/ | 31 | 2,693 | GateAPI, ReconcileSupervisor, ShutdownManager |
| skill/ | 10 | 2,063 | SkillDefinition, SkillLoader, SkillEvolver, SkillVersionManager |
| memory/ | 11 | 2,038 | MemoryCompressor, AsyncMemoryCompressor, LongTermMemoryGraph, DreamConsolidator |
| knowledge/ | 11 | 1,448 | KnowledgeWiki, RetrievalEngine, KnowledgeManager |
| trajectory/ | 9 | 1,381 | TrajectoryGraph, StageGraph |
| task_mgmt/ | 11 | 1,369 | AsyncTaskScheduler, RestartPolicyEngine, ReflectionOrchestrator |
| middleware/ | 7 | 1,226 | MiddlewareOrchestrator, PerceptionMiddleware, ControlMiddleware |
| route_engine/ | 13 | 1,158 | HybridRouteEngine, LLMRouteEngine, ConditionalRouter |
| context/ | 3 | 1,143 | ContextManager, RunContext, RunContextManager |
| llm/ | 8 | 1,138 | HTTPGateway, ModelRegistry, TierRouter, ModelSelector |
| server/ | 5 | 1,015 | AgentServer, EventBus, RunManager |
| evolve/ | 6 | 977 | EvolveEngine, PostmortemAnalyzer, SkillExtractor |
| task_decomposition/ | 4 | 821 | TaskDAG, DAGExecutor, TaskDecomposer |
| task_view/ | 4 | 716 | TaskView, AutoCompressTrigger, ContextProcessorChain |
| capability/ | 9 | 690 | CapabilityInvoker, AsyncCapabilityInvoker, CircuitBreaker |
| harness/ | 4 | 651 | HarnessExecutor, GovernanceEngine |
| config/ | 2 | 649 | TraceConfig, SystemBuilder |
| session/ | 3 | 494 | RunSession, CostCalculator |
| failures/ | 4 | 392 | FailureCollector, ProgressWatchdog |
| orchestrator/ | 3 | 379 | TaskOrchestrator, ParallelDispatcher |
| recovery/ | 3 | 302 | CompensationHandler, orchestrate_recovery |
| observability/ | 3 | 275 | Tracer, RunMetricsRecord |
| state_machine/ | 3 | 263 | StateMachine |
| auth/ | 4 | 252 | RBACEnforcer, JWTMiddleware |
| replay/ | 4 | 247 | ReplayEngine |
| events/ | 4 | 162 | EventEmitter |
| state/ | 2 | 127 | RunStateSnapshot |
| contracts/ | 8 | 448 | TaskContract, TrajectoryNode, PolicyVersionSet |

**合计**: 232 源文件 | 34,425 LOC | 207 测试文件 | 2,067 tests
