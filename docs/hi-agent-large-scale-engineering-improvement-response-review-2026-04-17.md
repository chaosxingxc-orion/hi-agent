# hi-agent 大规模工程落地反馈方案评审意见

**日期**：2026-04-17  
**评审对象**：`.claude/worktrees/distracted-poitras/docs/hi-agent-large-scale-engineering-improvement-response-2026-04-17.md`  
**关联原方案**：`docs/hi-agent-large-scale-engineering-improvement-plan-2026-04-17.md`  
**评审结论**：原则接受，但需要修正实施边界、数据合同和风险门控后再进入 Week 1 执行  

---

## 0. 给工程实施团队的总体结论

你们这份响应文档不是简单复述原方案，而是做了代码级核验，并据此调整了优先级。这个方向是正确的。

从代码事实看，你们提出的 4 个关键修订大体成立：

1. MCP 不应再被简单归类为完全 `infrastructure-only`。当前 stdio subprocess、`initialize`、`tools/call`、health check、binding 和 HTTP 正向链路已经存在，并且有集成测试覆盖。
2. `evolve_enabled=True` 默认开启确实是生产风险，应前移到 P0 处理。
3. `_heuristic` 已经在 capability fallback 层产生，但没有传播到 `RunResult`，这是 runtime truth 的关键断链点。
4. RBAC/SOC 相关模块和测试存在，但尚未接入敏感业务路由，治理能力没有进入真实使用路径。

因此，我建议接受你们对原 12 周路线的部分修订：先处理真实阻断点，再推进大规模拆分。

但这份响应文档还不能直接作为执行令。它的问题主要集中在三类：

1. **部分工作量估算偏乐观**：尤其是 MCP 动态发现与 stderr 消费，不应被描述成约 50 LOC 即可生产闭合。
2. **部分 MVP 设计会制造二次迁移**：尤其是 `execution_provenance` 如果先做单字符串 enum，很快会无法表达混合执行路径。
3. **部分治理接线边界尚未想透**：尤其是把 SOC 分离直接套到 `POST /runs`，可能混淆“任务提交”和“高风险审批”的语义。

建议调整后的执行策略是：

> 批准 P0 优先级调整，但将 Week 1 定义为 “Baseline + Runtime Truth MVP + Evolve Gate”，而不是一次性宣布 M1 完整达成。MCP 与 Capability Plane 进入 Week 2-5 做稳，SystemBuilder 与 RunExecutor 拆分必须先加 characterization tests 再动结构。

---

## 1. 已核验并建议接受的判断

### 1.1 MCP 现状修正：接受，但表述要降调

你们指出 MCP 当前并非完全没有真实 transport，这一点成立。

代码证据包括：

- `hi_agent/mcp/transport.py` 中已有 `StdioMCPTransport`。
- transport 已支持 subprocess 启动、`initialize` ping、`tools/call`、timeout、Windows thread fallback。
- `hi_agent/mcp/binding.py` 会在 server healthy 后把 manifest 预声明 tool 绑定进 `CapabilityRegistry`。
- `tests/integration/test_mcp_integration.py` 覆盖了 MI-01 到 MI-08 的真实 subprocess 正向链路。

我本地核验了相关测试：

```powershell
python -m pytest tests\integration\test_mcp_integration.py tests\test_auth_rbac.py -q
```

结果：

```text
17 passed in 0.89s
```

所以，原方案中“MCP 外部 transport 仍未实现”的表述需要修正。

但你们的响应文档也需要同步降调：当前 MCP 不是从 0 到 1，但也没有达到生产级闭环。当前仍然存在以下缺口：

- transport 层没有独立 `tools/list` 方法。
- `MCPBinding` 仍依赖 `plugin.json` 预声明 tools，不能动态发现未知工具。
- stderr 只是 pipe，没有被稳定消费、裁剪、持久化和暴露到 health。
- subprocess lifecycle 没有完整的 restart/backoff/kill/cleanup 策略。
- schema version、tool schema drift、server capability negotiation 尚未治理。
- auth、token、enterprise allowlist、per-server permission 仍缺失。

