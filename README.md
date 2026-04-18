# hi-agent

## Refresh Notes (2026-04-18 — W13 update)

- Updated validation status to `3543 passed, 13 skipped, 0 failures`.
- Added W13 security hardening: GovernedToolExecutor (central governance gate), PathPolicy (path traversal prevention), URLPolicy (SSRF prevention), CapabilityDescriptor risk metadata, auth posture degraded signal, shell_exec prod-default-disabled, FallbackTaxonomy metrics, ToolCallAuditEvent, JSON-backed RetrievalEngine cache.
- Added W13 engineering quality: AsyncBridgeService (shared ThreadPoolExecutor), ContextManager section-level cache, RetrievalEngine index governance, routes_tools_mcp.py extraction, public APIs (LLMBudgetTracker.snapshot, LongTermMemoryGraph.iter_nodes/stats, LLMRouteEngine.set_context_provider), memory store manifest index O(k), SqliteEvidenceStore batch API.
- Preserved W1–W12 sprint deliverables: ExecutionProvenance, evolve tri-state policy, RBAC/SOC auth, SystemBuilder sub-builder split, StageOrchestrator extraction, output budget enforcement, audit log, MCP schema drift, ProfileDirectoryManager, prod-real release gate, golden path tests, runbooks.

`hi-agent` 是基于 **TRACE**（Task → Route → Act → Capture → Evolve）框架构建的企业级智能体系统。  
负责任务理解、路由决策、能力执行、记忆沉淀与持续进化；底层持久化运行时由 `agent-kernel` 承载。

---

## 系统定位

| 仓库 | 职责 |
|------|------|
| `hi-agent`（本仓库） | 智能体大脑：策略、路由、执行、记忆/知识/技能、持续进化 |
| `agent-kernel` | durable runtime：run 生命周期、事件事实、幂等与恢复治理 |
| `agent-core` | 通用能力模块：工具、检索、MCP 等（集成到 hi-agent） |

---

## 架构概览

```mermaid
graph TB
  subgraph Client["客户端"]
    CLI["CLI"]
    API["HTTP Client"]
  end

  subgraph Server["API & 入口层"]
    SRV["HTTP Server<br/>/runs /knowledge /memory /skills"]
    RLM["RunManager"]
  end

  subgraph Brain["智能体大脑（hi-agent）"]
    subgraph Exec["执行层"]
      REXEC["RunExecutor"]
      STORCH["StageOrchestrator"]
      STAGE["StageExecutor"]
      LIFE["RunLifecycle"]
    end

    subgraph MW["中间件管道"]
      PERC["Perception"]
      CTRL["Control"]
      EXMW["Execution"]
      EVAL["Evaluation"]
    end

    subgraph Route["路由引擎"]
      HROUT["HybridRouteEngine<br/>Rule + LLM + Skill-Aware"]
    end

    subgraph Gov["治理层"]
      HARN["HarnessExecutor"]
      GOV["GovernanceEngine"]
      PERM["PermissionGate"]
    end

    subgraph LLM["LLM 层"]
      TIER["TierAwareLLMGateway<br/>strong / medium / light"]
      FAIL["FailoverChain"]
    end

    subgraph CKS["认知系统"]
      MEM["Memory (3-Tier)<br/>L0 Raw → L1 STM → L2 Dream → L3 Graph"]
      KNOW["Knowledge<br/>Wiki + Graph + BM25 + Embedding"]
      SKILL["Skill<br/>Registry + Loader + Evolver"]
    end

    subgraph EVO["进化引擎"]
      EVOLVE["EvolveEngine<br/>Postmortem → SkillExtract → Regression → A/B"]
    end

    subgraph OPS["运维层"]
      AUDIT["AuditLog<br/>.hi_agent/audit/events.jsonl"]
      GATE["ReleaseGate<br/>ops/release_gate.py"]
      PROF["ProfileDirectoryManager<br/>profile/manager.py"]
    end
  end

  subgraph Kernel["agent-kernel（durable runtime）"]
    KR["KernelRuntime<br/>RunLifecycle / EventLog / Idempotency"]
  end

  CLI --> SRV
  API --> SRV
  SRV --> RLM
  RLM --> REXEC

  REXEC --> STORCH
  STORCH --> STAGE
  REXEC --> LIFE
  STAGE --> MW
  MW --> PERC
  PERC --> CTRL
  CTRL --> EXMW
  EXMW --> EVAL

  CTRL --> HROUT
  EXMW --> HARN
  HARN --> GOV
  HARN --> PERM

  HROUT --> TIER
  CTRL --> TIER
  TIER --> FAIL

  STAGE --> MEM
  STAGE --> KNOW
  STAGE --> SKILL

  LIFE --> EVOLVE
  EVOLVE --> SKILL

  REXEC --> KR
  REXEC --> AUDIT
```

