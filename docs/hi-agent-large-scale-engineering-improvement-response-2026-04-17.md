> **⚠️ DEPRECATED 2026-04-17** — 本文档已被专家评审打回 8 处修订。**请勿作为执行依据**。
>
> **新授权文档**：
> - `docs/hi-agent-implementation-plan-2026-04-17.md`（主实施计划，团队执行依据）
> - `docs/hi-agent-implementation-plan-w2-w5-2026-04-17.md`
> - `docs/hi-agent-implementation-plan-w6-w12-2026-04-17.md`
> - `docs/hi-agent-engineering-execution-playbook-2026-04-17.md`（合同锁定版，自用 playbook）
>
> **评审文档**：`docs/hi-agent-large-scale-engineering-improvement-response-review-2026-04-17.md`
>
> 本文档仅保留作历史，记录最初的响应判断及其被纠正的 3 类乐观偏差（MCP LOC 低估 / provenance 单字符串 MVP / RBAC 套到 /runs）。

---

# hi-agent 大规模工程落地 — 执行承诺与响应（已作废）

**日期**：2026-04-17
**响应对象**：`docs/hi-agent-large-scale-engineering-improvement-plan-2026-04-17.md`
**作者**：hi-agent 平台团队
**状态**：**DEPRECATED** — 被专家评审修订，新版本参见顶部 banner

---

## 0. 摘要

我们整体**接纳**专家提出的 12 周 5 阶段路线与 "先打穿一条 production-grade golden path" 的核心判断。

在接纳之前，我们先对 314 个 Python 源文件做了 7 路并行代码级审计，交叉核对了专家的每条关键 claim。审计结果保存在：

- `docs/hi-agent-usability-audit-2026-04-17.md`（全量证据、file:line 引用、子系统记分卡）

本响应文档在专家路线上做了 4 处基于代码证据的**修订**，并把每个 P0/P1/P2 工单拆成**可评审的执行规格**（scope / files / tests / acceptance criteria / rollback）。

所有规格均遵守 `CLAUDE.md` 的六条 AI 工程规则：Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution / Pre-Commit Systematic Inspection / Three-Layer Testing。

---

## 1. 审计验证后的关键修订

基于代码证据，我们对专家判断有 4 处修订。这 4 处会直接改变执行的**节奏与范围**，请专家先行评审确认。

### 1.1 MCP 现状比 "infrastructure-only" 完整

**专家判断**：当前 MCP 是 infrastructure-only，缺 stdio/sse/http 真实 transport、auth、health、schema versioning、tool forwarding。

**代码证据**：
- `hi_agent/mcp/transport.py:65-286` — StdioMCPTransport 已实现 subprocess + initialize + tools/call + timeout + 退出检测（Unix select + Windows thread fallback）
- `hi_agent/mcp/binding.py:74-106` — MCPBinding 已做健康检查、条件注册、不可达自动剔除
- `hi_agent/server/app.py:1500-1560` — `/mcp/status` 已返回三态真实 truth table（`wired` / `registered_but_unreachable` / `not_wired`）
- `tests/test_mcp_integration.py:62-517` — 8 个端到端集成测试（MI-01~MI-08）用真实子进程驱动，非 mock

**修订**：MCP 真正的 P1 gap 只剩两项：
1. `tools/list` 从不被调用（工具必须在 `plugin.json` 预声明）
2. `stderr` 从不被读取（server crash 可能检测不到）

**影响执行计划**：专家原案中第 8-10 周的"MCP stdio 最小闭环"**压缩到约 50 LOC 的增量修复**，可以提前到 Week 4（与 Capability Plane 合并交付）。

### 1.2 Evolve 默认开启是未标注的生产风险

**专家建议**：evolve 不应默认影响生产路径，必须通过 experiment gate 或 profile policy 开启。

**代码证据**：
- `hi_agent/config/trace_config.py:80` — `evolve_enabled: bool = True`（**默认开启**）
- `hi_agent/config/trace_config.py:81` — `evolve_min_confidence = 0.6`
- `hi_agent/runner_lifecycle.py:326-387` — 每次 run 完成都调用 `evolve_engine.on_run_completed(postmortem)`
- `hi_agent/runner_lifecycle.py:355` — `route_engine.apply_evolve_changes()` 直接落盘
- `hi_agent/runner_lifecycle.py:365` — regression detection 仅 warning、不阻断

**修订**：这是**当前下游集成最直接的生产风险**。必须在 Week 1 P0 修复（1 行默认值 + 文档 + 迁移说明）。该风险在原专家计划里没有显式列为 P0，我们建议提级。

### 1.3 Runtime Provenance 的断链点就在 `_finalize_run`

**专家建议**：新增 `ExecutionProvenance` 数据结构，让 run/stage/action 都带来源信息。

**代码证据**：
- `hi_agent/capability/defaults.py:145` — 回退路径**已经写入** `_heuristic: True` 到 capability 输出
- `hi_agent/contracts/requests.py:110-162` — `RunResult.to_dict()` 没有任何 provenance 字段
- `hi_agent/server/app.py:415` — `/manifest` 硬编码 `"runtime_mode": "platform"`，忽略真实 `HI_AGENT_ENV`