因此，建议把 MCP 状态改成：

> stdio MCP 正向调用链路已存在，当前缺口从“基础 transport 实现”收敛为“动态发现、进程健康、stderr 诊断、schema/versioning、权限和生产治理”。

不要把 MCP 修复压缩成“约 50 LOC 增量修复”。可以说：

- Week 4 可交付最小 `tools/list` 动态发现。
- Week 4-5 可交付 stderr tail 与 health report。
- Week 6 以后再处理 schema/versioning/auth/permission。

### 1.2 Evolve 默认开启：接受，并建议 P0 提级

你们把 `evolve_enabled=True` 提为 P0 是正确的。

当前事实：

- `hi_agent/config/trace_config.py` 中 `evolve_enabled` 默认值为 `True`。
- `hi_agent/runner_lifecycle.py` 中 run 完成后会调用 `evolve_engine.on_run_completed(postmortem)`。
- 当 `evolve_result.changes` 存在且 `route_engine` 存在时，会调用 `route_engine.apply_evolve_changes(...)`。
- regression detection 当前只是 warning，不是阻断。

这意味着生产路径默认允许 run completion 后触发策略或 skill 相关 mutation。即使这些 mutation 不总是发生，默认开启本身也违背生产平台的安全原则。

建议接受 P0，但不要只做“一行默认值”。

正确目标应该是：

1. 默认行为可解释。
2. dev 与 prod 行为可区分。
3. 下游可以从 `/ready`、`/manifest`、`doctor` 看到 evolve 是否开启，以及为什么开启。
4. 显式开启时进入 audit log。

推荐方案不是直接 `True -> False`，而是三态：

```python
evolve_mode: Literal["auto", "on", "off"] = "auto"
```

解析规则：

- `dev-smoke`：`auto` 解析为 `on` 或 `warn_on`，保留研发体验。
- `local-real`：`auto` 解析为 `off`，除非显式开启。
- `prod-real`：`auto` 解析为 `off`，`on` 必须由 profile policy 或 env/CLI 显式开启。

如果短期不想引入三态，也可以先保留 `evolve_enabled: bool`，但必须同时补：

- `HI_AGENT_ENABLE_EVOLVE`。
- CLI `--enable-evolve`。
- readiness 字段 `evolve_enabled` 与 `evolve_source`。
- manifest 字段 `evolve_policy`。
- migration note。
- 显式开启时 audit event。

### 1.3 Runtime Provenance 断链：接受，但字段设计需要升级

你们指出 `_heuristic` 已在 capability fallback 层产生，但没有传播到 `RunResult`，这个判断成立。

但你们建议 Week 1 先做：

```python
execution_provenance: str | None
```

并限定为：

```text
heuristic_fallback | llm_real | kernel_http | kernel_local
```

这个 MVP 不建议采用。

原因是一次 run 不是单一来源。一个 run 可能同时出现：

- kernel 是 local-fsm。
- LLM 是 real。
- 某个 capability 是 heuristic fallback。
- 某个 tool 是 MCP external。
- memory/knowledge 是 local store。
- 部分 stage 失败后 fallback。

单字符串无法表达混合路径，后续一定会迁移。既然这是对外合同字段，应该第一版就做结构化。

建议第一版即采用结构化 dict，字段保持最小：

```json
{
  "execution_provenance": {
    "contract_version": "2026-04-17",
    "runtime_mode": "dev-smoke",
    "llm_mode": "heuristic",
    "kernel_mode": "local-fsm",
    "capability_mode": "sample",
    "mcp_transport": "not_wired",
    "fallback_used": true,
    "fallback_reasons": ["missing_llm_gateway"],
    "evidence": {
      "heuristic_stage_count": 1,
      "real_capability_count": 0,
      "mcp_tool_call_count": 0
    }
  }
}
```

最小实现可以先只填一部分字段，但 shape 不要再变。

建议验收标准：

