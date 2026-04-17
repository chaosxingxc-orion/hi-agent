# hi-agent 可用性审计报告（Usability Audit）

**日期**：2026-04-17
**范围**：hi-agent 工程实现 × 专家改进计划交叉验证
**输入**：
- `docs/hi-agent-large-scale-engineering-improvement-plan-2026-04-17.md`（专家12周路线图）
- `D:\chao_workspace\hermes-agent`（产品闭环参考）
- hi-agent 全量代码（314 Python源文件）

**审计方法**：7路并行代码级调查，每个claim均附file:line证据
**核心原则**："使用视角可用" — 架构声明的每个功能，能否被真实使用者（CLI/HTTP/集成方）驱动并观察到真实效果

---

## 0. 执行摘要

### 0.1 与专家判断的差异

专家文档方向**基本正确**但部分判断**已经过时或过重**。经过代码级审计：

| 专家主要判断 | 审计结论 | 修正点 |
|---|---|---|
| MCP 是 "infrastructure-only" | **部分过时** | stdio transport / subprocess / initialize / tools/call **全部已实现并有8个真实E2E集成测试**；仅缺`tools/list`动态发现和stderr消费（~50 LOC即可闭合） |
| `/health`、`/ready`、`/manifest` 要"补齐操作员体验" | **基础已很强** | `/ready`返回per-subsystem真实状态(kernel/LLM/capability/MCP/plugins/profiles)，非浅层200；但`/doctor`、`/ops/*` 6个专家期望端点**全部不存在** |
| Cognitive子系统(memory/knowledge/skill/evolve)需要"更严格的实验门控" | **Evolve风险比专家说的更大** | 4个子系统**都可从HTTP驱动并观察效果**，但`TraceConfig.evolve_enabled=True`**默认在prod开启**、无experiment gate，每次confidence≥0.6即mutate生产skill |
| SystemBuilder 是 "装配黑洞" | **确认且更严重** | 2,045 LOC / 34子系统 / 35个build_*方法 / **3处致命post-construction mutation** (builder.py:1621, 1644, 1663) / **专家提出的5个builder全部不存在** |
| RunExecutor 是 God Object | **确认且更严重** | 3,443 LOC / 64方法 / 10职责簇 / `__init__`本身326 LOC、40+参数 / `_finalize_run`227 LOC触达12子系统 |
| Runtime Provenance 机器不可辨 | **完全确认** | `_heuristic`标记在capability层**已写入** (defaults.py:145)，但**未传播到RunResult**；`/manifest`硬编码`"runtime_mode": "platform"`忽略真实模式 |
| Capability Plane 缺工具生态治理 | **确认** | 870 LOC已有Descriptor/RBAC/CircuitBreaker基座，但缺toolset grouping / pre-flight availability / required_env / output_budget / schema version / 结构化audit / sandbox enforcement；**RouteEngine不过滤unavailable能力** |

### 0.2 真实优先级排序（按"使用视角阻断度"）

与专家12周五阶段相比，我建议的**真实阻断级**排序：

| 等级 | 问题 | 阻断什么 | 修复规模 |
|---|---|---|---|
| **P0-可用性阻断** | Evolve默认开启无experiment gate | 产线运行会意外mutate skill，违反专家的"evolve不应默认影响生产路径" | 1行config默认值 + 文档 |
| **P0-信任阻断** | `_heuristic`不传播到RunResult，`/manifest`硬编码platform | 下游无法机器区分dev-smoke vs prod-real | 2文件、~20 LOC |
| **P0-治理阻断** | RBAC/SOC guard存在但**从未接线**到API/CLI | `auth/rbac_enforcer.py`和`auth/soc_guard.py`是死代码 | wire到route层 |
| **P1-运维阻断** | `/doctor`、`hi-agent doctor` CLI缺失 | ops无法自诊断，只能读日志/源码 | 复用`builder.readiness()`、~150 LOC |
| **P1-扩展阻断** | SystemBuilder god object、RunExecutor god object | 任何新能力都只能往god object塞分支，回归风险高 | 分阶段facade拆分，从ReadinessProbe + RunFinalizer起手 |
| **P1-生态阻断** | Capability Plane无toolset/availability/required_env | RouteEngine可能propose失效能力、manifest只输出字符串 | ~115 LOC |
| **P2-完整性** | MCP `tools/list`动态发现 + stderr消费 | MCP server如果没在plugin.json预声明tools就没法被发现 | ~50 LOC |
| **P2-产品化** | Profile / HI_AGENT_HOME隔离、session DB、release-gate | 多环境、多profile、CI/CD准入 | 各3-5天 |