**修订**：专家方案里的 provenance 设计是**完整新建**。实际工作只需要：
1. 给 `RunResult` 加一个 `execution_provenance` 字段
2. 在 `_finalize_run` 末尾扫描 `stage_summaries` 的 `_heuristic` 并聚合
3. `/manifest` 读取真实 `HI_AGENT_ENV`

**影响执行计划**：原专家第 2-3 周的"运行模式与 provenance"**压缩到 3 天**，Week 1 内即可交付。

### 1.4 RBAC/SOC guard 是接线缺失，不是缺失

**专家建议**：权限治理面补齐。

**代码证据**：
- `hi_agent/auth/rbac_enforcer.py` — 文件存在
- `hi_agent/auth/soc_guard.py` — 文件存在（`enforce_submitter_approver_separation` 等)
- 在 `hi_agent/server/app.py` 的 route 层 **grep 不到任何引用**

**修订**：治理代码完整，**仅差接线**。Week 1 内把它 wire 到 4 条敏感路由（`POST /skills/{id}/promote` / `POST /memory/consolidate` / `POST /skills/evolve` / `POST /runs` prod 模式），不需要重写。

---

## 2. 修订后的 12 周路线（对照专家原案）

| 周 | 专家原案 | 我们的承诺 | 差异说明 |
|---|---|---|---|
| 1 | Phase 0 基线冻结 | **Phase 0 基线冻结 + P0 四连击（治理底线）** | 把专家 Phase 1 的 provenance 压缩到 3 天塞进 Week 1，同时交付 evolve/RBAC/manifest 治理底线 |
| 2-3 | Phase 1 Runtime mode + provenance | **Phase 1 运维可用化（doctor + release-gate）+ 首拆 RunFinalizer + ReadinessProbe** | provenance 已在 Week 1 交付；这两周把运维层和最安全拆分点推进 |
| 4-5 | Phase 2 SystemBuilder 拆分 | **Capability Plane 最小治理 + MCP `tools/list` + SystemBuilder 低风险 4 拆分（Skill/Memory/Knowledge/Retrieval Builder）** | 把专家 Phase 4 中与 Capability 合并做；SystemBuilder 从低风险开始 |
| 6-7 | Phase 3 RunExecutor 拆分 | **SystemBuilder 高风险拆分（ServerBuilder / CapabilityPlaneBuilder）+ RunExecutor 提取 GateCoordinator** | 继续拆分，风险梯度递增 |
| 8-9 | 同上 | **RunExecutor 提取 ActionDispatcher + RecoveryCoordinator** | |
| 10 | Phase 4 Capability Plane + MCP | **RunExecutor 提取 StageOrchestrator + SystemBuilder 收尾（RuntimeBuilder / CognitionBuilder）** | 前面已做 Capability+MCP，这周收尾两个 god object |
| 11-12 | Phase 5 运营闭环 | **Profile/HI_AGENT_HOME 隔离 + Golden path 三层 + release gate 硬门控 + nightly prod E2E** | 产品化收尾 |

**每个里程碑 M1-M5 的交付物与成功标准**（沿用专家命名，内容更新见 §6）。

---

## 3. P0 工单执行规格（Week 1）

每个工单按统一模板交付，供专家评审：目标 / 文件 / 测试 / 验收 / 回滚。

### P0-1：关闭 Evolve 默认开启

**目标**：阻止低置信度 postmortem 在生产路径意外 mutate skill/policy。

**Scope**：
- 改 `TraceConfig.evolve_enabled` 默认值为 `False`
- 新增 `--enable-evolve` CLI flag 与 `HI_AGENT_ENABLE_EVOLVE` 环境变量等价物
- `readiness()` 增加 `evolve_enabled` 状态字段供下游观察
- 文档声明"evolve 默认关闭、需要显式开启"

**文件**：
- `hi_agent/config/trace_config.py:80`（1 行默认值）
- `hi_agent/cli.py`（新增 flag 解析）
- `hi_agent/config/builder.py`（readiness 输出增加 `evolve_enabled`）
- `README.md` / `ARCHITECTURE.md` / `CLAUDE.md`（声明行为变更）
- `docs/migration/evolve-default-off-2026-04-17.md`（迁移说明）

**测试**（Layer 1 + Layer 2）：
- `tests/unit/test_trace_config_defaults.py::test_evolve_disabled_by_default`
- `tests/integration/test_runner_evolve_gated.py::test_evolve_not_triggered_when_disabled`（完整 run 后 `skills/list` 不变）
- `tests/integration/test_runner_evolve_gated.py::test_evolve_triggered_when_enabled_flag`

**验收**：
- Default factory run → `skills_version_manager` 未收到任何 `create_version` 调用
- `HI_AGENT_ENABLE_EVOLVE=1` 或 `--enable-evolve` 时行为与当前一致
- `/readiness` 响应 `evolve_enabled=false` 除非显式开启