---

## 10 核心概念

| 概念 | 定义 |
|------|------|
| **Task** | 形式化任务契约（目标、约束、预算）`contracts/task.py` |
| **Run** | 可持久化的长时执行实体 `runner.py` |
| **Stage** | 任务推进的形式阶段（TRACE S1→S5） `runner_stage.py` |
| **Branch** | 探索空间中的逻辑轨迹 `trajectory/` |
| **Task View** | 每次模型调用前重建的最小充分上下文 `task_view/` |
| **Action** | 通过 Harness 执行的外部操作 `harness/` |
| **Memory** | 智能体经历的三层记忆（短/中/长期） `memory/` |
| **Knowledge** | 稳定知识（wiki + 图谱 + 四层检索） `knowledge/` |
| **Skill** | 可复用流程单元（5 阶段生命周期 + 版本进化） `skill/` |
| **Feedback** | 结果、评测与实验产生的优化信号 `evolve/` |

---

## 目录结构

```text
hi_agent/
  artifacts/           # ArtifactRegistry、OutputToArtifactAdapter（类型化产出物管理）
  auth/                # RBAC、JWT、SOC Guard；AuthorizationContext；operation_policy（mutation 路由守卫）
  capability/          # 能力注册、调用（同步/异步）、熔断器；output_budget_tokens 截断；dangerous RBAC；GovernedToolExecutor（中央治理入口）
  config/              # TraceConfig (95+ 参数) + SystemBuilder；CognitionBuilder；RuntimeBuilder；ProfileAwareConfigStack
  context/             # ContextManager、RunContext、RunContextManager
  contracts/           # 核心契约（Task/Run/Stage/Branch）；ExecutionProvenance（结构化执行来源）
  evaluation/          # EvaluatorRuntime（运行时评估注入）
  evolve/              # Postmortem、SkillExtractor、RegressionDetector、ChampionChallenger
  execution/           # StageOrchestrator（线性/图/恢复遍历策略）；ActionDispatcher；GateCoordinator；RunFinalizer
  failures/            # FailureCode 分类、异常、采集与恢复映射
  harness/             # HarnessExecutor、GovernanceEngine、PermissionGate、EvidenceStore
  knowledge/           # KnowledgeManager、Wiki、Graph、RetrievalEngine、TF-IDF/BM25/Embedding
  llm/                 # TierAwareLLMGateway、AnthropicLLMGateway、HttpLLMGateway、FailoverChain、PromptCacheInjector、ModelRegistry；流式/思考/多模态
  management/          # ops 运维命令（config_history、ops_timeline、ops_snapshot、runtime_config）
  mcp/                 # MCPServer、MCPHealth、MCPBinding；StdioMCPTransport（重启退避）；SchemaDriftRegistry（schema 漂移告警）
  memory/              # L0 Raw → L1 STM → L2 MidTerm → L3 LongTermGraph + Compressor + Retriever
  middleware/          # MiddlewareOrchestrator + 4 Middlewares (Perception/Control/Execution/Evaluation)
  observability/       # MetricsCollector、NotificationService、TrajectoryExporter；audit.py（emit → .hi_agent/audit/events.jsonl）；Tracer；FallbackTaxonomy（降级分类指标）
  ops/                 # diagnostics、doctor_report；ReleaseGateReport（7 门禁含 prod_e2e_recent）
  profile/             # ProfileDirectoryManager（HI_AGENT_HOME 优先链：explicit > env > ~/.hi_agent）
  profiles/            # ProfileRegistry（运行时能力 profile 管理）
  recovery/            # 补偿与恢复编排
  replay/              # 确定性回放引擎
  route_engine/        # Rule/LLM/Hybrid/SkillAware RouteEngine + DecisionAuditStore
  runtime/             # ProfileRuntimeResolver（profile → 运行时能力绑定）；AsyncBridgeService（进程级共享 ThreadPoolExecutor）
  runtime_adapter/     # RuntimeAdapter Protocol、KernelFacadeAdapter、AsyncKernelFacadeAdapter、ResilientKernelAdapter
  samples/             # TRACE 示例管道（register_trace_capabilities；S1→S5 stage 配置）
  server/              # HTTP Server（20+ 端点）、RunManager、EventBus、DreamScheduler；runtime_mode_resolver（单一真相来源）；routes_tools_mcp（工具/MCP 路由治理单元）
  session/             # RunSession、CostCalculator
  skill/               # SkillRegistry、SkillLoader、SkillMatcher、SkillEvolver、SkillVersionManager
  state_machine/       # StateMachine + 6 TRACE 状态定义
  task_mgmt/           # AsyncTaskScheduler、BudgetGuard、RestartPolicyEngine、ReflectionOrchestrator
  task_view/           # TaskView Builder、AutoCompress、TokenBudget
  task_decomposition/  # DAG/Tree/Linear 任务分解
  trajectory/          # TrajectoryGraph、StageGraph、GreedyOptimizer、DeadEndDetector
  workflows/           # WorkflowContracts（工作流契约定义）
  runner.py            # RunExecutor 主入口（execute / execute_graph / execute_async / resume）
  runner_stage.py      # StageExecutor 阶段执行委托
  runner_lifecycle.py  # 结束流程、postmortem、知识摄入、进化触发
  runner_telemetry.py  # 事件与指标记录
config/                # llm_config.json（本地，gitignore）+ llm_config.example.json（模板）
scripts/               # verify_llm.py — 流式/思考/多模态冒烟验证
tests/                 # 3543 个测试，全部通过（2026-04-18 W13 回归）
  fixtures/            # fake_llm_http_server、fake_kernel_http_server、fake_mcp_stdio_server
  golden/              # dev_smoke 黄金路径 3 层测试
  security/            # 安全拒绝路径测试（tool governance / path policy / URL policy / auth posture）
  perf/                # 性能基线测试（context cache / async bridge / retrieval warmup）
docs/                  # 架构、规格、研究文档、sprint 跟踪、runbook
  runbook/             # deploy.md、verify.md、rollback.md、incident-mcp-crash.md、incident-evolve-unexpected-mutation.md
  sprints/             # W1–W12 sprint 文档与 retro
  migration/           # contract-changes-2026-04-17.md（执行来源 + manifest + RBAC 变更通知）
```