- dev fallback completed run 必须 `fallback_used=true`。
- prod mode 不允许 `fallback_used=true` 后仍作为 production success 返回。
- stage summary 中若有 `_heuristic`，run-level provenance 必须聚合出来。
- `/manifest` 声明 provenance contract version。
- `tests/integration/test_prod_e2e.py` 从字符串扫描升级为结构化字段断言。

### 1.4 `/manifest` 读取真实环境：接受，且应进入 P0

你们指出 `/manifest.runtime_mode` 硬编码 `"platform"`，这个判断成立。

这属于低成本、高收益的 runtime truth 修复，应进入 P0。

但注意不要只读取 `HI_AGENT_ENV`。建议 runtime vocabulary 与 `/ready`、`RunResult.execution_provenance` 对齐。

推荐字段：

```json
{
  "runtime_mode": "dev-smoke | local-real | prod-real",
  "environment": "dev | test | prod",
  "execution_mode": "local | http",
  "kernel_mode": "local-fsm | http",
  "llm_mode": "heuristic | real | disabled",
  "provenance_contract_version": "2026-04-17"
}
```

如果短期只能实现一部分，也至少要做到：

- 不再硬编码 `"platform"`。
- `/manifest` 与 `/ready` 中同名字段取值一致。
- 增加 snapshot/golden test 防止未来再次漂移。

### 1.5 RBAC/SOC 未接线：接受，但接线范围要调整

你们指出 `RBACEnforcer` 与 `SOCGuard` 存在但未接入 server route，这个判断基本成立。

但 P0-4 的范围需要调整。

建议优先接入这些高风险 mutation 路由：

- `POST /skills/{skill_id}/promote`
- `POST /skills/evolve`
- `POST /memory/consolidate`
- 后续再评估 `POST /runs/{run_id}/resume`、`POST /runs/{run_id}/signal`、management gate resolve 等操作

不建议第一版把 SOC 分离直接套到普通 `POST /runs`。

原因：

- 提交任务不是天然审批动作。
- submitter 与 approver 的分离应发生在高风险 tool、dangerous command、prod mutation、manual approval gate 等场景。
- 粗暴给 `POST /runs` 加 submitter/approver 约束，会破坏大量下游和现有测试。
- 更容易导致团队为了兼容而在 dev/prod 中散落 bypass 逻辑，反而削弱治理。

建议 Week 1 做：

- 统一 `AuthorizationContext`。
- 统一 `RoutePolicy` 或 `require_operation(operation_name)` helper。
- mutation route 声明 operation name。
- prod 模式 enforce，dev 模式 allow 但记录 `auth_bypass_reason`。
- 所有 deny 返回 typed error，并进入 audit。

不要在每个 handler 里散写 role 判断。

---

## 2. 需要修正的路线与里程碑

### 2.1 M1 不应在 W1 宣布完整达成

你们将 M1 Runtime Truth 从 W3 提前到 W1，这个目标太激进。

W1 可以交付 Runtime Truth MVP，但不应声明完整 M1。

完整 M1 至少包括：

- runtime mode 统一 vocabulary。
- run-level provenance。
- stage-level provenance。
- capability/action-level provenance。
- `/ready`、`/manifest`、`RunResult` 字段一致。
- prod fallback fail-close。
- prod missing prerequisites 的错误 shape 固定。
- snapshot/golden tests 固化。

W1 更合理的定义：

> W1 交付 Runtime Truth MVP：evolve gate、run-level structured provenance、manifest truthfulness、prod fallback 不可伪装为 success。

M1 完整达成可以放在 W2 末或 W3 末，保留原方案节奏。

### 2.2 M4 提前到 W5 可以接受，但定义要缩小

你们将 M4 Real Tool Plane 提前到 W5，只有在定义缩小后才合理。

W5 可交付的是：

- capability descriptor 最小治理。
- required env availability。
- unavailable capability 不被 route engine 选择。
- manifest 输出结构化 capability view。
- MCP `tools/list` 动态发现最小闭环。

W5 不应承诺完整 Real Tool Plane。

完整 Real Tool Plane 还包括：