**回滚**：改回默认值；env var/flag 保留（加了不会破坏）。

**估算**：1 天（代码 + 测试 + 文档 + migration note）。

---

### P0-2：RunResult 传播 Execution Provenance

**目标**：下游集成方可**机器区分** dev-smoke vs prod-real success。

**Scope**：
- `RunResult` 新增可选字段 `execution_provenance: str | None`
  - 取值：`heuristic_fallback` / `llm_real` / `kernel_http` / `kernel_local` / `None`
- `RunExecutor._finalize_run` 末尾扫描 `stage_summaries` 的 `_heuristic` 标记并聚合
- `RunResult.to_dict()` 在 serialize 时输出该字段
- 更新 `tests/integration/test_prod_e2e.py`：断言 `execution_provenance != "heuristic_fallback"`，取代原来的 `_heuristic` 字符串扫描

**文件**：
- `hi_agent/contracts/requests.py:110-162`（+1 字段、+1 序列化行）
- `hi_agent/runner.py:1845-2070` _finalize_run 末尾新增聚合逻辑（~15 LOC）
- `tests/integration/test_prod_e2e.py:90-106`（断言升级）
- 新增 `tests/unit/test_run_result_provenance.py`

**测试**（Layer 1 + Layer 2 + Layer 3）：
- Layer 1：`RunResult(execution_provenance="...")` 序列化正确
- Layer 2：dev 模式 default run → `execution_provenance="heuristic_fallback"`；prod 模式 fake LLM HTTP → `"llm_real"`
- Layer 3：`POST /runs` 响应 JSON 包含该字段

**验收**：
- 专家"四问" Q1（"这次成功是真实执行还是 fallback？"）可以被机器稳定回答
- 现有所有测试不 break（新字段是 additive、可选）
- `_heuristic` 与 `execution_provenance` 语义不冲突：保留 `_heuristic` 作为内部实现细节，`execution_provenance` 作为对外合同

**回滚**：删字段或设为 None。

**估算**：1 天。

---

### P0-3：`/manifest` 读取真实 `HI_AGENT_ENV`

**目标**：`/manifest` 不能撒谎。

**Scope**：
- `/manifest` 响应中 `runtime_mode` 字段改为读取真实 `HI_AGENT_ENV`（`dev` / `prod`）
- 同时加 `execution_mode`（`local` / `http`），与 `/ready` 的 vocabulary 对齐
- 增加 `provenance_contract_version` 标识这一轮修订

**文件**：
- `hi_agent/server/app.py:415`（3-5 LOC 替换硬编码）
- `tests/integration/test_manifest_truthfulness.py`（新增断言）

**测试**（Layer 2 + Layer 3）：
- `HI_AGENT_ENV=dev` 启动 server → `/manifest.runtime_mode=="dev"`
- `HI_AGENT_ENV=prod` 启动 server → `/manifest.runtime_mode=="prod"`
- Manifest vocabulary 与 `/ready` 返回的同名字段取值一致

**验收**：
- 专家"四问" Q2（"使用了哪个 kernel、LLM、capability、profile？"）通过 manifest + ready 组合可回答
- Manifest contract 加入 snapshot/golden 测试（应专家 §9.2 风险缓解要求）

**回滚**：改回硬编码。

**估算**：半天。

---

### P0-4：RBAC + SOC Guard 接线到敏感路由

**目标**：让现有治理代码不再是死代码。

**Scope**：识别 4 条高风险路由，接入 `RBACEnforcer` 和 `SOCGuard`：
1. `POST /skills/{skill_id}/promote`（champion 切换）
2. `POST /memory/consolidate`（中期记忆推进）
3. `POST /skills/evolve`（手动 evolve 触发）
4. `POST /runs`（仅 prod 模式要求 submitter ≠ approver，或保留 default=off）

**文件**：
- `hi_agent/server/app.py`（各 handler 上加 guard）
- `hi_agent/auth/rbac_enforcer.py`（可能补少量 role 矩阵配置）
- `hi_agent/auth/soc_guard.py`（复用）
- `tests/integration/test_auth_wiring.py`（新增）

**测试**（Layer 2）：
- 未带 token 调 `/skills/promote` → 401/403
- 以 `viewer` role 调 `/skills/evolve` → 403
- 以 `admin` role 调 → 200
- submitter 调 `/runs` 时 submitter 字段 == approver 字段 → 403（prod）/ 200（dev）

**验收**：
- `rbac_enforcer.py` 和 `soc_guard.py` 被至少 4 条路由引用（grep 可验证）
- 默认配置保持 backward compat（即无 token 时 dev 仍可用）
- 文档写明 prod 模式下的 guard 行为

**回滚**：route 上删 guard decorator；auth 模块保持不变。

**估算**：2 天。

---

## 4. P1 工单执行规格（Week 2-3）

### P1-1：`hi-agent doctor` CLI + `GET /doctor`

**目标**：让非核心开发者（ops/集成方/新同学）能自诊断。

**Scope**：一致的诊断模型，从同一个 `Diagnostics` 对象派生 CLI 输出和 HTTP 响应。