---

## 快速开始

```bash
# 安装依赖（含 agent-kernel submodule）
git submodule update --init --recursive
python -m pip install -e ".[dev]"

# 本地执行（不依赖 server）
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# 指定 HI_AGENT_HOME（profile / episode / checkpoint 目录）
python -m hi_agent run --goal "Analyze data" --local --home /data/hi_agent

# 携带完整 TaskContract 字段本地执行
python -m hi_agent run --goal "Analyze data" --local \
  --risk-level low \
  --task-family quick_task \
  --acceptance-criteria '["required_stage:synthesize"]' \
  --constraints '["no_external_calls"]' \
  --deadline "2099-12-31T23:59:59Z" \
  --budget '{"max_llm_calls": 10}'

# 启动 API server
python -m hi_agent serve --host 127.0.0.1 --port 8080

# 从 checkpoint 恢复
python -m hi_agent resume --checkpoint checkpoint_run-001.json
```

---

## CLI 用法

```bash
# 本地执行
python -m hi_agent run --goal "Summarize logs" --local

# 远程执行
python -m hi_agent --api-host 127.0.0.1 --api-port 8080 run --goal "Summarize logs"

# 查询状态
python -m hi_agent --api-port 8080 status --run-id <run_id> --json

# 健康检查
python -m hi_agent --api-port 8080 health --json

# 进化模式控制（tri-state: auto / on / off）
HI_AGENT_EVOLVE_MODE=on python -m hi_agent run --goal "..."
```

> 注：API 请求默认超时 15 秒，可通过 `HI_AGENT_API_TIMEOUT_SECONDS` 覆盖。

---

## Public API

Minimal Python usage example:

```python
from hi_agent import RunExecutorFacade, check_readiness

report = check_readiness()
facade = RunExecutorFacade()
facade.start("run-001", profile_id="proj-A", model_tier="medium", skill_dir="skills/")
result = facade.run("Summarize the TRACE framework in one paragraph")
facade.stop()
```

---

