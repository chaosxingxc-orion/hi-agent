# hi-agent 大规模工程落地改进与实施方案

**日期**：2026-04-17  
**状态**：建议进入架构评审  
**适用范围**：`hi-agent` 当前生产工程阶段  
**对比样本**：`D:\chao_workspace\hermes-agent`、`D:\chao_workspace\claude-code-rev`

---

## 0. 执行摘要

`hi-agent` 当前已经不是一个轻量 demo。代码库约 314 个 Python 源文件、300 个测试文件，具备 `TaskContract`、`RunResult`、`/ready`、`/manifest`、`RunManager`、`SystemBuilder`、`RunExecutor`、memory/knowledge/skill/evolve 等完整平台抽象。它的主要价值在于：用 TRACE（Task -> Route -> Act -> Capture -> Evolve）建立了一套清晰的智能体平台心智模型，并已经开始用 readiness、manifest、failure code、production E2E contract 等方式约束下游集成。

但从大规模工程实施落地视角看，当前最大问题不是“模块不够多”，而是“平台抽象已经很多，真实产品闭环还不够硬”。默认路径仍以 dev heuristic fallback、in-process kernel、sample TRACE topology 为主；MCP 外部 transport 仍是 infrastructure-only；`SystemBuilder`、`RunExecutor`、`server/app.py` 等核心文件承担过多职责；真实 LLM、真实 kernel、真实 MCP、真实工具权限、真实运维链路尚未形成一条稳定、可重复、可观测、可回归的生产路径。

本方案的核心判断是：

> 接下来不要继续扩张认知子系统，而要先把一条 production-grade golden path 打穿。

建议以 12 周为一个工程周期，分五个阶段推进：

1. **边界收敛**：明确 dev-smoke、local-real、prod-real 三种运行模式，所有结果带 provenance，杜绝 fallback 成功被误认为生产成功。
2. **核心重构**：拆分 `SystemBuilder` 和 `RunExecutor` 的过重职责，建立稳定装配边界和运行时端口。
3. **真实能力面**：补齐 capability/toolset、MCP transport、权限治理、工具输出预算、artifact 与 replay。
4. **可运营闭环**：补齐 doctor、runbook、SLO gate、指标、失败诊断、配置检查和生产准入。
5. **测试与发布治理**：从“测试多”升级为“关键路径强”，建立 golden path、nightly prod E2E、覆盖率分层门槛和发布阻断策略。

---

## 1. 背景与目标

### 1.1 背景

`hi-agent` 当前定位是企业级智能体平台的大脑层，负责策略、路由、执行、记忆、知识、技能和持续进化。底层 durable runtime 由 `agent-kernel` 承载，通用能力生态由 `agent-core` 或 capability/MCP 层承载。

现有文档已经声明了较完整的平台合同：

- `README.md` 将 `hi-agent` 定义为 TRACE 企业级智能体系统。
- `ARCHITECTURE.md` 描述了 API、Execution、Middleware、Route Engine、Harness、Memory、Knowledge、Skill、Evolution、Observability 等分层。
- `docs/platform-contract.md` 定义了 readiness、task submission、result shape 等下游集成合同。
- `tests/integration/test_prod_e2e.py` 已经将生产 E2E 前置条件显式化，要求真实 LLM credentials、`HI_AGENT_ENV=prod` 和真实 `agent-kernel` HTTP endpoint。

这些方向是正确的。但当前实现中，默认可运行路径仍主要服务于研发 smoke，而不是可证明的生产运行。

### 1.2 本文档目标

本文档用于指导下一阶段工程实施，目标是把 `hi-agent` 从“平台骨架完整”推进到“生产路径可信”。

具体目标：

- 明确当前实现与大规模落地之间的差距。
- 对比 `hermes-agent` 和 `claude-code-rev`，提炼可借鉴能力。
- 给出目标架构、模块边界、实施阶段、验收标准和风险控制。
- 形成后续拆分工单、技术评审和版本规划的依据。

### 1.3 非目标

以下内容不在本轮 12 周实施范围内：

- 不重写整个 `hi-agent`。
- 不引入全新的工作流引擎替换所有现有执行逻辑。
- 不把 Hermes 或 Claude Code Rev 的代码直接移植进来。
- 不追求一次性实现所有平台能力。
- 不把 dev fallback 删除，fallback 仍可作为研发和离线 smoke 能力保留。

本轮重点是让真实路径变硬，而不是让概念面继续变宽。

---

## 2. 当前实现诊断

### 2.1 优点

#### 2.1.1 平台合同意识较强

`hi-agent` 已经有比较明确的下游集成意识。`/ready`、`/manifest`、`RunResult`、`failure_code`、`contract_field_status` 等设计，让外部系统可以判断平台能否运行、运行结果是否可消费、失败是否可归因。