**诊断维度**（与 expert §5.7 对齐）：
- LLM credentials（`HI_AGENT_ENV=prod` 时硬检）
- Kernel 可达性（prod HTTP endpoint reachable）
- Capability registry 启动（至少有 fallback handler）
- MCP servers 健康（若配置）
- Skill loader 能读到 SKILL.md
- Memory / knowledge 可写目录
- Profile 解析正常

**文件**：
- `hi_agent/ops/diagnostics.py`（新）— 纯函数，返回 `DoctorReport` dataclass
- `hi_agent/cli/doctor.py`（新）— 格式化 CLI 输出
- `hi_agent/server/ops_routes.py`（新）— `/doctor` handler
- `hi_agent/cli.py`（注册 subcommand）
- `hi_agent/server/app.py`（注册 route）

**输出 shape**：
```json
{
  "status": "ready" | "degraded" | "error",
  "blocking": [
    {"subsystem": "llm", "code": "missing_credentials", "message": "...", "fix": "...", "verify": "..."}
  ],
  "warnings": [...],
  "next_steps": [...]
}
```

**测试**（Layer 1 + Layer 2 + Layer 3）：
- Layer 1：Diagnostics 在各种 mock state 下返回正确 code
- Layer 2：真实 builder.readiness() 快照 → doctor 输出正确
- Layer 3：CLI `hi-agent doctor` exit code 0/1 正确；`curl /doctor` 返回结构化 JSON

**验收**：
- 缺 LLM key 的 prod 启动：doctor 给出明确 "set ANTHROPIC_API_KEY or OPENAI_API_KEY" + verify 命令
- 缺 kernel URL 的 prod 启动：doctor 给出"set HI_AGENT_KERNEL_URL"
- MCP server 配错：doctor 给出 server_id + stderr 摘要
- `--json` 和 HTTP JSON 格式一致

**估算**：3 天。

---

### P1-2：`GET /ops/release-gate`

**目标**：CD/CD 有单一端点判断是否可部署。

**Scope**：聚合 4 个已有信号 + 1 个新信号：
- `readiness.status` 不是 `error`
- `doctor.blocking` 为空
- 最近一次 `prod-real` golden path 通过（Week 11-12 交付后才有）
- SLO monitor 未触发
- Config validation 通过

**文件**：
- `hi_agent/ops/release_gate.py`（新）
- `hi_agent/server/ops_routes.py`（挂 route）

**输出 shape**：
```json
{
  "pass": true | false,
  "gates": [
    {"name": "readiness", "status": "pass", "evidence": "ready"},
    {"name": "doctor", "status": "pass", "evidence": "no blocking issues"},
    {"name": "prod_e2e_recent", "status": "skipped", "evidence": "no recent run"}
  ],
  "last_checked_at": "..."
}
```

**测试**（Layer 2 + Layer 3）：
- 全绿时 pass=true
- 任一 gate fail 时 pass=false + 原因
- HTTP 响应结构稳定

**验收**：CI/CD 可 `curl /ops/release-gate | jq .pass` 做简单 gating。

**估算**：2 天。

---

### P1-3：抽取 `RunFinalizer`

**目标**：`RunExecutor` god-object 缓解的第一步。选最安全的拆分点（纯只读、无回写）。

**Scope**：
- 新建 `hi_agent/execution/run_finalizer.py`
- 从 `hi_agent/runner.py:1845-2070` 移动 `_finalize_run` + `_cancel_pending_subruns` + `_build_postmortem`
- 建立 `RunFinalizerContext` dataclass 打包所有只读引用（`raw_memory` / `mid_term_store` / `long_term_consolidator` / `feedback_store` / `failure_collector` / `lifecycle` / `metrics_collector` / `session` / `contract` / `dag` / `action_seq` / `policy_versions` / `_pending_subrun_futures` / `_completed_subrun_results`）
- `RunExecutor._finalize_run` 变成一行 `return RunFinalizer(ctx).finalize(outcome)` 的 facade

**文件**：
- `hi_agent/execution/__init__.py`（新）
- `hi_agent/execution/run_finalizer.py`（新，~600 LOC 移动）
- `hi_agent/runner.py:1845-2070`（换成 facade）
- `tests/unit/test_run_finalizer.py`（新）
- 现有 5-8 个 runner 测试可能需要更新

**测试策略**：
- 先写 characterization test 固定当前 `_finalize_run` 在 3 种 outcome（completed/failed/cancelled）下的输出形态（P3 production integrity：用真实 stores，不 mock）
- 再做移动
- 最后加 unit test 覆盖 RunFinalizer 自身的逻辑分支

**验收**：
- graph execution / gate resume / forced failure / failure attribution / L0→L2→L3 chain 全部测试仍通过
- `runner.py` LOC 下降 ~600
- `RunFinalizer` 有独立测试

**回滚**：保留 facade 允许内联回 runner.py。

**估算**：4 天。

---

### P1-4：抽取 `ReadinessProbe`