- permission policy 与 tool risk class。
- output budget。
- artifact integration。
- audit trail。
- schema versioning。
- MCP health degradation。
- server restart/backoff。
- profile-scoped tool state。
- enterprise allowlist。

建议 M4 改名为：

> M4A：Minimum Governed Tool Plane。

完整 M4 仍保留在 W8-W10。

### 2.3 SystemBuilder 拆分顺序基本合理，但要加准入条件

你们提出从低风险 builder 开始拆，这是正确方向。

但每一步必须满足准入条件：

1. 先写 characterization test。
2. 证明外部 API shape 不变。
3. 新 builder 不得访问其它 builder 私有属性。
4. 新 builder 不得引入新的 post-construction mutation。
5. 每一步都能独立回滚。

特别注意：

- `ReadinessProbe` 可优先拆，因为它是观察面。
- `SkillBuilder`、`MemoryBuilder`、`KnowledgeBuilder` 可做早期拆分。
- `RuntimeBuilder` 和 `CapabilityPlaneBuilder` 是高风险拆分，不应提前。
- profile 派生时共享 mutable cache 的问题要先标注和测试，不要顺手大改。

### 2.4 RunFinalizer 可以先拆，但不能说“纯只读”

你们把 `RunFinalizer` 作为 RunExecutor 的第一拆分点，这个方向可以接受。

但文档里“纯只读、无回写”的表述需要删除。

finalization 明显涉及副作用：

- memory finalization。
- episode build/store。
- feedback/evolve。
- telemetry。
- failure attribution。
- pending subrun cancellation。
- artifact/result assembly。

它可以被拆，不是因为它纯，而是因为它是一个相对清晰的生命周期阶段，适合被封装为副作用协调器。

建议目标改为：

> 将 run finalization 的副作用集中到 `RunFinalizer`，用 characterization tests 固化 completed/failed/cancelled 三类 outcome 的外部行为。

---

## 3. 对 6 个开放问题的评审意见

### Q1：Evolve 默认行为

建议选 B：三态 `auto | on | off`。

推荐解析：

- dev-smoke：`auto -> on` 或 `auto -> warn_on`。
- local-real：`auto -> off`。
- prod-real：`auto -> off`。
- prod-real 下 `on` 必须显式配置，并进入 audit。

如果 Week 1 时间紧，可以先用 bool，但文档必须声明这是临时兼容层，最终会迁移到 policy-driven evolve mode。

### Q2：`execution_provenance` 字段形态

建议直接选 B：结构化 dict。

不要先上 A 的单字符串 enum。它会很快无法表达混合执行路径，并且这是对外合同字段，二次迁移成本不值得。

### Q3：`/ops/release-gate` prod-real 门控时长

建议选 A：72 小时内有通过。

补充规则：

- nightly 使用 72 小时窗口。
- release candidate 使用更严格规则：目标 commit 或 release branch 最近一次 prod-real 必须通过。
- 无 secrets 时 nightly 可 skipped，但 release gate 不应把 skipped 当 pass。

### Q4：RBAC 默认 role 矩阵

建议选 B：`submitter | approver | auditor | admin`。

`viewer | operator | admin` 可以作为产品层角色映射，但底层 governance 语义应贴近操作风险。

推荐初始映射：

```text
viewer   -> auditor
operator -> submitter
admin    -> approver + admin
```

SOC guard 应该针对需要审批的 mutation/action，而不是所有任务提交。

### Q5：SystemBuilder 拆分是否允许阶段性共存

建议选 A：允许 facade 阶段性共存。

这是大规模工程里更安全的路径。每个 builder 拆分都应是一组小 PR，不要一次性切掉旧路径。

### Q6：Coverage 门槛提升节奏

建议选 A：W4/W8/W12 分别 70/75/80。

但要先确认工具支持。不要假设 `pytest-cov` 原生支持 per-package fail_under。更稳的方式是：

- 全局 coverage 继续用现有配置。
- 核心包 coverage 用单独脚本基于 coverage json/xml 检查。
- 新增代码 coverage 用 changed-files 或 diff coverage 单独门控。