### 0.3 核心判断

专家的 **"不要继续扩张认知子系统，先打穿一条production-grade golden path"** 方向正确。但**当前最紧迫的不是12周重构，而是"3行默认值 + 20 LOC provenance传播"**：

1. `TraceConfig.evolve_enabled = False`（默认关闭）
2. `RunResult.execution_provenance` 字段 + runner聚合`_heuristic`
3. `/manifest` 读取 `HI_AGENT_ENV` 真实值

这三项是**当前下游集成最可能踩到的真实风险**，总计不到100 LOC。完成后再启动专家的5阶段12周路线，投入产出比最高。

---

## 1. 子系统可用性记分卡

每个子系统按"使用者能否真实驱动并观察效果"打分（1-5）。

| 子系统 | 分数 | 可用性 | 端到端真实路径 | 关键gap | 证据 |
|---|---|---|---|---|---|
| **Memory (L0-L3)** | 5/5 | 完全可用 | 自动wire到每次run、`_finalize_run`触发L0→L2→L3链、`POST /memory/{dream,consolidate}`可手动触发、`GET /memory/status`观察 | 无关键gap；可选加`/memory/restore-from-archive` | `runner.py:2030-2041`, `app.py:1767-1769` |
| **Knowledge (wiki+graph+retrieval)** | 5/5 | 完全可用 | 自动ingest_from_session at run completion、6个HTTP端点完整 | 无CLI直接入口（仅HTTP） | `runner_lifecycle.py:437-449`, `app.py:1772-1781` |
| **Skill (loader/version/evolver)** | 4/5 | 基本可用 | Loader/observer wire在default path、7个HTTP端点完整 | Skill创建**依赖**postmortem confidence≥0.6，低质量run不会触发extraction | `builder.py:1577-1580`, `app.py:1784-1790` |
| **Evolve (postmortem/extract/regression/champion)** | 3/5 | 可用但风险 | `on_run_completed` 每run自动调用、可经`/skills/evolve`手触 | **默认开启、无experiment gate、无prod禁用flag**；confidence≥0.6即mutate；regression仅warning不阻断 | `trace_config.py:80`, `runner_lifecycle.py:326-387` |
| **RunExecutor (execute/graph/async)** | 4/5 | 可用但god object | `POST /runs` + CLI `run` + `resume`端到端 | 3,443 LOC / 64方法 / 10职责簇；execute/execute_graph/continue_from_gate重复逻辑~60 LOC | `hi_agent/runner.py` |
| **Route Engine** | 3/5 | 部分可用 | Rule/LLM/Hybrid/Skill-aware/Conditional 5种已实现 | **不过滤unavailable/disabled capability**，LLM可能propose失效工具 | `hi_agent/route_engine/` (未搜到filter逻辑) |
| **Capability Layer** | 3/5 | 基础可用 | Registry/Invoker/CircuitBreaker/Policy都wire | 无预检availability、无toolset、无required_env、无output_budget；`/manifest.capabilities`仅`list[str]` | `hi_agent/capability/`, `app.py:366-376` |
| **MCP Transport** | 4/5 | 基本可用 | stdio subprocess、initialize、tools/call、`/mcp/status` 3态truth table、8个E2E集成测试 | `tools/list`从未调用，工具必须plugin.json预声明；stderr从不读取 | `transport.py`, `binding.py`, `test_mcp_integration.py` MI-01~08 |
| **Harness (governance)** | 3/5 | 部分接线 | EffectClass + SideEffectClass存在 | 无dangerous approval UI、dangerous action检测未pattern化 | `hi_agent/harness/` |
| **Server / HTTP API** | 4/5 | 基础完整 | `/health` + `/ready` + `/manifest`真实返回per-subsystem状态；20+端点 | `/doctor`、`/ops/*` 全部不存在；`/manifest.runtime_mode`硬编码`"platform"` | `server/app.py:199-415, 1500-1800` |
| **Readiness Probe** | 4/5 | 真实 | 返回per-subsystem `runtime_mode / execution_mode / prerequisites`等 | prod模式下LLM缺失返回`not_configured`而非`error`，`/ready`仍200 (`builder.py:2013-2014`) | `builder.py:1837-2045` |
| **SystemBuilder** | 2/5 | 可用但高风险 | Default factory可构建完整系统 | god object;  3处致命post-construction mutation;  profile派生时共享私有缓存（hot reload风险） | `builder.py:1621,1644,1663,1727-1746` |
| **Auth (RBAC/SOC)** | 1/5 | 代码死 | `auth/rbac_enforcer.py`、`auth/soc_guard.py` 存在 | **从未接线**到API/CLI route层；是孤立模块 | grep: 无route引用 |
| **CLI Interface** | 3/5 | 基础可用 | serve/run/status/health/readiness/tools/resume 7个命令 | 无`doctor`、`setup`、`profile`、`config` 等ops命令 | `hi_agent/cli.py:477-659` |
| **Ops/Governance Layer** | 1/5 | 缺失 | 仅metrics | 无`/doctor`、`/ops/runbook`、`/ops/release-gate`、`/ops/config`、`/ops/dependencies` | `server/app.py` |

