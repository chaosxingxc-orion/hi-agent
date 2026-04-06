# 对 `Feedback from agent-kernel team` 的可行性分析

> 依据：
> - `Feedback from agent-kernel team.txt`
> - `2026-04-05-trace-architecture-review-v1.2.1.md`
> - `2026-04-05-trace-contract-mapping.md`
> - `2026-04-05-trace-runtime-arbitration.md`

## 1. 结论先行

这份协商稿 `整体可行`，而且方向上是健康的。

它没有试图把 TRACE 的认知语义偷回 `agent-kernel`，反而在多数关键点上尊重了已经冻结的边界：

- `hi-agent` 拥有任务语义、CTS、Task View 选择、Route、Evolve、Skill 治理
- `agent-kernel` 提供 durable runtime、runtime truth、LLM Gateway、Harness 治理、仲裁与回放元数据
- `agent-core` 继续做能力供给层

因此，这份稿子 `可以作为联合推进的基础版本`。

但它还不应直接视为“已完全达成一致”，因为仍有 4 个需要收口的点；其中 2 个如果不改，会造成语义边界漂移。

## 2. 可以直接接受的部分

以下内容与 TRACE V1.2.1 基本一致，可以接受：

### 2.1 policy version freeze

- run 启动时冻结 `route/skill/evaluation/task_view_policy_version`
- waiting run 恢复时默认继续使用冻结版本
- 中途切换需显式 `change_record`

这与 TRACE 对 `policy version pinning` 的要求一致。

### 2.2 TraceRuntimeView + ActionState + 仲裁承诺

- `TraceRuntimeView` 作为派生真相视图而不是第二套状态机，是合理的
- `ActionState` 显式区分 `acknowledged` 与 `succeeded`，是必须项
- callback / timeout / effect_unknown / review gate 的仲裁承诺，与现有仲裁文档一致

### 2.3 TaskViewRecord 只存引用

- 内核只存 `evidence_refs / memory_refs / knowledge_refs`
- 不把 Task View 内容本体放入 kernel

这与 TRACE 对 Task View 边界的定义一致，避免了内容装配责任下沉到 kernel。

### 2.4 Kernel Boundaries

以下“不做”的边界是对的：

- 不解释 CTS / Stage Graph 业务语义
- 不拥有 route / prune 决策
- 不拥有 skill 生命周期
- 不拥有 evolve 触发逻辑
- 不向上暴露内部实现细节

这说明对方没有试图把 `agent-kernel` 变成上层 agent 编排器，这一点是健康的。

### 2.5 V1 推迟项总体合理

以下内容推迟到 V2，整体上可接受：

- `replay_old_run_under_old_versions`
- `evolve change set` 回滚机制
- 完整 skill 五阶段管理
- 批量 run 级 metrics aggregation

前提是：

- `V1` 仍要保留版本冻结、Task View 引用、change_record、evidence replay metadata
- 推迟的是“完整基础设施”，不是把“审计与追溯能力”一起推迟掉

## 3. 需要返修或联合澄清的点

### 3.1 `TraceRuntimeView` 缺少 `StageState`

问题位置：

- `Feedback from agent-kernel team.txt` 第 18-21 行

当前稿子里 `TraceRuntimeView` 包含：

- `RunState`
- `WaitState`
- `ReviewState`
- `BranchState`

但缺了 `StageState`。

这会带来一个直接问题：

- `hi-agent` 若要判断阶段是否阻塞、完成、失败，就必须自己从事件拼阶段状态
- 于是运行时真相会重新分裂成“kernel 真相”和“hi-agent 推导真相”

建议：

- 要么把 `StageState` 纳入 `TraceRuntimeView`
- 要么提供 `get_stage_state(run_id, stage_id)` 作为一等查询接口

这一点我认为是 `必须补齐` 的，不然 TRACE 的 Stage 只会停留在文档层。

### 3.2 不应把 `Branch` 固化成 `child run`

问题位置：

- `Feedback from agent-kernel team.txt` 第 102-110 行

对方给了两个方案，并推荐：