---

## 4. 建议调整后的 Week 1 执行计划

Week 1 不建议做“四连击 + 完整 M1”。建议聚焦更硬的三件事：

1. 冻结基线。
2. 关闭或门控生产 evolve。
3. 打通 runtime truth 的最小可验证链路。

### Day 1：基线冻结

必须产出：

- full pytest 结果。
- ruff 结果。
- coverage 摘要。
- 当前 `/ready` 样例。
- 当前 `/manifest` 样例。
- 当前 `/mcp/status` 样例。
- dev `POST /runs -> GET /runs/{id}` 样例。
- prod prerequisites missing 行为样例。

产物建议：

```text
docs/platform/current-runtime-baseline-2026-04-17.md
```

没有基线，不进入重构。

### Day 2：Evolve Gate

交付：

- `evolve_enabled` 或 `evolve_mode` 默认生产关闭。
- env/CLI/profile 显式开启机制。
- readiness/manifest/doctor 可观察。
- 显式开启进入 audit。
- dev 兼容策略明确。

测试：

- 默认 run 不触发 evolve mutation。
- 显式开启时保持当前行为。
- prod auto/off 不 apply evolve changes。

### Day 3：Structured Execution Provenance

交付：

- `RunResult.execution_provenance` 结构化字段。
- `RunResult.to_dict()` 输出。
- `_finalize_run` 聚合 `_heuristic`。
- stage summary 与 run-level provenance 不矛盾。

测试：

- dev fallback run 输出 `fallback_used=true`。
- prod E2E 测试断言不允许 heuristic fallback。
- 对外 JSON shape snapshot。

### Day 4：Manifest Truthfulness

交付：

- `/manifest.runtime_mode` 不再硬编码。
- `/manifest` 与 `/ready` vocabulary 对齐。
- `provenance_contract_version`。
- manifest snapshot/golden test。

测试：

- `HI_AGENT_ENV=dev` 输出 dev 或 dev-smoke。
- `HI_AGENT_ENV=prod` 输出 prod 或 prod-real。
- manifest 与 ready 中同名字段一致。

### Day 5：RBAC/SOC 最小接线 RFC + 首批 route 接线

交付：

- route operation policy 表。
- `AuthorizationContext`。
- mutation route 最小接线。
- dev bypass 可观察。
- prod deny typed error。

首批只接：

- `POST /skills/{skill_id}/promote`
- `POST /skills/evolve`
- `POST /memory/consolidate`

`POST /runs` 暂不强制 SOC，除非该 run 触发 high-risk approval profile。

---

## 5. Week 2-5 建议调整

### 5.1 Doctor 与 release gate 可提前，但 release gate 初期不要过度承诺

`doctor` 可以在 Week 2 做，因为它复用 readiness，很适合补操作员体验。

但 `/ops/release-gate` 第一版建议只聚合：

- readiness。
- doctor blocking。
- config validation。
- current runtime mode。
- known prerequisites。

prod-real 最近通过记录可以先作为 `skipped | missing` gate 输出，不要在未建立 nightly 之前就强制 fail 所有部署。

### 5.2 Capability Plane 最小治理要兼容 manifest

你们提出 `/manifest.capabilities` 从 `list[str]` 改为 `list[CapabilityView]`，这是 breaking change。

建议改成兼容方案：

```json
{
  "capabilities": ["trace.route", "trace.act"],
  "capability_views": [
    {
      "name": "trace.act",
      "status": "available",
      "toolset_id": "trace-default",
      "required_env": [],
      "effect_class": "read",
      "output_budget_tokens": 4096
    }
  ]
}
```

至少保留一个版本周期，再考虑替换旧字段。

### 5.3 MCP 动态发现不要只做 happy path

`tools/list` 动态发现至少需要覆盖：

- 正常返回 tools。
- 返回空 tools。
- 返回 invalid schema。
- timeout。
- server stderr 有内容。
- server crash。
- manifest 预声明 tools 与动态发现 tools 冲突。