这比很多 Agent 工程只返回字符串或日志要成熟得多。

#### 2.1.2 默认 dev path 诚实暴露

当前实现没有把 dev fallback 包装成生产能力。`server/app.py`、`config/builder.py`、`cli.py` 中都明确提示：

- 默认服务模式使用 dev/fallback。
- production mode 需要真实 LLM credentials。
- production mode 需要真实 kernel HTTP endpoint。
- dev smoke path 不是 formal production E2E。

这是一种健康的工程诚实。后续应该继续保持这种透明度。

#### 2.1.3 测试数量与合同测试已经初具规模

当前测试文件数量较多，并且已经覆盖了：

- server default factory E2E。
- manifest truthfulness。
- readiness consistency。
- failure attribution。
- MCP transport status consistency。
- prod E2E prerequisites。

这说明工程已经开始从“能跑”转向“可被下游信任”。

#### 2.1.4 TRACE 抽象具备长期价值

Task -> Route -> Act -> Capture -> Evolve 这条主线清晰，适合沉淀长期记忆、技能演化、路由决策、失败归因和成本优化。相比纯工具调用 loop，TRACE 更适合作为企业级任务执行框架。

### 2.2 关键不足

#### 2.2.1 默认成功不等于真实成功

当前默认 server 会设置 `HI_AGENT_ENV=dev`，使用 heuristic fallback 和 in-process LocalFSM，以便开箱可跑。这对研发体验有价值，但对生产落地是最大误导源。

风险表现：

- 下游集成方看到 `POST /runs -> completed`，但实际上没有真实 LLM、真实 kernel、真实工具能力参与。
- 测试可以在 fallback 下全部通过，但不能证明 prod path 可用。
- 工程团队容易把“smoke path 稳定”误认为“系统可交付”。

需要将结果 provenance 变成一等字段，而不是只靠文档说明。

#### 2.2.2 `SystemBuilder` 成为装配黑洞

`hi_agent/config/builder.py` 同时承担：

- kernel 构建。
- LLM gateway 构建。
- capability registry/invoker 构建。
- harness 构建。
- MCP registry/transport/plugin wiring。
- skill loader/evolver。
- memory/knowledge/retrieval。
- context manager/budget guard。
- profile registry/runtime resolver。
- executor/server/readiness。

这导致：

- 生命周期不清晰。
- 单元测试容易绕过真实装配。
- 局部改动容易影响全局状态。
- 热更新和多 profile 隔离困难。
- 后构造注入变多，类型和依赖边界不稳定。

#### 2.2.3 `RunExecutor` 职责过载

`hi_agent/runner.py` 是核心执行器，但当前已经承担太多责任：

- run lifecycle。
- stage graph execution。
- recovery/backtrack。
- human gate。
- subrun delegation。
- async execution。
- memory finalization。
- evolve engine。
- telemetry。
- checkpoint/resume。
- failure collection。

这类 God Object 在大规模团队协作时会成为高冲突、高回归风险文件。后续每加一个平台能力，都可能继续往 `RunExecutor` 塞分支。

#### 2.2.4 MCP 仍停留在 infrastructure-only

当前 readiness 和 manifest 已明确 MCP 外部 transport 未完成。平台可以用 MCP-compatible endpoint 暴露内部 capabilities，但还不是完整 MCP client/provider。

企业落地中，MCP 是工具生态接入的主路径之一。缺少真实 transport、auth、health、schema versioning、tool forwarding，会导致平台很难接入真实工具链。

#### 2.2.5 工具/能力层缺少产品化治理

相比 Hermes 和 Claude Code Rev，`hi-agent` 的 capability 抽象偏“内部执行能力”，缺少面向产品使用的工具治理面：

- toolset enable/disable。
- tool availability。
- required env。
- per-tool output budget。
- dangerous action approval。
- profile-scoped state path。
- background process tracking。
- tool schema cross-reference 防幻觉策略。
- sandbox/permission mode。

这些能力看起来偏“外围”，但在真实 agent 产品中是稳定性和安全性的核心。

#### 2.2.6 测试体系仍需从数量转向关键路径强度

现有测试数量不少，但仍存在三个问题：

- coverage threshold 只有 65，对平台内核偏低。
- 真实 prod E2E 依赖环境，默认跳过，缺少持续性信号。
- 很多测试是在修补合同缺口后追加，说明历史上存在运行路径与文档/设计不一致。

后续应增加“不可绕过”的 golden path 测试，而不是只继续增加局部单测。

---

## 3. 对比样本带来的启发

### 3.1 Hermes Agent：产品闭环优先

Hermes 的架构不一定更优雅，甚至存在大文件和同步主循环问题，但它的工程落地能力明显更完整。

值得借鉴：