## API 核心端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/runs` | POST | 提交任务（支持 TaskContract 全部 13 字段） |
| `/runs/{id}/events` | GET | SSE 实时事件流 |
| `/runs/{id}/resume` | POST | 从 checkpoint 恢复 |
| `/runs/{id}/resolve-escalation` | POST | 恢复 human_escalation 挂起的 run |
| `/ready` | GET | 平台就绪检查（200=ready，503=not ready；含 `evolve_source`） |
| `/manifest` | GET | 系统能力清单（`runtime_mode`、`evolve_policy`、`provenance_contract_version`、`contract_field_status`） |
| `/knowledge/ingest` | POST | 文本摄取 |
| `/knowledge/query` | GET | 知识查询 |
| `/memory/dream` | POST | 触发 Dream 整合 |
| `/memory/consolidate` | POST | 触发长期图整合（需 `approver` 角色） |
| `/skills/evolve` | POST | 触发技能进化（需 `approver` 角色） |
| `/skills/{id}/promote` | POST | Challenger → Champion（需 `approver` 角色 + SOC 分离） |
| `/context/health` | GET | 上下文预算状态 |
| `/mcp/tools/list` | POST | MCP 工具枚举 |
| `/metrics` | GET | Prometheus 格式指标 |

---

## 关键能力

### 模型分层路由与多模态 LLM
`TierAwareLLMGateway` 按任务目的自动路由：`strong`（Opus）/ `medium`（Sonnet）/ `light`（Haiku），配合 `FailoverChain` 凭证轮转与 `PromptCacheInjector` 降低成本。`complete()`（同步）、`acomplete()`（异步）、`stream()`（SSE 流式）均经由 tier 选择。

- **流式输出**：`stream()` 通过 httpx 返回 `Iterator[LLMStreamChunk]`，增量文本（`delta`）与思考过程（`thinking_delta`）分流传出。
- **Extended Thinking**：`LLMRequest(thinking_budget=N)` 开启单请求思考；`llm_config.json` 中 `features.thinking_budget` 设置 gateway 级默认值（`null` 关闭）。
- **Multimodal**：`messages[].content` 接受 content block 列表，支持图文混合输入。
- **第三方代理**：`config/llm_config.json` 通过 `api_format`（`"anthropic"` / `"openai"`）+ `base_url` 接入 DashScope 等 Anthropic 协议兼容端点，无需修改代码。

### SystemBuilder 三层分拆（W6 + W10）
`SystemBuilder` 职责拆分为三个专职 Builder，按依赖方向单向引用：

| Builder | 职责 |
|---------|------|
| `CognitionBuilder` | LLM gateway 选择（Anthropic/OpenAI/llm_config.json）、failover chain、prompt cache、budget tracker、cost optimizer、regression detector、evolve engine、reflection orchestrator |
| `RuntimeBuilder` | kernel adapter（HTTP/LocalFSM）、metrics collector、middleware orchestrator、restart policy engine |
| `SystemBuilder` | 装配协调：调用上述两个 Builder，装配 memory/knowledge/skill/harness/server；消除 3 处后置构造突变 |

`RunExecutor` 构造函数现在在 build 时直接接收 `middleware_orchestrator`、`skill_evolver`、`skill_evolve_interval`、`tracer` 四个可选参数，彻底消除后置 `setattr` 突变。

### StageOrchestrator（W10-001）
`hi_agent/execution/stage_orchestrator.py` 从 `RunExecutor` 提取遍历策略，通过 `StageOrchestratorContext` dataclass 注入依赖：
- `run_linear()` — 顺序线性遍历（S1→S5）
- `run_graph()` — 动态 DAG 遍历含回溯
- `run_resume()` — 从 checkpoint 恢复续跑

### 执行来源（ExecutionProvenance，W1-D3）
每个 `RunResult` 携带 `execution_provenance: ExecutionProvenance`，包含：

| 字段 | 说明 |
|------|------|
| `contract_version` | 固定 `"2026-04-17"`，下游用于 schema 版本检查 |
| `runtime_mode` | `dev-smoke` / `local-real` / `prod-real`（由 `runtime_mode_resolver.py` 统一计算） |
| `llm_mode` | `heuristic` / `real` / `disabled` / `unknown` |
| `fallback_used` | 是否使用了启发式兜底 |
| `fallback_reasons` | 去重排序的兜底原因列表 |
| `evidence` | `heuristic_stage_count` 等可观测指标 |

`/manifest` 同步返回 `runtime_mode`、`evolve_policy`、`provenance_contract_version`，与 `/ready` 术语对齐。