---

## 2. 专家Claim × 代码证据矩阵

| 专家claim | 代码证据 | Usable? | Gap |
|---|---|---|---|
| hi-agent有runtime_mode概念 | `config/builder.py:404,603` + `cli.py:89` HI_AGENT_ENV dev/prod | **Y** | 仅`/ready`暴露，`/manifest`硬编码 |
| Dev fallback silently成功 | `capability/defaults.py:28-33` `_allow_heuristic_fallback()`、`:137-146` fallback响应带`_heuristic:True` | **Y** | `_heuristic`到`RunResult`断链 |
| Fallback flag不传播 | `contracts/requests.py:110-162` RunResult无任何provenance字段 | **确认gap** | 加`execution_provenance`字段 |
| Prod fail-close完整 | `capability/defaults.py:127-135` + `test_prod_e2e.py:52-61` | **Partial** | LLM缺失时readiness返回`not_configured`非`error`，`/ready`仍200 |
| /manifest conflate execution | `server/app.py:415` 硬编码`"runtime_mode": "platform"` | **确认gap** | 读取实际HI_AGENT_ENV |
| SystemBuilder承担过多职责 | 2,045 LOC / 34子系统 / 35个build_*方法 / 28个测试耦合 | **严重god object** | 5个builder全部不存在 |
| 后构造注入变多 | `builder.py:1621,1644,1663` 3处executor私有属性赋值 | **确认** | 最紧急修复点 |
| Profile隔离不稳定 | `builder.py:1727-1746` 派生builder复制私有缓存 | **确认** | hot reload会跨profile共享mutable state |
| RunExecutor God Object | 3,443 LOC / 64方法 / 10职责簇 / `__init__`326 LOC 40+参 | **确认** | execute/execute_graph/continue_from_gate重复60 LOC |
| `_finalize_run`触达多子系统 | 227 LOC / 12子系统 (L0→L2→L3/lifecycle/feedback/failure/duration...) | **确认** | RunFinalizer是最安全首拆点 |
| 3个execute入口重复 | execute:2081-2166 / execute_graph:2178-2263 / continue_from_gate_graph:2972 | **确认** | 可抽`_execute_all_stages(traversal_fn)` |
| MCP仍infrastructure-only | `/mcp/status`返回`wired / registered_but_unreachable / not_wired`三态 + 8个E2E集成测试 | **过时** | 仅缺`tools/list`动态发现 |
| MCP无真实transport | `transport.py:150-184` subprocess.Popen + `:101-131` initialize + `:65-99` tools/call全部实现 | **过时** | Transport本身OK |
| MCP无错误处理 | `:195-239` 超时(select+thread Windows fallback) + `:206-209` 退出检测 | **Partial过时** | stderr从不读取是真gap |
| Capability 工具治理缺失 | 870 LOC有Descriptor(`descriptor_factory.py:10-30`)/RBAC(`policy.py`)/CircuitBreaker(`circuit_breaker.py`) | **Partial** | 10项governance中6项缺（toolset/availability/required_env/output_budget/schema version/sandbox enforcement） |
| RouteEngine不过滤unavailable | `route_engine/base.py:21-23` propose返回所有proposals，未查registry.probe | **确认** | P1核心缺口 |
| Evolve默认on且无实验门 | `trace_config.py:80` `evolve_enabled=True` | **比专家判断更严重** | P0：改默认False或加`--enable-evolve`flag |
| 缺`/doctor`等ops端点 | `server/app.py` 无route匹配 | **完全确认** | 6个ops端点全缺 |
| 缺doctor CLI | `cli.py` 7个subcommand中无doctor/setup | **完全确认** | 可复用readiness()快速实现 |
| Coverage 65偏低 | 待查pyproject/ruff/pytest config | 未查 | - |