**目标**：SystemBuilder god-object 缓解的第一步。选最安全的拆分点（纯观察器、零 mutation）。

**Scope**：
- 新建 `hi_agent/config/readiness.py`
- 从 `hi_agent/config/builder.py:1837-2045` 移动 `readiness()` + 相关私有辅助
- `SystemBuilder.readiness()` 变成 `return ReadinessProbe(self).snapshot()` 的 facade
- 保留 `SystemBuilder` 公开 API 不变

**文件**：
- `hi_agent/config/readiness.py`（新，~300 LOC 移动）
- `hi_agent/config/builder.py:1837-2045`（facade）
- `tests/unit/test_readiness_probe.py`（新）

**验收**：
- `/ready` 端到端测试输出 byte-identical（加入 golden snapshot 测试防漂移）
- ReadinessProbe 可单独构造并测试

**回滚**：facade 内联回原位置。

**估算**：2 天。

---

### P1-5：Capability Plane 最小治理

**目标**：让 Capability 从"内部 registry"升级为"可治理的工具生态"的最小版本。

**Scope**：
- `CapabilityDescriptor` 扩 3 字段：`toolset_id: str`、`required_env: dict[str, str]`、`output_budget_tokens: int`
- `CapabilityRegistry.probe_availability(name) -> (bool, reason)`：检查 `required_env` 在 `os.environ` 是否齐全
- `/manifest.capabilities` 从 `list[str]` 升级为 `list[CapabilityView]`，包含 name / status / effect_class / toolset / required_env / availability 原因
- `RouteEngine.propose()` 后加 filter：剔除 `probe_availability == False` 的 proposal
- `CapabilityInvoker.invoke()` 前置 availability 检查

**文件**：
- `hi_agent/capability/adapters/descriptor_factory.py:10-30`（+3 字段）
- `hi_agent/capability/registry.py`（+probe_availability）
- `hi_agent/capability/invoker.py:95-108`（+前置检查）
- `hi_agent/route_engine/base.py` 或各 engine（+filter）
- `hi_agent/server/app.py:366-376`（manifest 结构化）
- `tests/unit/test_capability_probe_availability.py`（新）
- `tests/integration/test_route_engine_filters_unavailable.py`（新）
- `tests/integration/test_manifest_capability_shape.py`（新）

**测试**：
- Layer 1：Descriptor 序列化、probe 在各种 env 组合下行为
- Layer 2：RouteEngine 真实 propose 后看不到 unavailable
- Layer 3：manifest 响应 shape 稳定

**验收**：
- 所有 capability 都有 descriptor（即使是 legacy ones 用 factory 推断）
- 一个 required_env 未 set 的 capability 在 disabled-env 下：
  - `/manifest` 显示 `status="unavailable"` + reason
  - `RouteEngine` 不 propose
  - 直接 invoke 抛 typed error
- ~115 LOC，无 breaking change

**估算**：5 天。

---

## 5. P2 阶段执行规格（Week 4-12）

### P2-1：SystemBuilder 分阶段 facade 拆分（Week 4-10）

**拆分顺序**（按风险从低到高，与专家 §5.2 对齐）：

| 步骤 | 新 builder | 职责 | 移动 LOC | 目标周 |
|---|---|---|---|---|
| 1 | `ReadinessProbe` | readiness() 快照 | 300 | P1-4（Week 2-3）已做 |
| 2 | `SkillBuilder` | skill_registry / loader / observer / version_manager / evolver | 200 | Week 4 |
| 3 | `MemoryBuilder` | short_term / mid_term / long_term stores | 150 | Week 4 |
| 4 | `KnowledgeBuilder` | wiki / manager / retrieval engine | 250 | Week 5 |
| 5 | `RetrievalBuilder` | 消除 `engine._embedding_fn = ...` 后构造 mutation | 100 | Week 5 |
| 6 | `ServerBuilder` | AgentServer + 7 处 assignment（消除 post-construction mutation） | 200 | Week 6 |
| 7 | `CapabilityPlaneBuilder` | capability / invoker / artifact / harness（打破 LLM-capability 循环依赖） | 400 | Week 6-7 |
| 8 | `RuntimeBuilder` | executor + 3 处私有属性注入（最危险） | 600 | Week 8-9 |
| 9 | `CognitionBuilder` | kernel / LLM / middleware orchestrator | 300 | Week 10 |

**每步执行模板**：
1. 先加 characterization test 固定当前 `SystemBuilder.build_*()` 外部行为
2. 新建 builder 文件（在 `hi_agent/config/` 下）
3. `SystemBuilder` 对应方法变 facade（内部委托）
4. 跑 28 个依赖 SystemBuilder 的测试，确保全部通过
5. 对新 builder 加独立单测
6. 如遇 post-construction mutation，**一律改为 constructor 注入**（这是专家的核心关切）
7. 每步独立 PR、独立 review、独立 merge

**不做的事**：
- 不重写 `SystemBuilder` 公开 API
- 不改变 profile 派生语义（但要用 characterization test 固定并标注目前的共享缓存问题，留作 Week 11-12 修复）