### 进化三态策略（evolve_mode，W1-D2）
`TraceConfig.evolve_mode: Literal["auto", "on", "off"]`（取代旧 `evolve_enabled: bool`）：
- `auto`：`dev-smoke` → 开启；`local-real` / `prod-real` → 关闭
- `on`：强制开启，在 prod 环境下额外写入 `audit.evolve.explicit_on` 审计事件
- `off`：强制关闭
- 旧 `evolve_enabled=True/False` 保留弃用路径，映射到 `on/off` + `DeprecationWarning`
- 环境变量 `HI_AGENT_EVOLVE_MODE` 或 CLI `--enable-evolve` / `--disable-evolve` 可覆盖

### RBAC/SOC 操作驱动授权（W1-D5）
mutation 路由受 `@require_operation(op_name)` 装饰器保护，通过 `AuthorizationContext` 从请求 header 中解析角色：

| 操作 | 所需角色 | SOC 分离 |
|------|---------|----------|
| `skill.promote` | `approver` / `admin` | 是（submitter ≠ approver） |
| `skill.evolve` | `approver` / `admin` | 是 |
| `memory.consolidate` | `approver` / `admin` | 否 |

dev-smoke 模式下自动绕过（写入 `audit.auth.bypass`）；prod-real 模式下强制执行，违反返回 `403 + reason`。

### 能力输出预算与危险 RBAC（W10-003 / W10-004）
- `CapabilityDescriptor.output_budget_tokens`：超出 budget × 4 字符时截断 response，写入 `_output_truncated: true`
- `effect_class = "dangerous"`：调用方必须持 `approver` 或 `admin` 角色，否则 `PermissionError`

### 审计日志（W1-D2 + W10-005）
`hi_agent/observability/audit.py` 提供 `emit(event_name, payload)` 函数，追加写入 `.hi_agent/audit/events.jsonl`（每行一个 JSON 事件，含 `ts`、`event`、`payload`）。内置事件：`audit.evolve.explicit_on`、`audit.auth.bypass`、`audit.auth.deny`、`audit.capability.*`。

### MCP 传输与 schema 漂移（W10-005）
- `StdioMCPTransport`：支持指数退避自动重启（最多 5 次，基础延迟 1s），隔离进程崩溃影响
- `MCPSchemaRegistry`：在工具列表响应与注册 schema 不一致时发出 `WARNING: schema drift`，不阻断调用

### ProfileDirectoryManager（W11-001）
`hi_agent/profile/manager.py` 统一管理 `HI_AGENT_HOME` 目录优先链（explicit arg > `HI_AGENT_HOME` env > `~/.hi_agent`），提供：
- `profile_dir(profile_id)`、`episodic_dir()`、`checkpoint_dir()`、`audit_dir()`

`ProfileAwareConfigStack`（`config/stack.py`）实现 5 层配置合并：defaults → 文件 → profile → env → run_patch。

### 发布门禁（W12-002）
`hi_agent/ops/release_gate.py` 提供 `build_release_gate_report(builder)` 返回 `ReleaseGateReport`，包含 7 个门禁：

| 门禁 | 说明 |
|------|------|
| `readiness` | 平台就绪状态 |
| `doctor` | 无 blocking issues |
| `config_validation` | config 正常加载 |
| `current_runtime_mode` | info：当前运行模式 |
| `known_prerequisites` | capability registry 非空 |
| `mcp_health` | MCP server 全部健康（无配置时 skipped） |
| `prod_e2e_recent` | 24h 内存在 prod-real 运行（仅 `HI_AGENT_ENV=prod` 时生效；非 prod 自动 skipped） |

### 中间件管道
`Perception → Control → Execution → Evaluation` 四中间件 + 5 阶段生命周期钩子。`MiddlewareOrchestrator` 所有结构变更均持锁执行；`run()` 入口以快照隔离，消除并发竞态。

### 认知三系统
- **记忆**：L0 原始事件 → L1 短期（会话压缩）→ L2 中期（Dream 整合）→ L3 长期（语义图谱）。
- **知识**：Wiki（`[[wikilinks]]` 风格）+ 知识图谱 + 四层检索（Grep → BM25 → Graph → Embedding）。
- **技能**：SKILL.md 定义 + `SkillLoader` token 预算注入 + `ChampionChallenger` A/B 版本管理 + `SkillEvolver` textual gradient 优化

### 持续进化
每次 run 完成后：`PostmortemAnalyzer` → `SkillExtractor`（提取候选技能）→ `RegressionDetector`（检测退化）→ `ChampionChallenger`（A/B 对比）→ 自动注册/晋升技能。

### 治理与安全（W13 安全加固）