---

## 3. Hermes 可借鉴模式优先级

| 模式 | 价值 | 工作量 | 理由 |
|---|---|---|---|
| Doctor + setup CLI | ★★★★★ | 4天 | 复用现成`builder.readiness()`，ops自诊断ROI最高 |
| `/ops/release-gate` 单端点 | ★★★★ | 3天 | 合并health+ready+last test run，CI/CD单一准入 |
| Profile / HI_AGENT_HOME隔离 | ★★★★ | 5天 | 扩`config/stack.py`，dev/staging/prod互不污染 |
| RBAC+SOC 接线到敏感路由 | ★★★★ | 2天 | 现有死代码复活，治理面马上到位 |
| DANGEROUS_PATTERNS风险分类 | ★★★ | 2天 | hermes `approval.py:68-100` — 扩capability effect_class新增"dangerous"枚举 |
| Session DB + FTS5搜索 | ★★★ | 5天 | 运营可见性强，但非golden path阻断 |
| Tool requirements gating | ★★★ | 3天 | 直接补齐Capability Plane gap |
| Process registry ops面 | ★★ | 3天 | 运营可见性 |
| ContextVar做session隔离 | ★★ | 1天 | 小量代码，但对future async扩展有价值 |
| Gateway multi-surface (Telegram/Discord/ACP) | ★ | 10+天 | 非golden path，**明确不建议** |
| Honcho memory provider | ✗ | - | hi-agent已有L0-L3成熟memory，无必要 |
| Cron后台任务 | ✗ | - | 当前HTTP polling够用 |

---

## 4. 修复路线图

### 4.1 P0 快速修复（<1周，<200 LOC）

这些是**可用性**和**治理**底线，不做不能上生产。

#### P0-1 关闭Evolve默认开启
```python
# hi_agent/config/trace_config.py:80
- evolve_enabled: bool = True
+ evolve_enabled: bool = False  # Must explicitly enable via config/--enable-evolve
```
**理由**：专家原文要求"evolve不应默认影响生产路径，必须通过experiment gate或profile policy开启"。当前confidence≥0.6即mutate skill/policy，违反生产默认安全原则。

#### P0-2 RunResult传播execution_provenance
```python
# hi_agent/contracts/requests.py RunResult 加字段
execution_provenance: str | None = None  # "heuristic_fallback" | "llm_real" | "kernel_http" | None

# hi_agent/runner.py _finalize_run 末尾扫描stage_summaries
fallback_used = any(s.get("_heuristic") for s in stage_summaries)
run_result.execution_provenance = "heuristic_fallback" if fallback_used else "llm_real"

# hi_agent/server/app.py:415 替换硬编码
- "runtime_mode": "platform",
+ "runtime_mode": os.environ.get("HI_AGENT_ENV", "dev"),
+ "execution_mode": readiness_snapshot.get("execution_mode", "local"),
```
**验收**：`tests/integration/test_prod_e2e.py` 断言升级为结构化字段而非`:heuristic:`字符串搜索。