- **真实用户入口**：CLI、Telegram、Discord、Slack、WhatsApp、Signal 等 gateway。
- **工具生态**：tool registry、toolsets、availability check、requirements。
- **会话体系**：SQLite + FTS5，支持 session search、resume、title、branch。
- **后台进程**：process registry、poll、wait、kill、crash recovery、gateway notification。
- **多实例隔离**：`HERMES_HOME` profile 机制，配置、密钥、memory、sessions、skills 隔离。
- **安全审批**：dangerous command detection、session approval、permanent allowlist、gateway approval。
- **运营命令**：setup、doctor、gateway、model、tools、skills、update。

Hermes 的启发是：

> Agent 平台能不能落地，不只取决于推理链路，而取决于“用户每天怎么用、出了错怎么诊断、长期运行怎么恢复”。

### 3.2 Claude Code Rev：客户端操作系统能力

`claude-code-rev` 是恢复版源码，不宜作为质量标杆。它明确存在 shims、degraded implementations、`strict=false` 等风险。但它展示了一个成熟 CLI agent 产品需要面对的复杂边界。

值得借鉴：

- **CLI 参数体系**：print/json/stream-json、input-format、permission-mode、tools、allowed/disallowed tools、MCP config、system prompt、resume、worktree、remote。
- **权限与沙箱**：permission mode、bypass permissions、sandbox manager、bash security。
- **MCP 体系**：config、client、auth、OAuth、connection manager。
- **远程与工作区**：SSH、remote session、worktree、tmux。
- **TUI 状态管理**：REPL、notifications、overlay、task state。
- **自动压缩与上下文管理**：compact、micro compact、auto compact。

Claude Code Rev 的启发是：

> 工程 agent 的难点不是“调用模型”，而是管理会话、权限、上下文、工具、远程环境、失败恢复和用户交互状态。

### 3.3 对 `hi-agent` 的定位修正

`hi-agent` 不应该照搬 Hermes 的产品形态，也不应该照搬 Claude Code 的 TUI 架构。更合理的定位是：

- 继续保留 TRACE 作为核心智能体编排框架。
- 用 Hermes 的产品闭环补齐用户和运营面。
- 用 Claude Code 的权限、MCP、会话、工具边界补齐工程 agent 能力面。
- 将三者融合成一个“可集成、可运营、可证明”的 agent platform。

---

## 4. 目标架构

### 4.1 总体原则

后续架构调整遵循五个原则：

1. **真实路径优先**：任何平台能力都必须说明 dev-smoke、local-real、prod-real 下的行为差异。
2. **合同先行**：每个对外接口必须有 result shape、error shape、readiness shape 和 provenance。
3. **装配显式**：核心依赖必须通过明确 constructor 或 provider 注入，减少 post-construction mutation。
4. **能力可运营**：每个 capability/tool 必须可枚举、可诊断、可禁用、可审计。
5. **测试锁边界**：每个核心边界必须有 golden path 和 failure path 测试。

### 4.2 目标分层

建议将平台拆成六个清晰层次。

#### 4.2.1 API & Interface Layer

职责：

- HTTP API。
- CLI。
- SSE/streaming。
- machine-readable result。
- readiness/manifest/doctor。

不应承担：

- 运行时装配细节。
- capability 注册细节。
- memory/evolve 内部流程。

目标文件方向：

- `hi_agent/server/app.py` 只保留 ASGI app、route registration、request/response adapter。
- endpoint handler 按域拆分到 `hi_agent/server/routes/`。
- `AgentServer` 缩减为 server composition root，而不是所有子系统持有者。

#### 4.2.2 Runtime Composition Layer

职责：

- 从配置构建 runtime graph。
- 校验 prod prerequisites。
- 管理 singleton lifecycle。
- 输出 readiness probes。

建议拆分：

- `RuntimeBuilder`：kernel、run store、event store、scheduler。
- `CognitionBuilder`：LLM、route、context、memory、knowledge、skill。
- `CapabilityPlaneBuilder`：capability registry、toolset、MCP、harness、permissions。
- `ServerBuilder`：HTTP/SSE/metrics/auth。
- `ReadinessProbe`：统一探测实际 runtime。

#### 4.2.3 Execution Layer

职责：

- run lifecycle。
- stage graph traversal。
- action dispatch。
- recovery/gate/delegation。
- result finalization。

建议拆分：

- `RunCoordinator`：一次 run 的生命周期主控。
- `StageOrchestrator`：stage graph、stage selection、backtrack。
- `ActionDispatcher`：route proposal -> action spec -> harness/capability result。
- `GateCoordinator`：human gate 注册、pending、resume。
- `RecoveryCoordinator`：failure classification、retry/backtrack/escalation。
- `RunFinalizer`：artifact、memory、evolve、telemetry finalization。

