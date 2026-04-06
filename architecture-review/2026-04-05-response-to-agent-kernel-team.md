# 致 `agent-kernel` 团队的正式回复

> 依据文件：
> - `Feedback from agent-kernel team.txt`
> - `2026-04-05-trace-architecture-review-v1.2.1.md`
> - `2026-04-05-trace-contract-mapping.md`
> - `2026-04-05-trace-runtime-arbitration.md`

各位同学，

我们认真审阅了这版《agent-kernel TRACE 对齐边界确认》协商稿。总体判断是：这份稿子方向正确、边界意识清楚，已经具备作为双方联合推进基线的可行性。

尤其是以下几点，我们认为与你们的理解已经基本对齐：

- `policy version freeze` 的 run 级冻结机制是合理且必要的
- `TraceRuntimeView`、`ActionState.succeeded`、callback/timeout/effect_unknown 仲裁承诺符合 TRACE 对 durable runtime 的要求
- `TaskViewRecord` 仅记录引用、不下沉内容装配责任，这一点边界是正确的
- `agent-kernel` 不拥有 CTS / Route / Evolve / Skill 生命周期等上层语义，这一分工我们认可
- 部分高成本能力推迟到后续版本，也符合 V1 收敛原则

因此，我们的态度不是要求重写这份协商稿，而是建议在少量关键点上补一轮小修后，再作为冻结版本共同使用。

## 一、我们建议直接接受的内容

以下部分我们建议直接确认：

1. `Run lifecycle with policy version freeze`
2. `ActionState` 显式包含 `succeeded`
3. callback 优先于后续 timeout 的仲裁原则
4. `effect_unknown` 进入恢复面，不自动重发 irreversible 动作
5. waiting run 恢复时默认沿用冻结版本
6. `ReviewState != approved` 时，不自动推进高风险动作
7. `TaskViewRecord` 作为一等记录对象，但只存引用
8. kernel 不拥有 Task View 内容装配策略
9. kernel 不拥有 CTS / Stage Graph 语义
10. kernel 不拥有 route / prune / evolve / skill lifecycle 的上层逻辑

这些点与我们当前冻结的 TRACE V1.2.1 一致，可以作为双方共识。

## 二、建议补齐后再冻结的 4 个点

### 1. `TraceRuntimeView` 请补 `StageState`

当前协商稿中的 `TraceRuntimeView` 已包含：

- `RunState`
- `WaitState`
- `ReviewState`
- `BranchState`

但尚未显式包含 `StageState`。

我们建议补上这一层，原因很直接：

- TRACE 的阶段推进不是纯文档概念，而是上层 route、capture、evaluate 的正式对象
- 如果 kernel 不暴露阶段真相，上层就只能从事件自行拼 `StageState`
- 这会导致运行时真相重新分裂为 “kernel 真相” 与 “hi-agent 推导真相”

我们接受两种等价实现方式：

- 方案 A：`TraceRuntimeView` 直接包含 `StageState`
- 方案 B：额外提供 `get_stage_state(run_id, stage_id)` 一等查询接口

但无论哪种方式，`StageState` 本身需要成为稳定公共契约的一部分。

### 2. 不建议在架构层将 `Branch` 固定等同 `child run`

我们理解你们提出 `1 Branch = 1 child run` 的出发点，是希望边界清晰、便于实现。

但从 TRACE 语义上，我们不建议把这条上升为架构层约束。

原因是：

- `Branch` 是 TRACE 的逻辑轨迹分支
- `child run` 是 kernel 的执行承载方式
- 一个 Branch 在抽象上可能包含多轮 route compare、多个 action、多个 wait/resume

因此，我们建议的表述是：

- `Branch` 始终是逻辑身份
- `child run` 可以是某些实现中的承载方式
- 在 V1 实现里允许采用 `1 Branch -> 1 child run` 的近似映射
- 但该映射不应写成架构冻结语义

这样可以避免未来 kernel 的执行模型反向约束 TRACE 的演化空间。

### 3. `budget_exhausted` 请区分预算域

当前协商稿里，`budget_exhausted` 既出现在 branch/prune 边界讨论里，也出现在 Human Gate B 的触发语境里。

这里我们建议补一个更清晰的边界：

- TRACE 至少存在 `exploration budget`
- 同时也存在 runtime / harness 侧的 `execution budget`

这两类预算不完全同义。

因此建议：

- kernel 可直接治理并上报自己掌握的执行预算、运行预算、超时预算
- CTS 探索预算是否耗尽，应由 hi-agent 基于 kernel 暴露的数据进行解释与决策
- 如果需要统一 failure/event 命名，建议至少区分：
  - `exploration_budget_exhausted`
  - `execution_budget_exhausted`

这样可以避免 kernel 无意中接管 CTS 层的认知决策语义。

### 4. `TaskViewRecord` 与 `decision_ref` 建议采用两阶段绑定

我们同意你们判断：`hi-agent` 不应感知 `TurnIntent` 等 kernel 内部 ID。

但如果要求 `TaskViewRecord` 在第一次提交时就与最终 `decision_ref` 强绑定，会形成一个时序循环：

- Task View 需要在模型调用前记录
- decision / intent commit 往往要在本轮调用后才稳定出现

因此，我们建议明确采用两阶段绑定：

1. `hi-agent` 先调用 `record_task_view(...)`
2. kernel 返回 `task_view_id`
3. 后续在 decision / signal / intent commit 完成后，由 kernel 侧进行补关联

可以通过任一等价方式实现：

- `signal` 时携带 `task_view_id`，由 kernel 自动绑定
- 或提供显式 `bind_task_view_to_decision(task_view_id, decision_ref)` 能力

我们倾向于前者，但关键点不是具体接口名，而是要把这个模式明确成：

`pre-record + late-bind`

## 三、对 V1 范围的态度

对于你们提出暂不纳入 V1 的几项能力，我们总体接受：

- `replay_old_run_under_old_versions`
- `evolve change set` 回滚机制
- 完整 skill 五阶段生命周期管理
- 批量 run 级 metrics aggregation

我们的前提只有一个：

V1 虽可不做完整高级基础设施，但必须保留未来演进所需的最小元数据基础，尤其是：

- version freeze
- change record
- Task View 引用回放能力
- action / callback / recovery 的稳定仲裁记录

只要这些基础在，V1 到后续版本的升级路径就是连续的。

## 四、我们的总体结论

我们的正式结论是：

`该协商稿具备可行性，可以作为 hi-agent 与 agent-kernel 联合推进的基础版本；建议在 StageState、Branch 语义、budget 边界、TaskView 决策绑定 4 点上完成一轮小修后，再作为冻结版本使用。`

如果你们认可，我们建议下一步按以下顺序推进：

1. 双方先确认上述 4 个小修点
2. 将协商稿更新为一版 joint frozen draft
3. 再基于 frozen draft 进入接口落地与仓间联调

以上是我们的正式反馈，供双方继续收口。