#### P0-3 RBAC+SOC接线到敏感路由
`auth/rbac_enforcer.py`和`auth/soc_guard.py`是现成代码，需要wire到：
- `POST /skills/{id}/promote`
- `POST /memory/consolidate`
- `POST /skills/evolve`
- `POST /runs` (若prod且有admin_token要求)

实现：在`server/app.py`的route handler中加decorator检查。

### 4.2 P1 运维可用化（2-3周）

#### P1-1 hi-agent doctor CLI + /doctor HTTP
复用`builder.readiness()`快照，输出：
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
新文件：`hi_agent/cli/doctor.py` + `hi_agent/server/ops_endpoints.py`，各~150 LOC。

#### P1-2 /ops/release-gate
单端点合并：`readiness + manifest + recent run artifacts + config validation`。CI/CD可据此阻断部署。

#### P1-3 RunFinalizer 首拆
从`RunExecutor._finalize_run`（227 LOC）抽出只读操作到`hi_agent/execution/run_finalizer.py`。`RunFinalizerContext`打包只读引用。低风险（测试仅5-8个需更新）。

#### P1-4 ReadinessProbe 独立
从`builder.py:1837-2045`抽出到`hi_agent/config/readiness.py`。纯观察器，零mutation，可独立单测。

#### P1-5 Capability Plane 最小治理
- 扩`CapabilityDescriptor`加`toolset_id / required_env / output_budget_tokens`
- `CapabilityRegistry.probe_availability(name) -> (bool, reason)`
- `/manifest.capabilities` 改为结构化dict
- `RouteEngine` propose后filter `registry.probe_availability()`
- `CapabilityInvoker.invoke()` 前置availability检查

总计~115 LOC，零breaking change（新字段都默认empty）。

### 4.3 P2 架构健康（4-8周）

#### P2-1 SystemBuilder 分阶段facade拆分
按风险排序：ReadinessProbe（P1-4已做）→ SkillBuilder → MemoryBuilder → KnowledgeBuilder → RetrievalBuilder → ServerBuilder → CapabilityPlaneBuilder → RuntimeBuilder → CognitionBuilder。每步facade保留旧API。

#### P2-2 RunExecutor 分阶段coordinator拆分
RunFinalizer（P1-3已做）→ GateCoordinator → ActionDispatcher → RecoveryCoordinator → StageOrchestrator。每步RunExecutor保留compat facade。

#### P2-3 MCP `tools/list` 动态发现
`binding.py` 健康检查后调用`transport.invoke(server_id, "tools/list", {})`，用发现结果代替或merge plugin.json预声明。`transport.py`加`list_tools()`方法 + stderr tail消费。~50 LOC。

#### P2-4 Profile / HI_AGENT_HOME 隔离
扩`config/stack.py`，支持`~/.hi_agent/profiles/{profile_id}/`目录结构。checkpoint/config/skills/memory按profile分离。

#### P2-5 Golden path三层
- **dev-smoke**: 当前默认路径，保留
- **local-real**: 新增fake LLM HTTP server + fake kernel HTTP + fake MCP stdio (MI-01~08已是模板)
- **prod-real**: nightly run，真实外部依赖

---

## 5. 与专家12周路线对比

| 专家阶段 | 专家时长 | 我的修订 |
|---|---|---|
| Phase 0 基线冻结 | 第1周 | **保持** — 添加：记录`HI_AGENT_ENV`切换行为基线 |
| Phase 1 Runtime mode + provenance | 第2-3周 | **压缩到3天** — 只需P0-2的20 LOC，不需2周 |
| Phase 2 SystemBuilder拆分 | 第4-5周 | **保持** — 但从ReadinessProbe起手而非RuntimeBuilder |
| Phase 3 RunExecutor拆分 | 第6-7周 | **保持** — RunFinalizer首拆 |
| Phase 4 Capability Plane + MCP stdio | 第8-10周 | **压缩到1周** — Capability Plane 115 LOC，MCP 50 LOC（专家低估了已有实现） |
| Phase 5 运营闭环 | 第11-12周 | **提前到第2周** — 用`builder.readiness()`快速上doctor，不必等全部重构完 |