`RunExecutor` 可以保留为 facade，避免一次性破坏所有调用方。

#### 4.2.4 Capability Plane

职责：

- capability registry。
- tool schema。
- toolset。
- availability。
- permissions。
- output budget。
- MCP forwarding。
- audit。

核心合同：

```python
CapabilityDescriptor(
    name: str,
    kind: Literal["internal", "mcp", "external"],
    toolset: str,
    risk_class: str,
    side_effect_class: str,
    availability: AvailabilityStatus,
    required_env: list[str],
    schema_version: str,
    output_budget_chars: int,
)
```

后续所有工具都应从 capability descriptor 派生 manifest、MCP schema、permission rules 和 readiness。

#### 4.2.5 Cognitive State Layer

职责：

- context。
- memory。
- knowledge。
- skills。
- compression。
- retrieval。
- evolution。

需要收敛的点：

- memory 与 knowledge 边界要更清晰：memory 是经验，knowledge 是稳定事实。
- evolve 不应默认影响生产路径，必须通过 experiment gate 或 profile policy 开启。
- skill evolution 需要 champion/challenger 的真实指标，不应只依赖启发式成功。

#### 4.2.6 Ops & Governance Layer

职责：

- metrics。
- tracing。
- cost。
- SLO gate。
- runbook。
- audit。
- config validation。
- release gate。

目标是让平台从“开发者能调试”变成“运维能接管”。

---

## 5. 关键改进主题

### 5.1 运行模式与 provenance

#### 问题

当前 dev fallback 是必要的，但 fallback 结果容易被误读。

#### 目标

每一次 run、每一个 stage、每一个 action 都明确标注执行来源。

建议新增字段：

```json
{
  "execution_provenance": {
    "runtime_mode": "dev-smoke | local-real | prod-real",
    "llm_mode": "heuristic | real | disabled",
    "kernel_mode": "local-fsm | http",
    "capability_mode": "sample | profile | mcp | external",
    "mcp_transport": "not_wired | stdio | sse | http",
    "fallback_used": true,
    "fallback_reasons": ["missing_llm_gateway"]
  }
}
```

#### 实施要点

- `TraceConfig` 增加明确的 `runtime_mode`。
- `SystemBuilder.readiness()` 输出同一套 provenance vocabulary。
- `RunResult` 增加顶层 provenance。
- `StageSummary` 增加 stage-level provenance。
- `CapabilityInvoker` 返回 capability-level provenance。
- `/manifest` 声明哪些 endpoint 能产生真实 prod result。

#### 验收标准

- dev fallback 下，任何 completed run 都带 `fallback_used=true`。
- prod mode 下，fallback 被禁用；缺少真实依赖时返回 503 或 failed，不返回 heuristic success。
- 测试能断言 dev success 与 prod success 的区别。

### 5.2 装配层重构

#### 问题

`SystemBuilder` 职责过重，后构造注入较多。

#### 目标

把平台装配拆成可测试、可替换、可诊断的多个 builder/provider。

#### 建议结构

```text
hi_agent/config/
  runtime_builder.py
  cognition_builder.py
  capability_builder.py
  server_builder.py
  readiness_probe.py
  builder.py                  # backward-compatible facade
```

#### 迁移策略

第一步不删除 `SystemBuilder`，而是让它变成 facade：

```python
class SystemBuilder:
    def __init__(...):
        self.runtime = RuntimeBuilder(...)
        self.cognition = CognitionBuilder(...)
        self.capabilities = CapabilityPlaneBuilder(...)
        self.server = ServerBuilder(...)
        self.readiness_probe = ReadinessProbe(...)
```

旧方法保留，但内部委托到新 builder。

#### 验收标准

- `SystemBuilder.build_executor()` 外部行为不变。
- `build_llm_gateway()`、`build_kernel()`、`build_invoker()` 迁移后仍通过现有测试。
- 每个新 builder 有独立 readiness probe。
- 不再通过直接修改 executor 内部私有属性完成关键装配。

### 5.3 执行器拆分

#### 问题

`RunExecutor` 过重，后续继续扩展会提高回归风险。

#### 目标

将执行流程拆为可组合的 coordinator，同时保留 `RunExecutor` 兼容入口。

#### 建议结构

```text
hi_agent/execution/
  run_coordinator.py
  stage_orchestrator.py
  action_dispatcher.py
  gate_coordinator.py
  recovery_coordinator.py
  run_finalizer.py
  execution_provenance.py
```

#### 第一阶段拆分顺序

1. 提取 `ExecutionProvenance` 数据结构。
2. 提取 `GateCoordinator`，承接 gate registry、pending、resume。
3. 提取 `ActionDispatcher`，承接 route proposal 到 harness/capability invocation。
4. 提取 `RunFinalizer`，承接 `_finalize_run` 中 memory/evolve/artifact/telemetry。
5. 提取 `StageOrchestrator`，承接 `execute_graph` 和 stage traversal。