**回滚单位**：每步一个 PR，可独立回滚。

---

### P2-2：RunExecutor 分阶段 coordinator 拆分（Week 2-10）

**拆分顺序**：

| 步骤 | 新 coordinator | 职责 | 移动 LOC | 目标周 |
|---|---|---|---|---|
| 1 | `RunFinalizer` | _finalize_run 只读链 | 600 | P1-3（Week 2-3）已做 |
| 2 | `GateCoordinator` | register_gate / resume / gate_pending / continue_from_gate | 360 | Week 7 |
| 3 | `ActionDispatcher` | route proposal → harness/capability invocation | 280 | Week 8 |
| 4 | `RecoveryCoordinator` | stage_failure / restart_policy / escalation | 420 | Week 8-9 |
| 5 | `StageOrchestrator` | execute / execute_graph / _execute_remaining 三入口统一 | 430 | Week 10 |
| 6 | `SubRunManager` | dispatch_subrun / await_subrun（可选，延后） | 370 | Deferred |

**每步执行模板**：同 P2-1。

**关键收敛**：execute / execute_graph / continue_from_gate_graph 三处 ~60 LOC 启动/异常/收尾逻辑抽成 `_execute_all_stages(traversal_fn)`（在 StageOrchestrator 阶段完成）。

---

### P2-3：MCP `tools/list` 动态发现 + stderr 消费（Week 4）

**Scope**：
- `StdioMCPTransport.list_tools(server_id, timeout) -> list[dict]`
- `MCPBinding.bind_all()` 健康检查后调用 `list_tools`，merge 预声明和发现结果
- subprocess stderr 定期 tail 进入 `MCPHealth` 报告
- 失败时标记 server unavailable，不注册 broken stub

**文件**：
- `hi_agent/mcp/transport.py`（+1 方法 + stderr reader）
- `hi_agent/mcp/binding.py:96-106`（+list_tools 调用）
- `hi_agent/mcp/health.py`（+stderr tail）
- `tests/test_mcp_integration.py`（新增 MI-09：tools/list 动态发现）
- fake MCP server 脚本更新（支持返回 tools/list）

**估算**：3 天。~50 LOC 主代码 + 测试。

---

### P2-4：Profile / HI_AGENT_HOME 隔离（Week 11）

**Scope**：
- `HI_AGENT_HOME` 环境变量（默认 `~/.hi_agent`）
- `~/.hi_agent/profiles/{profile_id}/` 目录结构
- 每个 profile 独立 config / skills / memory / checkpoints
- CLI `--profile=<id>` 切换
- 消除 Week 4-10 标注的 SystemBuilder 派生时共享可变缓存问题（此时已经有清晰的 builder 边界）

**文件**：
- `hi_agent/profile/manager.py`（新）
- `hi_agent/config/stack.py`（扩 profile-aware loading）
- `hi_agent/cli.py`（--profile flag pre-parse）

**测试**：
- Layer 2：两个 profile 并行运行互不污染（不同 skills、不同 memory）

**估算**：5 天。

---

### P2-5：Golden Path 三层 + release gate 硬门控（Week 11-12）

**三层 golden path**：

| 层 | 外部依赖 | 默认运行 | 目的 |
|---|---|---|---|
| dev-smoke | 无 | CI 必跑 | 平台基础可用 |
| local-real | fake LLM/kernel/MCP server（subprocess） | CI 必跑 | 真实网络、序列化、重试边界 |
| prod-real | 真实 LLM + 真实 kernel endpoint | nightly | 生产可复现证据 |

**新建 fake server fixtures**：
- `tests/fixtures/fake_llm_http_server.py`（已有 ground truth from anthropic_gateway tests，参考它扩）
- `tests/fixtures/fake_kernel_http_server.py`
- `tests/fixtures/fake_mcp_stdio_server.py`（已有 `test_mcp_integration.py:62-142`，复用）

**release gate 硬门控**：`/ops/release-gate` 增加一个 gate：最近一次 prod-real 必须在 72 小时内通过，否则 pass=false。

**估算**：8 天。

---

## 6. 里程碑修订（M1-M5）

| 里程碑 | 专家目标周 | 我们承诺目标周 | 交付物 | 成功标准 |
|---|---|---|---|---|
| **M1 Runtime Truth** | W3 末 | **W1 末** | provenance 传播 + manifest 诚实 + evolve/RBAC 治理底线 | 专家"四问"Q1/Q2 机器可回答 |
| **M2 Composable Runtime** | W5 末 | **W6 末** | ReadinessProbe / SkillBuilder / MemoryBuilder / KnowledgeBuilder / RetrievalBuilder / ServerBuilder 独立 | SystemBuilder LOC 下降 ≥40%，每个 builder 有独立 unit test |
| **M3 Composable Execution** | W7 末 | **W10 末** | RunFinalizer + GateCoordinator + ActionDispatcher + RecoveryCoordinator + StageOrchestrator | runner.py LOC 下降 ≥60%，3 个 execute 入口共用内循环 |
| **M4 Real Tool Plane** | W10 末 | **W5 末** | Capability Plane 治理 + MCP tools/list | 至少一个外部 MCP tool 真实可调用、manifest 结构化、RouteEngine 过滤 unavailable |
| **M5 Operable Platform** | W12 末 | **W12 末** | doctor / release-gate / profile 隔离 / golden path 三层 | 专家"四问"Q3/Q4 机器可回答，release-gate 可以阻断部署 |