建议 merge 策略：

- 动态发现为准。
- manifest 预声明作为 bootstrap hint。
- 冲突时 manifest 进入 warning，不阻塞 server，但该 tool 标记 degraded。

---

## 6. 必须避免的执行误区

### 6.1 不要把“测试多”当作“生产可信”

MCP 相关测试能通过，说明 stdio 正向链路存在，不代表 MCP 生产治理已经完成。

后续测试必须覆盖：

- health degradation。
- stderr 诊断。
- unavailable tool 不被 route engine 选择。
- direct invoke unavailable tool 抛 typed error。
- manifest 与 readiness 不矛盾。

### 6.2 不要先上临时对外字段再迁移

`execution_provenance` 是下游会依赖的字段。第一版 shape 应该慎重。

宁可字段内部先填少一点，也不要先用错误的数据模型。

### 6.3 不要把权限逻辑写散

RBAC/SOC 如果散落在 handler 中，后续一定会出现不一致。

建议统一：

```text
route -> operation_name -> RoutePolicy -> RBAC/SOC decision -> audit -> typed response
```

### 6.4 不要一边拆 God Object 一边改业务语义

SystemBuilder 和 RunExecutor 拆分阶段必须坚持：

- 先 characterization。
- 再移动代码。
- 外部行为不变。
- 最后再做语义修正。

否则会分不清回归来自结构迁移还是行为变更。

---

## 7. 评审通过条件

建议你们在正式进入 Week 1 前，先按以下条件修订响应文档：

1. 将 MCP 状态从“只剩 50 LOC”改为“stdio 正向链路已存在，但生产治理仍需分阶段补齐”。
2. 将 `execution_provenance` MVP 从字符串 enum 改为结构化 dict。
3. 将 evolve 默认行为从简单 bool 讨论升级为 dev/prod 可解析 policy。
4. 将 RBAC/SOC 的 `POST /runs` 强制接线改为 high-risk approval 场景接线。
5. 将 W1 M1 “完整达成”改为 W1 “Runtime Truth MVP”。
6. 将 `/manifest.capabilities` breaking change 改为兼容新增字段。
7. 将 `RunFinalizer` “纯只读”表述改为“副作用集中封装”。
8. 在 Week 1 第一天加入 baseline freeze，产出可比较基线文档。

满足以上 8 条后，可以批准进入 Week 1。

---

## 8. 建议的最终执行口径

给团队的执行口径建议如下：

> 我们接受工程团队基于代码审计提出的优先级修订。当前最紧急目标不是继续扩展认知子系统，也不是立刻大拆 God Object，而是先让平台对自己的运行状态诚实、可机器判断、可被下游信任。
>
> Week 1 聚焦 Runtime Truth MVP：冻结基线、门控 evolve、传播结构化 provenance、修正 manifest、接入 mutation route 的最小治理。MCP、Capability Plane、doctor、release gate 在 Week 2-5 推进，SystemBuilder 和 RunExecutor 拆分必须以 characterization tests 为前置条件。
>
> 任何对外合同字段都必须一次性设计到足够表达真实路径，宁可先少填字段，也不要发布会很快废弃的临时 shape。

---

## 9. 最终判断

这份响应方案值得推进，但不能原样执行。

它比原方案更贴近代码现实，尤其在 MCP、evolve、provenance、RBAC/SOC 四个点上给出了有价值的修正。然而，它也有工程实施中常见的乐观风险：看到局部链路已通，就低估生产闭环；看到字段好加，就低估对外合同；看到权限模块存在，就低估接线语义。

调整后的方向应该是：

1. 接受 P0 提级。
2. 收紧 Week 1 范围。
3. 结构化 provenance 一步到位。
4. Evolve 进入 profile/policy gate。
5. RBAC/SOC 先保护 mutation 与 high-risk approval。
6. MCP 按“已有正向链路，补生产治理”推进。
7. God Object 拆分坚持 characterization-first。

这样执行，既能吸收工程团队的代码级发现，也能避免把新的过度乐观变成下一轮技术债。