#### 验收标准

- `RunExecutor.execute()` 返回 shape 不变。
- gate resume 测试不变。
- forced failure 测试不变。
- graph execution 测试不变。
- 每提取一个 coordinator，增加独立单元测试和一条 executor-level 集成测试。

### 5.4 Capability Plane 产品化

#### 问题

当前 capability 更像内部函数注册表，缺少工具生态治理能力。

#### 目标

建立统一 Capability Plane，使内部 capability、MCP tool、外部工具都能被同一套合同治理。

#### 关键能力

- toolset enable/disable。
- capability availability。
- required env / credentials。
- risk class。
- side effect class。
- permission policy。
- output size limit。
- schema version。
- audit event。
- profile-scoped state。

#### 建议新增模块

```text
hi_agent/capability_plane/
  descriptor.py
  toolset.py
  availability.py
  permissions.py
  output_budget.py
  audit.py
  manifest_adapter.py
  mcp_adapter.py
```

#### 与现有模块关系

- `hi_agent/capability/registry.py` 保留为低层 registry。
- 新增 `CapabilityPlane` 作为上层治理面。
- `HarnessExecutor` 从 `CapabilityPlane` 获取 permission 和 audit metadata。
- `/manifest` 从 `CapabilityPlane` 生成 capabilities。
- MCP tools/list 从 `CapabilityPlane` 生成 schema。

#### 验收标准

- 每个 capability 都有 descriptor。
- `/manifest.capabilities` 不再只是字符串列表，可输出详细状态。
- disabled/unavailable capability 不会被 route engine 选中。
- 工具执行结果超过预算时被裁剪并标记。

### 5.5 MCP 真实 transport

#### 问题

当前 MCP provider/client 能力不完整，外部 transport 未接入。

#### 目标

实现最小可用 MCP transport，并纳入 readiness 和 capability plane。

#### 第一阶段范围

优先实现 stdio transport，因为它最常见、最容易做本地集成测试。

能力要求：

- 读取 MCP server 配置。
- 启动 stdio 子进程。
- 发送 initialize。
- 发送 tools/list。
- 发送 tools/call。
- 处理超时、退出、stderr。
- 将 healthy tools 注册为 capability。
- 将 unhealthy tools 标记为 unavailable，而不是注册 broken stub。

#### 后续范围

- SSE transport。
- HTTP transport。
- OAuth/token。
- per-server permission。
- enterprise allowlist。

#### 验收标准

- 使用一个本地 fake MCP stdio server 完成 tools/list 和 tools/call。
- `/mcp/status` 显示 `transport_status=stdio`。
- `/manifest.e2e_contract.mcp_provider.status` 从 `infrastructure_only` 变成 `available`。
- MCP server crash 后 readiness 降级，run 不崩溃。

### 5.6 生产 E2E golden path

#### 问题

现有 prod E2E 设计正确，但默认 skip，不能作为日常质量信号。

#### 目标

建立三类 golden path：

1. **dev-smoke golden path**：无外部依赖，确认平台基本可跑。
2. **local-real golden path**：使用本地 fake LLM server + fake kernel HTTP server + fake MCP server。
3. **prod-real golden path**：使用真实 LLM + 真实 kernel endpoint，nightly 或 release gate 执行。

#### local-real 的价值

local-real 不依赖真实供应商，也不使用 heuristic fallback。它用可控 fake server 模拟真实协议，验证真实网络边界、序列化、错误处理和重试逻辑。

#### 验收标准

- CI 默认跑 dev-smoke 和 local-real。
- nightly 跑 prod-real，缺少 secrets 时明确 skipped，不影响 PR。
- release 前必须有最近一次 prod-real 通过记录。

### 5.7 可运营化

#### 问题

当前已有 health、ready、metrics、manifest，但缺少完整操作员体验。

#### 目标

让非核心开发者也能判断平台为什么不可用、如何修复、修复后如何验证。

#### 建议新增能力

- `python -m hi_agent doctor`
- `GET /doctor`
- `GET /ops/runbook`
- `GET /ops/release-gate`
- `GET /ops/config`
- `GET /ops/dependencies`

#### doctor 输出结构

```json
{
  "status": "degraded",
  "blocking": [
    {
      "subsystem": "llm",
      "code": "missing_credentials",
      "message": "Production mode requires OPENAI_API_KEY or ANTHROPIC_API_KEY",
      "fix": "Set env var or configure config/llm_config.json",
      "verify": "python scripts/verify_llm.py"
    }
  ],
  "warnings": [],
  "next_steps": []
}
```

#### 验收标准