- `1 Branch = 1 child run`

这条我不建议直接接受。

原因是：

- TRACE 的 `Branch` 是逻辑轨迹分支，不是内核执行容器
- 一个 Branch 可以包含多步 route compare、多个 action、多个 wait/resume
- 如果把 Branch 直接等同 child run，会把 kernel 的执行模型倒灌成 TRACE 的语义模型

更稳妥的约束应该是：

- `Branch` 始终是 TRACE 的逻辑身份
- `child run` 只是 kernel 的一个可选执行承载方式
- 在某些实现里可以 `1 Branch -> 1 child run`
- 但这不应成为架构层强约束

这是本轮最需要守住的边界之一。

### 3.3 `budget_exhausted` 的归属边界不够清楚

问题位置：

- `Feedback from agent-kernel team.txt` 第 51-53 行
- `Feedback from agent-kernel team.txt` 第 115-120 行

当前稿子写法容易让人理解成：

- kernel 在 `budget_exhausted` 时会触发 escalation / Human Gate B

问题在于 TRACE 里至少有两类 budget：

- `CTS exploration budget`
- `runtime / harness execution budget`

如果不区分，就会出现边界漂移：

- kernel 可能开始替 hi-agent 判断“探索预算耗尽”
- 但 CTS 预算本来是 route / prune 策略的一部分，应由 hi-agent 解释

建议：

- 明确区分 `trace_budget_domain`
- 至少分成：
  - `exploration_budget_exhausted`
  - `execution_budget_exhausted`
- kernel 只能直接判定自己掌握的执行预算与运行预算
- CTS 预算是否耗尽，由 hi-agent 基于 kernel 暴露的指标来判断

### 3.4 `TaskViewRecord` 与 `decision_ref` 的绑定仍有循环依赖风险

问题位置：

- `Feedback from agent-kernel team.txt` 第 76-79 行
- `Feedback from agent-kernel team.txt` 第 93-99 行

当前稿子已经意识到了问题，但契约还没完全闭合：

- Task View 需要在模型调用前记录
- 但 `decision_ref` 往往要到本轮 intent/decision 写入后才稳定出现

如果这一步不处理成两阶段绑定，就会出现：

- hi-agent 为了拿 `decision_ref` 先走一遍内核内部记录
- 上层被迫理解 `TurnIntent` 之类的内核内部对象

建议：

- 采用两阶段绑定
- 第一步：`record_task_view` 返回 `task_view_id`
- 第二步：在本轮 decision / signal / intent commit 后，由 kernel 用 `bind_task_view_to_decision(task_view_id, decision_ref)` 或等价机制补关联

结论上，我同意他们偏向的 “方案 A”，但要明确它本质上是 `pre-record + late-bind`，不是一次调用就要求 hi-agent 已知 decision 内部 ID。

## 4. 对 V1 范围的判断

如果以上 4 点收口，我认为这份协商稿 `足以支持 V1 联合落地`。

更准确地说：

- 它已经足够支持 `hi-agent` 和 `agent-kernel` 开始进入契约冻结
- 也足够支持双方先按 `Phase 1 + Phase 2` 做接口推进
- 但还不适合直接宣称“TRACE 与 kernel 边界已完全闭合”

当前更合适的结论是：

`该协商稿具备可行性，可以作为联合实现基线；但需在 StageState、Branch 语义、budget 边界、TaskView 决策绑定 4 点上补一轮小修后再冻结。`

## 5. 我建议给 `agent-kernel` 团队的回应口径

可以直接回这 4 条：

1. `TraceRuntimeView` 请补 `StageState`，否则上层会被迫自行拼阶段真相。
2. `Branch` 不应在架构层固定等同 `child run`，child run 只能是实现承载方式。
3. `budget_exhausted` 请拆分预算域，避免 kernel 侵入 CTS 探索语义。
4. `TaskViewRecord` 与 `decision_ref` 请采用两阶段绑定，避免 hi-agent 感知内核内部对象。

除此之外，其余协商项我认为可以接受。