**显著变化**：M1 提前到 W1 末，M4 提前到 W5 末；M2/M3 略晚但分批交付。整体 12 周边界不变。

---

## 7. 测试策略执行承诺

遵守 `CLAUDE.md` Rule 6 三层测试：

### 7.1 覆盖率目标

| 阶段 | 全局 coverage | 核心包 | 新增代码 |
|---|---|---|---|
| 当前 | 65 | - | - |
| W4 末 | **70** | execution 80 / config 80 / capability_plane 80 / server 80 | 85 |
| W8 末 | **75** | 同上保持 | 85 |
| W12 末 | **80** | 同上保持 | 90 |

在 `pyproject.toml` 的 `[tool.coverage]` 增加 per-package `fail_under` 设置（需要 `pytest-cov` 支持）。

### 7.2 关键回归场景（固化为长期测试）

按专家 §7.3 清单全部加为"不可绕过"的 regression suite：

1. ✅ dev fallback completed 且 provenance 标记（P0-2 交付后立即加）
2. ✅ prod missing LLM 不允许 heuristic success（P0-2 + P0-3 交付后加）
3. prod missing kernel 不允许 LocalFSM fallback（已有 `test_prod_e2e.py` 骨架，W2 强化）
4. MCP configured but unreachable 不注册 callable tool（已有 MI-06）
5. RouteEngine 不选择 unavailable capability（P1-5 交付后加）
6. failed run 必有 failure_code 和 failed_stage_id（已有）
7. run.state 与 result.status 不矛盾（已有，加入 manifest snapshot）
8. gate pending 可 resume（已有）
9. config reload 不影响 in-flight run（W11 Profile 隔离时加）
10. output 超预算被裁剪且标记（P1-5 交付后加）

### 7.3 Layer 1/2/3 强制

- **禁止 mock 任何 hi-agent 内部子系统**（P3 Production Integrity 规则）
- fake external server 允许且鼓励（fake_llm_http_server, fake_kernel_http_server, fake_mcp_stdio_server）
- 每个 P0/P1/P2 工单必须附带至少 Layer 2 集成测试

---

## 8. 待专家决策的开放问题

请专家在评审时明确以下 6 个决策点：

### Q1：Evolve 默认行为

我们建议改默认值为 `False`（P0-1）。这是 breaking behavior change（即使 config API 不变）。

**选项**：
- A. 直接默认 False（我们建议，最诚实）
- B. 新增 `evolve_enabled` 三态（`"auto"` / `"on"` / `"off"`），prod 下 `auto == off`，dev 下 `auto == on`
- C. 保留默认 True，但 prod 模式下硬关闭

**倾向**：A（最小且明确）。

### Q2：`execution_provenance` 字段的 enum 固定

**选项**：
- A. 固定 4 值：`heuristic_fallback` / `llm_real` / `kernel_http` / `kernel_local`
- B. 改为结构化 dict（如 `{"llm": "real", "kernel": "http", "capability": "mcp"}`）—— 更贴合专家 §5.1 设计

**倾向**：**B**（与专家原案一致），但 Week 1 先交付 A 作为 MVP，Week 2 扩展为 B。

### Q3：`/ops/release-gate` 中 prod-real 的门控时长

**选项**：
- A. 72 小时内有通过
- B. 24 小时内
- C. "最近 master/main 提交后一定有过一次"（更严格）

**倾向**：A（周末间隔容忍）。

### Q4：RBAC 默认 role 矩阵

P0-4 里我们准备了 3 个 role：`viewer` / `operator` / `admin`。

**选项**：
- A. 这三者就够（我们建议）
- B. 扩展为 `submitter` / `approver` / `auditor` / `admin` 贴合专家的 SOC 分离原则

**倾向**：A + `approver` 从 `admin` 派生。需要专家确认是否接受。

### Q5：SystemBuilder 拆分是否允许阶段性共存

W4-W10 期间 SystemBuilder 同时持有旧代码和新 facade。

**选项**：
- A. 允许共存，facade 内部委托到新 builder（我们建议）
- B. 每拆一步立即删除旧代码（激进）

**倾向**：A（对齐专家 §8.3 回滚策略）。

### Q6：Coverage 门槛提升节奏

**选项**：
- A. W4/W8/W12 分别 70/75/80（我们建议）
- B. 每拆一个 god-object 就提升 5 个点（更直接绑定到架构进步）

**倾向**：A（更稳定可预测）。

---

## 9. 风险与缓解承诺

对照专家 §9 风险清单，逐项承诺：