- prod mode 缺少 kernel URL 时，doctor 给出明确修复命令。
- prod mode 缺少 LLM key 时，doctor 给出明确修复命令。
- MCP server 配置错误时，doctor 给出 server name、transport、stderr 摘要。
- release gate 可基于 readiness、最近 E2E、SLO、队列风险输出 pass/fail。

---

## 6. 分阶段实施路线

### 阶段 0：基线冻结与事实清单

**周期**：第 1 周  
**目标**：先建立可比较基线，避免重构期间不知道是否退化。

#### 工作项

- 记录当前测试基线：全量 pytest、ruff、coverage。
- 记录当前 `/ready`、`/manifest`、`/health` 样例输出。
- 记录当前 dev server `POST /runs` 的结果 shape。
- 记录当前 prod prerequisites 缺失时的错误行为。
- 建立 `docs/platform/current-runtime-baseline-2026-04-17.md`。

#### 验收

- 基线文档包含命令、输出摘要、失败/skip 原因。
- 后续阶段所有变更都能与该基线对比。

### 阶段 1：运行模式与 provenance

**周期**：第 2-3 周  
**目标**：先让系统诚实、机器可读地区分 smoke 与 real。

#### 工作项

- 增加 `RuntimeMode`：`dev_smoke`、`local_real`、`prod_real`。
- 增加 `ExecutionProvenance` 数据结构。
- `RunResult`、`StageSummary`、capability result 增加 provenance。
- `/ready` 与 `/manifest` 统一 provenance vocabulary。
- dev fallback 下所有 heuristic result 标记 `_heuristic=true` 和 `fallback_used=true`。
- prod mode 禁止 heuristic success。

#### 验收

- dev path 测试明确断言 `fallback_used=true`。
- prod missing prerequisites 测试明确断言返回 503 或 failed。
- manifest 中 e2e contract 与 readiness 中 runtime mode 不矛盾。

### 阶段 2：装配层拆分

**周期**：第 4-5 周  
**目标**：降低 `SystemBuilder` 复杂度，建立可测试装配边界。

#### 工作项

- 新增 `RuntimeBuilder`，迁移 kernel/run/event/scheduler 构建。
- 新增 `CognitionBuilder`，迁移 LLM/context/memory/knowledge/skill。
- 新增 `CapabilityPlaneBuilder`，迁移 capability/harness/MCP/plugin wiring。
- 新增 `ReadinessProbe`，统一 readiness 逻辑。
- `SystemBuilder` 保留 facade，旧测试不改或少改。

#### 验收

- `SystemBuilder` 外部 API 兼容。
- 每个 builder 有独立单测。
- server default factory E2E 通过。
- readiness 仍读取 live builder，不创建假快照。

### 阶段 3：RunExecutor 拆分

**周期**：第 6-7 周  
**目标**：把执行器从 God Object 拆成稳定 coordinator。

#### 工作项

- 提取 `GateCoordinator`。
- 提取 `ActionDispatcher`。
- 提取 `RunFinalizer`。
- 提取 `RecoveryCoordinator`。
- 提取 `StageOrchestrator`。
- `RunExecutor` 作为兼容 facade。

#### 验收

- graph execution、gate resume、forced failure、failure attribution 全部通过。
- `RunExecutor` 行数明显下降。
- 新 coordinator 都有直接测试。
- 不新增跨 coordinator 私有属性互相修改。

### 阶段 4：Capability Plane 与 MCP stdio

**周期**：第 8-10 周  
**目标**：补齐真实工具生态的最小闭环。

#### 工作项

- 增加 capability descriptor。
- 增加 toolset registry。
- 增加 availability probe。
- 增加 permission policy adapter。
- 增加 output budget。
- 实现 MCP stdio transport。
- fake MCP server fixture。
- `/mcp/status`、`/mcp/tools/list`、`/manifest` 对齐真实状态。

#### 验收

- MCP stdio fake server tools/list + tools/call 通过。
- broken MCP server 不注册 broken stub。
- disabled tool 不出现在可调用列表。
- capability descriptor 覆盖全部默认 TRACE capabilities。

### 阶段 5：运营闭环与发布治理

**周期**：第 11-12 周  
**目标**：让平台可诊断、可发布、可回滚。

#### 工作项

- CLI `doctor`。
- HTTP `/doctor`。
- `/ops/release-gate`。
- `/ops/dependencies`。
- runbook 文档。
- nightly prod E2E workflow。
- release checklist。

#### 验收

- 缺少 LLM、kernel、MCP 时 doctor 给出明确修复建议。
- release-gate 能阻断 readiness degraded、prod E2E 过期、SLO 失败。
- 文档包含部署、验证、回滚步骤。

---

## 7. 测试策略

### 7.1 测试分层

#### Layer 1：Unit

目标：