**我的修订路线**：
- **Week 1**: P0-1/P0-2/P0-3 (治理底线) + Phase 0 基线冻结
- **Week 2-3**: P1-1/P1-2 (doctor/release-gate)、P1-3 (RunFinalizer)、P1-4 (ReadinessProbe)、P1-5 (Capability Plane最小治理)
- **Week 4-6**: P2-1 SystemBuilder分阶段拆分
- **Week 7-9**: P2-2 RunExecutor分阶段拆分
- **Week 10**: P2-3 MCP `tools/list` + stderr消费、P2-4 Profile隔离
- **Week 11-12**: P2-5 Golden path三层 + release gate硬门控

**总工期保持12周，但前4周就能看到"每次成功能回答专家四问"**：
1. 真实执行 or fallback？ → 第1周（execution_provenance字段）
2. 使用了哪个kernel/LLM/capability/profile？ → 第1周（扩展provenance + manifest修复）
3. 失败码、失败阶段、证据？ → 已存在
4. 有无自动证据证明生产可复现？ → 第10周（golden path三层）

---

## 6. 最终判断

### 6.1 hi-agent当前真实成熟度

按"使用视角可用度"综合评分：

| 维度 | 分数 | 评价 |
|---|---|---|
| **认知能力（memory/knowledge/skill）** | 4.5/5 | 已接近生产级，Evolve需下调默认值 |
| **HTTP API基础面** | 4/5 | health/ready/manifest真实输出per-subsystem状态 |
| **CLI可用性** | 3/5 | 7个基础命令够用，缺ops命令 |
| **执行引擎** | 3.5/5 | 可用但god object |
| **装配层** | 2.5/5 | 可用但god object + post-construction mutation |
| **Runtime Provenance** | 2/5 | 有概念有标记，但不传播，`/manifest`还撒谎 |
| **Capability治理** | 2.5/5 | 基座在，治理缺 |
| **MCP集成** | 3.5/5 | 比专家说的完整 |
| **Ops/运营层** | 1/5 | 只有metrics，doctor/ops全缺 |
| **Auth治理** | 1/5 | 代码存在但未接线 |

**加权平均 ≈ 2.8/5**（可用但未产品化）

### 6.2 与专家"最终判断"对齐

专家原文的四问：

> 1. 这次成功是真实执行还是 fallback？
> 2. 使用了哪个 kernel、哪个 LLM、哪个 capability、哪个 profile？
> 3. 如果失败，失败码、失败阶段、失败证据是什么？
> 4. 如果要上线，有没有自动化证据证明这条路径可在生产环境复现？

**现状**：
- Q1：**No**（_heuristic存在但不在RunResult）
- Q2：**Partial**（`/ready`有，`/manifest`有profile和capability_count，但RunResult无kernel_mode/capability_used）
- Q3：**Yes**（failure_code、failed_stage_id、is_retryable都在RunResult；evidence在artifacts）
- Q4：**No**（prod E2E默认skip、无nightly、无release gate）

**完成P0-2 + P2-5后四问全部Yes**。

### 6.3 一句话结论

> **hi-agent不是"架构骨架完整但不能实施"** — 其14个子系统中10个已经端到端可用。**真正的gap是治理、诚实、和god-object风险**。不需要12周重写，需要的是：前2周修3个治理默认值（evolve/provenance/RBAC-wire），然后10周分阶段facade拆分god object并补全ops面。按"使用视角阻断度"而非"架构层级完整度"来规划工期。

---

## 附录A：引用代码定位（file:line）

所有本报告的claim均可回溯到：

**Runtime Provenance**：
- `config/builder.py:404,603,1837-2045,2027` HI_AGENT_ENV + readiness
- `capability/defaults.py:28-33,127-135,137-146` fallback handler + _heuristic flag
- `contracts/requests.py:110-162` RunResult（无provenance字段）
- `server/app.py:199-225,227-415` /ready, /manifest
- `tests/integration/test_prod_e2e.py:40-106` prod E2E prerequisites