`HarnessExecutor` 包裹所有能力调用，`GovernanceEngine` 按 `EffectClass + SideEffectClass` 双维度分级，`PermissionGate` 细粒度工具级授权，`EvidenceStore` 全量审计记录（支持 `store_many()` 批量写入 + `transaction()` 上下文管理器）。Human Gate 支持四类审批；mutation 路由受 `@require_operation` 保护。

W13 新增：
- **GovernedToolExecutor**（`capability/governance.py`）：所有工具调用路径（HTTP /tools、/mcp/tools、runner、CLI）统一收敛的治理入口，按 CapabilityDescriptor 风险等级执行 RBAC、PathPolicy、URLPolicy 检查，写入 `ToolCallAuditEvent`（allow/deny 均记录）。
- **CapabilityDescriptor 风险元数据**：`risk_class`（shell/network/filesystem_*）、`prod_enabled_default`、`requires_approval`；`/manifest` 返回每个能力的风险视图。
- **PathPolicy**（`security/path_policy.py`）：`safe_resolve()` 拒绝路径穿越（`../`）、绝对路径、符号链接逃逸、Windows UNC 路径。
- **URLPolicy**（`security/url_policy.py`）：拒绝 loopback、私有 IP、link-local、云元数据 IP（169.254.169.254）；`file://` 和非 http/https scheme 同样拒绝。
- **shell_exec 生产默认禁用**：`prod-real` profile 下不注册 `shell_exec`；尝试调用返回 `CapabilityNotFoundError`。
- **认证姿态**：`HI_AGENT_API_KEY` 未设置且 `runtime_mode=prod-real` 时 `/ready` 返回 `degraded`，`/tools/call` 返回 503。
- **FallbackTaxonomy**（`observability/fallback.py`）：6 类降级标签（`expected_degradation`、`unexpected_exception`、`security_denied` 等）；`MetricsCollector` 暴露 `fallback_count` 按分类统计。
- **AsyncBridgeService**（`runtime/async_bridge.py`）：进程级共享 `ThreadPoolExecutor(max_workers=8)`，替代每次调用创建 `ThreadPoolExecutor(max_workers=1)` 的开销。
- **ContextManager 分段缓存**：稳定分段（system/tools/skills）指纹缓存，动态分段（memory/history/reflection）脏标志失效；缓存命中/未命中上报 MetricsCollector。

---

## 开发与验证

```bash
python -m ruff check hi_agent tests scripts examples       # lint
python -m pytest -q           # 3543 passed, 13 skipped, 0 failures

# LLM 配置验证（填写 config/llm_config.json 后运行）
python scripts/verify_llm.py                            # 流式测试
python scripts/verify_llm.py --thinking                 # + 思考模式
python scripts/verify_llm.py --multimodal path/to.png   # + 多模态

# 触发 Dream 记忆整合
curl -X POST http://localhost:8080/memory/dream

# 查询知识
curl "http://localhost:8080/knowledge/query?q=revenue+trends&limit=5"

# 触发技能进化（需 approver 角色）
curl -X POST http://localhost:8080/skills/evolve \
  -H "X-Role: approver" -H "X-Submitter: alice" -H "X-Approver: bob"

# 查看发布门禁状态
curl http://localhost:8080/ready | jq '{runtime_mode, evolve_source, release_gate}'

# 查看执行来源
curl -s -X POST http://localhost:8080/runs \
  -H 'Content-Type: application/json' \
  -d '{"goal":"smoke"}' | jq '.execution_provenance'
```

---

## 依赖说明

- `agent-kernel`：通过固定 commit 引用（`git submodule`），减少 tag 漂移风险。
- Windows 安装如遇 submodule 路径问题：

```bash
python -m pip install -e ../agent-kernel --no-deps
python -m pip install -e ".[dev]"
```

---

## 参考文档

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 完整架构设计（含时序图、数据流图、接口关系图）
- [docs/sprints/](./docs/sprints/) — W1–W12 sprint 文档与 retro
- [docs/runbook/](./docs/runbook/) — deploy、verify、rollback、incident runbook
- [docs/migration/contract-changes-2026-04-17.md](./docs/migration/contract-changes-2026-04-17.md) — 执行来源 + manifest + RBAC 变更通知
- [docs/module-evolution-analysis.md](./docs/module-evolution-analysis.md)
- [docs/agent-kernel-evolution-proposal.md](./docs/agent-kernel-evolution-proposal.md)
- [docs/specs/](./docs/specs/) — 各子系统规格文档