- 小对象、小函数、小 coordinator。
- 不依赖外部网络。
- mock 只用于外部 HTTP 或故障注入。

重点：

- `ExecutionProvenance` merge/serialization。
- `ReadinessProbe` decision。
- `CapabilityDescriptor` validation。
- `PermissionPolicy` decision。
- `OutputBudget` truncation。

#### Layer 2：Integration

目标：

- 真实组件组装。
- 不 mock 内部子系统。
- 使用 fake external server 模拟外部协议。

重点：

- `RuntimeBuilder + CognitionBuilder + CapabilityPlaneBuilder`。
- `RunCoordinator + StageOrchestrator + ActionDispatcher`。
- fake LLM HTTP server。
- fake kernel HTTP server。
- fake MCP stdio server。

#### Layer 3：E2E

目标：

- 通过公共接口验证。
- CLI、HTTP、SSE 都要覆盖。

重点：

- `POST /runs -> GET /runs/{id} -> artifacts -> events`。
- `python -m hi_agent run --local-real`。
- `python -m hi_agent doctor`。
- prod prerequisites missing。
- prod real nightly。

### 7.2 覆盖率目标

建议分三步提高：

- 第一阶段：全局 `fail_under=70`。
- 第二阶段：核心包单独门槛 80，包括 execution、config、capability_plane、server。
- 第三阶段：新增代码覆盖率 85，核心 failure path 必须覆盖。

### 7.3 关键回归场景

必须固定为长期回归：

- dev fallback completed 但 provenance 明确标记 fallback。
- prod missing LLM 不允许 heuristic success。
- prod missing kernel 不允许 LocalFSM fallback。
- MCP configured but unreachable 不注册 callable tool。
- route engine 不选择 unavailable capability。
- failed run 必有 failure_code 和 failed_stage_id。
- run.state 与 result.status 不矛盾。
- gate pending 可 resume。
- config reload 不影响 in-flight run。
- output 超预算被裁剪且标记。

---

## 8. 发布与运维策略

### 8.1 发布准入

每次 release 必须满足：

- ruff 通过。
- pytest 全量通过。
- dev-smoke golden path 通过。
- local-real golden path 通过。
- 最近一次 prod-real nightly 通过或人工豁免。
- `/ready` 在目标环境为 ready。
- `/doctor` 无 blocking issue。
- `/ops/release-gate` pass。

### 8.2 发布分级

#### Patch Release

适用：

- bug fix。
- 文档修复。
- 小范围测试补充。

准入：

- affected tests + full tests。
- 不要求新增 migration。

#### Minor Release

适用：

- 新 endpoint。
- 新 capability descriptor 字段。
- 新 runtime mode。
- MCP transport 新能力。

准入：

- full tests。
- local-real golden path。
- manifest contract 更新。

#### Major Release

适用：

- RunResult shape breaking change。
- TaskContract breaking change。
- profile/runtime config breaking change。

准入：

- migration guide。
- compatibility adapter。
- downstream impact review。

### 8.3 回滚策略

每个阶段都必须可回滚：

- 新 builder 通过 facade 接入，保留旧方法。
- 新 executor coordinator 通过 feature flag 或 config 控制。
- MCP transport 默认可关闭。
- prod mode enforcement 可以先 warn，再 fail close。
- manifest 新字段 additive，不移除旧字段。

---

## 9. 风险与缓解

### 9.1 重构范围过大

风险：

- 一次性拆 `SystemBuilder` 和 `RunExecutor` 可能造成大量回归。

缓解：

- facade 优先。
- 每次只迁移一个职责。
- 每个迁移点保留旧测试。
- 先加 characterization tests，再动代码。

### 9.2 文档与实现再次漂移

风险：

- manifest/readiness 文档写得很完整，但实现没有同步。

缓解：

- 文档中的关键合同必须由测试断言。
- `/manifest` 输出作为 snapshot/golden 测试。
- platform contract 每次变更必须更新测试。

### 9.3 fallback 语义继续污染生产判断

风险：

- 开发人员为了方便又在 prod path 中启用 fallback。

缓解：

- prod mode 默认 fail close。
- `HI_AGENT_ALLOW_HEURISTIC_FALLBACK` 在 prod 下无效，除非显式 emergency override。
- emergency override 必须进入 audit log。

### 9.4 MCP transport 引入进程管理复杂度

风险：

- stdio server 子进程泄漏、阻塞、stderr 未消费、工具调用挂死。

缓解：

- 所有 transport 调用必须有 timeout。
- 子进程必须有 lifecycle owner。
- stderr tail 进入 health report。
- server crash 后自动标记 unavailable。

### 9.5 过度产品化影响核心研究速度

风险：

- 过早引入复杂运营体系，拖慢 TRACE 研究迭代。

缓解：