**SystemBuilder god object**：
- `config/builder.py:1621` `executor._stage_executor._middleware_orchestrator = mw`
- `config/builder.py:1644-1645` `executor._lifecycle.skill_evolver` + `_skill_evolve_interval`
- `config/builder.py:1663` `executor._telemetry.tracer = Tracer(...)`
- `config/builder.py:1727-1746` 派生builder共享缓存
- `config/builder.py:1816-1831` server 7处post-construction assignment

**RunExecutor god object**：
- `hi_agent/runner.py:160-486` __init__ 326 LOC
- `hi_agent/runner.py:1845-2070` _finalize_run 227 LOC
- `hi_agent/runner.py:2072-2171` execute (99 LOC)
- `hi_agent/runner.py:2171-2267` execute_graph (96 LOC)
- `hi_agent/runner.py:2267-2592` _handle_stage_failure (325 LOC)

**Capability Plane**：
- `capability/registry.py:15-53` CapabilitySpec flat dict
- `capability/invoker.py:15-114` CapabilityInvoker (circuit breaker + timeout + retry, no availability probe)
- `capability/adapters/descriptor_factory.py:10-30` CapabilityDescriptor (缺6字段)
- `server/app.py:246,366-376` /manifest 返回flat `list[str]`
- `route_engine/base.py:21-23` propose 无availability filter

**MCP Transport**：
- `hi_agent/mcp/transport.py:65-99,101-131,150-184,195-239,241-286` stdio transport实现
- `hi_agent/mcp/binding.py:74-91,96-106` MCPBinding `_unavailable` tracking
- `tests/test_mcp_integration.py:62-142,186-517` 8个E2E集成测试 MI-01~08
- `server/app.py:287-311,1500-1560` /manifest + /mcp/status truth table

**Cognitive Reachability**：
- `server/app.py:1767-1790` memory/knowledge/skills 共16个端点
- `runner.py:2030-2041` `_finalize_run` L0→L2→L3链
- `runner_lifecycle.py:326-387,409-449` evolve + STM + knowledge auto-ingest
- `trace_config.py:80-81` `evolve_enabled=True` + `evolve_min_confidence=0.6`

**Ops + Hermes**：
- `hi_agent/cli.py:477-659` 7个subcommand（无doctor/setup）
- `hi_agent/server/app.py` 无/doctor, /ops/*
- `hermes-agent/hermes_cli/doctor.py` 44KB diagnostic
- `hermes-agent/hermes_cli/setup.py` 124KB wizard
- `hermes-agent/tools/approval.py:26-47,68-100` ContextVar + DANGEROUS_PATTERNS
- `hermes-agent/hermes_cli/main.py:83-158` profile isolation

---

## 附录B：首批建议工单（落地版）

| ID | 标题 | 类型 | 工作量 | Block什么 |
|---|---|---|---|---|
| P0-1 | `evolve_enabled`默认改为False | config | 1 LOC | 生产skill意外mutation |
| P0-2 | `RunResult.execution_provenance` + runner聚合 | feature | 20 LOC | 下游无法区分dev vs prod success |
| P0-3 | `/manifest` runtime_mode读取真实HI_AGENT_ENV | bugfix | 3 LOC | Manifest撒谎 |
| P0-4 | RBAC+SOC接线到4个敏感route | integration | 50 LOC | 治理代码死 |
| P1-1 | `hi-agent doctor` CLI + `/doctor` HTTP | feature | 300 LOC | Ops无法自诊断 |
| P1-2 | `/ops/release-gate` 单端点 | feature | 200 LOC | CI/CD准入无单点 |
| P1-3 | 抽`RunFinalizer` from runner.py | refactor | 600 LOC移动 | God object继续膨胀 |
| P1-4 | 抽`ReadinessProbe` from builder.py | refactor | 300 LOC移动 | God object继续膨胀 |
| P1-5 | Capability Plane最小治理 | feature | 115 LOC | RouteEngine可propose失效能力 |
| P2-1 | MCP `tools/list` + stderr tail | feature | 50 LOC | 工具必须plugin.json预声明 |
| P2-2 | Profile / HI_AGENT_HOME 隔离 | feature | 400 LOC | 多环境污染 |
| P2-3 | Golden path三层 + fake server fixtures | test infra | 800 LOC | prod E2E默认skip无信号 |

---

**End of audit report.**