| 专家风险 | 我们的缓解承诺 |
|---|---|
| 重构范围过大 | facade 优先、每次一个 PR、每次 characterization test 先行、每 PR 独立 review & rollback |
| 文档与实现再次漂移 | manifest 响应加 golden snapshot 测试；platform contract 每次变更必须同步测试；每周一次 "runtime truth review"（见 §10） |
| Fallback 语义继续污染生产判断 | P0-2 交付后，prod 模式下 `execution_provenance="heuristic_fallback"` 必定触发 release-gate fail；`HI_AGENT_ALLOW_HEURISTIC_FALLBACK` 在 prod 下不生效 |
| MCP transport 引入进程管理复杂度 | 所有 transport 调用必 timeout；subprocess 必有 lifecycle owner；stderr tail 进 health（P2-3 承诺）；crash 自动标记 unavailable（已有） |
| 过度产品化影响研究速度 | dev-smoke 保留作为默认 CI 路径；研究路径继续 fallback；prod 准入严格但不阻塞研究 |

**自加的风险**：

| 新增风险 | 缓解 |
|---|---|
| P0-1 默认改 False 可能影响已经依赖 evolve 的内部流水线 | 检查 `hi_agent` 仓内全部 CI 配置和下游集成方测试，提前 1 周通知，提供 `--enable-evolve` 迁移脚本 |
| P0-4 RBAC 接线可能 break 没有带 token 的集成测试 | 默认 dev 模式下 guard bypass；prod 模式下才 enforce；现有集成测试多是 dev 模式，影响面小 |
| Coverage 提升到 80 对核心包可能需要补大量测试 | W4-W12 每周检查 coverage trend，不达标的包单独建 ticket 而不是阻塞主线 |

---

## 10. 运营机制承诺

### 10.1 每周 "Runtime Truth Review"（专家 §10.1）

每周五固定 1 小时对齐以下内容是否一致：
- `README.md` / `ARCHITECTURE.md`
- `/manifest` 响应 shape
- `/ready` 响应 shape
- 最近一次 golden path 测试结果
- 变更日志（`docs/` 下最新的 response / audit）

### 10.2 每个 P0/P1/P2 工单必须更新：
- 代码 + Layer 1/2/3 测试
- 相应 ARCHITECTURE.md 章节
- 若涉及下游合同：新版本 `docs/platform-contract.md` 条目
- 若修改 manifest/readiness shape：更新 golden snapshot

### 10.3 决策机制
以下变更经过架构评审（专家 §10.3）：
- `TaskContract` 字段语义变化
- `RunResult` shape 变化（**P0-2 即属此项，所以本响应文档就是这次评审**）
- runtime mode 行为变化（**P0-1 和 P0-3 属此项**）
- prod fallback 策略变化
- MCP schema/versioning 变化
- permission policy 默认行为变化（**P0-4 属此项**）

---

## 11. 反馈时间线与评审请求

### 请专家在 2026-04-18 18:00 前对以下 3 项给出反馈

1. **§8 的 6 个开放问题**（Q1-Q6）的选择
2. **§5 的 M1-M5 修订是否接受**（特别是 M1 提前到 W1 末、M4 提前到 W5 末）
3. **§1 的 4 处修订是否接受**（MCP、Evolve、Provenance、RBAC）

### 评审通过后，我们的 Week 1 工作计划

| 天 | 任务 | 产出 |
|---|---|---|
| Mon | P0-1 evolve 默认关闭 + migration doc | PR + tests |
| Tue | P0-2 RunResult provenance | PR + tests |
| Wed | P0-3 manifest 诚实 + golden snapshot | PR + tests |
| Thu | P0-4 RBAC/SOC 接线 | PR + tests |
| Fri | W1 集中 review + M1 达成声明 + 发下游集成方通告 | Runtime Truth Review |

### 每周交付节奏

- 每周一：发 weekly RFC（本周要推进的工单清单）
- 每周五：Runtime Truth Review + 下游合同变更公告

---

## 12. 附：下游合同变更预告

发给下游 Research Intelligence App 团队的合同变更预告（仅预告，不是正式通知）：

| 变更 | 影响 | 时间 |
|---|---|---|
| `RunResult.execution_provenance` 新增字段（optional） | additive，不 break | W1 末 |
| `/manifest.runtime_mode` 从 `"platform"` 改为真实 `dev`/`prod` | **可能 break** 硬编码依赖 | W1 末（请提前检查集成代码） |
| `/manifest.capabilities` 从 `list[str]` 改为 `list[CapabilityView]` dict | **break** | W4-5 |
| `evolve_enabled` 默认改为 False | **behavior change** | W1 Mon |
| 新增 `/doctor`、`/ops/release-gate` 端点 | additive | W2-3 |
| `/skills/{id}/promote` 等 4 条路由加 RBAC（prod 模式） | **prod 模式 break**，dev 不影响 | W1 末 |

---

**End of response document.**

本响应文档与 `docs/hi-agent-usability-audit-2026-04-17.md` 配套阅读，审计证据可回溯到 file:line。评审通过后，我们从 2026-04-18 进入 Week 1 执行。