- 将 dev-smoke 与 prod-real 清晰分离。
- 研究路径可继续快速 fallback。
- 生产路径必须严格准入。
- 用 profile/policy 控制 evolve、skill auto-promotion 等实验能力。

---

## 10. 组织推进建议

### 10.1 工作流

建议采用阶段性 RFC + 小 PR 的方式：

1. 每个阶段先写 mini-RFC。
2. RFC 明确目标、非目标、合同变化、测试计划。
3. 每个 PR 只迁移一个边界或新增一个可测能力。
4. 每个 PR 都更新 docs 或 manifest contract。
5. 每周做一次 runtime truth review：文档、manifest、ready、tests 是否一致。

### 10.2 责任边界

建议按模块设 owner：

- Runtime owner：kernel、run lifecycle、scheduler、state。
- Capability owner：registry、toolset、MCP、permission、harness。
- Cognition owner：LLM、route、context、memory、knowledge、skill。
- Server/Ops owner：HTTP、SSE、readiness、doctor、metrics、release gate。
- QA owner：golden path、prod E2E、coverage、contract tests。

### 10.3 决策机制

以下变更必须经过架构评审：

- `TaskContract` 字段语义变化。
- `RunResult` shape 变化。
- runtime mode 行为变化。
- prod fallback 策略变化。
- MCP schema/versioning 变化。
- permission policy 默认行为变化。

---

## 11. 里程碑

### M1：Runtime Truth

目标日期：第 3 周结束  
交付物：

- runtime mode。
- execution provenance。
- dev/prod fallback 区分。
- readiness/manifest 对齐。

成功标准：

- 下游系统可以机器读取 run 是否真实执行。

### M2：Composable Runtime

目标日期：第 5 周结束  
交付物：

- builder 拆分。
- readiness probe 拆分。
- `SystemBuilder` facade 兼容。

成功标准：

- 装配层职责清晰，可独立测试。

### M3：Composable Execution

目标日期：第 7 周结束  
交付物：

- gate/action/finalizer/recovery/stage coordinator。
- `RunExecutor` facade 兼容。

成功标准：

- 核心执行器不再继续膨胀，新增能力有明确落点。

### M4：Real Tool Plane

目标日期：第 10 周结束  
交付物：

- capability descriptor。
- toolset。
- MCP stdio。
- permission/output budget。

成功标准：

- 至少一个外部 MCP tool 真实可调用，并纳入 readiness/manifest。

### M5：Operable Platform

目标日期：第 12 周结束  
交付物：

- doctor。
- release gate。
- local-real/prod-real golden path。
- runbook。

成功标准：

- 平台具备生产准入、诊断、回滚和发布治理能力。

---

## 12. 首批建议工单

### P0：防止 fallback 被误判为生产成功

- 增加 `ExecutionProvenance`。
- `RunResult` 增加 provenance。
- dev fallback 标记 `fallback_used=true`。
- prod 禁止 heuristic success。

### P0：建立 local-real golden path

- fake LLM HTTP server。
- fake kernel HTTP server。
- fake MCP stdio server。
- public HTTP E2E。

### P1：拆分 `SystemBuilder`

- 先提取 `RuntimeBuilder`。
- 再提取 `CapabilityPlaneBuilder`。
- 最后提取 `CognitionBuilder` 和 `ReadinessProbe`。

### P1：提取 `RunFinalizer`

- 从 `_finalize_run` 中拆出 memory/evolve/artifact/telemetry。
- 固化 failed/completed/cancelled 行为。

### P1：MCP stdio 最小闭环

- stdio transport。
- tools/list。
- tools/call。
- health probe。
- manifest/readiness 对齐。

### P2：doctor 与 release gate

- CLI doctor。
- HTTP doctor。
- release gate。
- runbook。

---

## 13. 最终判断

`hi-agent` 当前已经具备平台化的骨架和正确的长期方向，但还没有形成足够硬的生产运行闭环。现在最危险的事情是继续堆新概念：更多 memory 层、更多 evolve 策略、更多路由器、更多抽象接口。更正确的路径是收敛到一条真实 production-grade golden path，用 provenance、builder 边界、execution coordinator、capability plane、MCP transport、doctor 和 release gate 把这条路径做硬。

短期目标不是成为 Hermes，也不是复刻 Claude Code。短期目标是让 `hi-agent` 的每一次成功都能回答四个问题：

1. 这次成功是真实执行还是 fallback？
2. 使用了哪个 kernel、哪个 LLM、哪个 capability、哪个 profile？
3. 如果失败，失败码、失败阶段、失败证据是什么？
4. 如果要上线，有没有自动化证据证明这条路径可在生产环境复现？

当这四个问题都能被机器稳定回答时，`hi-agent` 才真正从“架构完整”进入“工程可信”。
