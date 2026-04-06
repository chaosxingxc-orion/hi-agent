# TRACE 运行时状态转移与事件仲裁

> 依据版本：`2026-04-05-trace-architecture-review-v1.2.1.md`
> 目标：把 TRACE 的运行时真相从“状态草图”提升为“可实现仲裁基线”
> 说明：本文件仍是架构契约文档，不是代码实现说明

## 1. 目的

TRACE 能否真正 7x24 工作，关键不在模型推理链，而在运行时能否对以下场景给出唯一真相：

- callback 和 timeout 同时到来
- action 已受理但未完成
- human gate 修改了 task contract
- branch 在 waiting 时策略版本发生变化
- action 结果不确定但任务不能重复污染外部系统

因此，本文件定义：

- 状态对象
- 关键事件
- 合法转移
- 仲裁优先级
- 幂等语义

## 2. 运行时对象

TRACE 运行时至少包含 6 类状态对象：

- `RunState`
- `StageState`
- `BranchState`
- `ActionState`
- `WaitState`
- `ReviewState`

## 3. 状态定义

### 3.1 RunState

允许状态：

- `created`
- `active`
- `waiting`
- `recovering`
- `completed`
- `failed`
- `aborted`

语义：

- `created`：运行已建立，但尚未进入有效执行
- `active`：存在可执行阶段或分支
- `waiting`：运行因外部回调、人审或定时恢复而暂停推进
- `recovering`：运行正在处理不确定结果、恢复策略或补偿策略
- `completed`：任务达成终态且通过完成判定
- `failed`：任务进入不可继续的失败终态
- `aborted`：被人工或系统显式终止

### 3.2 StageState

允许状态：

- `pending`
- `active`
- `blocked`
- `completed`
- `failed`

### 3.3 BranchState

允许状态：

- `proposed`
- `active`
- `waiting`
- `pruned`
- `succeeded`
- `failed`

### 3.4 ActionState

允许状态：

- `prepared`
- `dispatched`
- `acknowledged`
- `succeeded`
- `effect_unknown`
- `failed`

关键区分：

- `acknowledged`：外部系统已受理请求
- `succeeded`：动作真正完成，可采集结果与证据
- `effect_unknown`：无法确定外部副作用是否已发生

### 3.5 WaitState

允许状态：

- `none`
- `external_callback`
- `human_review`
- `scheduled_resume`

### 3.6 ReviewState

允许状态：

- `not_required`
- `requested`
- `in_review`
- `approved`
- `rejected`

## 4. 身份与幂等键

最小身份集合：

- `task_id`
- `run_id`
- `stage_id`
- `branch_id`
- `action_id`
- `attempt_id`
- `callback_id`

最小幂等原则：

- 每个外部动作必须具备稳定 `idempotency_key`
- 每个 callback 必须通过 `callback_id` 去重消费
- `action_id` 标识动作语义身份
- `attempt_id` 标识同一动作的重试轮次

## 5. 合法状态转移

### 5.1 RunState 转移

| 当前状态 | 事件 | 下一状态 | 说明 |
|------|------|------|------|
| `created` | `run_started` | `active` | 进入执行 |
| `active` | `run_wait_requested` | `waiting` | 无可立即推进路径，需要等待 |
| `waiting` | `wakeup_received` | `active` | 回调/人审/定时恢复触发 |
| `active` | `recovery_required` | `recovering` | 进入恢复面 |
| `recovering` | `recovery_resolved_continue` | `active` | 恢复后继续 |
| `active` | `run_completed` | `completed` | 达成完成条件 |
| `active` | `run_failed` | `failed` | 无法继续 |
| `active` | `run_aborted` | `aborted` | 被中止 |
| `waiting` | `run_aborted` | `aborted` | 等待中止 |
| `recovering` | `run_failed` | `failed` | 恢复失败 |

### 5.2 StageState 转移

| 当前状态 | 事件 | 下一状态 |
|------|------|------|
| `pending` | `stage_activated` | `active` |
| `active` | `stage_blocked` | `blocked` |
| `blocked` | `stage_unblocked` | `active` |
| `active` | `stage_completed` | `completed` |
| `active` | `stage_failed` | `failed` |

### 5.3 BranchState 转移

| 当前状态 | 事件 | 下一状态 |
|------|------|------|
| `proposed` | `branch_accepted` | `active` |
| `proposed` | `branch_pruned` | `pruned` |
| `active` | `branch_wait_requested` | `waiting` |
| `waiting` | `branch_resumed` | `active` |
| `active` | `branch_pruned` | `pruned` |
| `active` | `branch_succeeded` | `succeeded` |
| `active` | `branch_failed` | `failed` |

### 5.4 ActionState 转移

| 当前状态 | 事件 | 下一状态 | 说明 |
|------|------|------|------|
| `prepared` | `action_dispatched` | `dispatched` | 已发送 |
| `dispatched` | `action_acknowledged` | `acknowledged` | 外部系统确认受理 |
| `acknowledged` | `action_succeeded` | `succeeded` | 结果可确认 |
| `dispatched` | `action_failed` | `failed` | 直接失败 |
| `acknowledged` | `action_failed` | `failed` | 受理后失败 |
| `dispatched` | `effect_uncertain` | `effect_unknown` | 无法判定副作用 |
| `acknowledged` | `effect_uncertain` | `effect_unknown` | 无法判定副作用 |

## 6. 关键事件仲裁原则

### 6.1 callback vs timeout

场景：

- 外部 callback 到达
- 同一动作的 timeout 也被 watchdog 触发

仲裁原则：

1. 如果 callback 已被幂等消费并带有有效 `action_id/callback_id`，优先认定 callback
2. timeout 事件转为诊断事件，不覆盖已确认 callback 的结果
3. 如果 timeout 先发生且动作进入 `effect_unknown`，但后续 callback 到达，则由恢复面仲裁：
   - 若 callback 证据可确认结果，转为 `succeeded` 或 `failed`
   - 若 callback 不足以确认，保持 `effect_unknown`

### 6.2 human review vs auto-resume

场景：

- 系统计划定时恢复
- 同时进入人工审核

仲裁原则：

- `human_review` 优先于 `scheduled_resume`
- 在 `ReviewState != approved` 前，不得自动推进高风险动作

### 6.3 task contract revised while branches exist

场景：

- `Human Gate A` 修正了 task contract
- 已有多个 branch 正在运行或等待

仲裁原则：

1. 新 contract 生成新版本
2. 所有现有 branch 必须重新做兼容性检查
3. 兼容分支：
   - 可保留并重新标注 contract version
4. 不兼容分支：
   - 标记为 `pruned_by_contract_change`
5. 已完成阶段不自动失效，但后续评估时必须带上旧 contract version 以供审计

### 6.4 policy version changed while run is waiting

场景：

- run 在 `waiting`
- evolve 发布了新 routing / skill / evaluation policy

仲裁原则：

- 运行恢复时默认继续使用该 run 冻结时绑定的 policy version
- 不允许未显式授权的中途切换
- 若要切换，必须产生新的 change record，并在 replay 元数据中可见

### 6.5 acknowledged but no final result

场景：

- 外部系统已受理
- 长时间没有结果

仲裁原则：

1. 保持 `ActionState = acknowledged`
2. `WaitState = external_callback`
3. 到达 watchdog 阈值后进入恢复评估，而不是直接重发
4. 是否允许重发取决于 `side_effect_class`

## 7. Side Effect 治理规则

### 7.1 Side Effect Class

- `read_only`
- `local_write`
- `external_write`
- `irreversible_submit`

判定原则：

- 以 `blast radius` 和业务影响范围为准
- 不以目标是本地文件、共享盘还是远程 API 来简单判定

### 7.2 Retry 规则

| side_effect_class | 默认重试策略 |
|------|------|
| `read_only` | 可自动重试 |
| `local_write` | 可重试，但需幂等键或覆盖规则 |
| `external_write` | 谨慎重试，优先确认是否已生效 |
| `irreversible_submit` | 默认不自动重试，通常需审批或人工确认 |

### 7.3 Recovery 规则

| side_effect_class | 默认恢复方向 |
|------|------|
| `read_only` | 重试或更换路径 |
| `local_write` | 回滚或覆盖 |
| `external_write` | 查询外部状态后再仲裁 |
| `irreversible_submit` | 记录审计并进入人工处理 |

## 8. Failure Taxonomy 与触发用途

当前冻结失败类型：

- `missing_evidence`
- `invalid_context`
- `harness_denied`
- `model_output_invalid`
- `model_refusal`
- `callback_timeout`
- `no_progress`
- `contradictory_evidence`
- `unsafe_action_blocked`
- `budget_exhausted`

### 8.1 用途映射

| failure_code | 主要用途 |
|------|------|
| `missing_evidence` | Task View 重建后检视、route 降级 |
| `invalid_context` | 上下文装配缺陷、模型调用前阻断 |
| `harness_denied` | 权限或安全策略阻断 |
| `model_output_invalid` | 模型输出不可执行，触发重试或降级 |
| `model_refusal` | 模型拒绝执行，触发替代模型或人工介入 |
| `callback_timeout` | 外部任务长期未完成，进入恢复面 |
| `no_progress` | watchdog 触发 |
| `contradictory_evidence` | 触发 Human Gate C |
| `unsafe_action_blocked` | 安全动作阻断，可能进入人工审批 |
| `budget_exhausted` | 触发 Gate B 或 CTS 终止 |

## 9. Human Gate 后的清算规则

这一部分是为了避免人类介入污染后续 evolve 数据。

### 9.1 Gate A: task contract correction

- 生成新的 contract version
- 原分支必须重新做 compatibility check
- 后续评估必须区分更改前后版本

### 9.2 Gate B: route direction choice

- 记录人工选择的 branch priority
- 不将人工直接选择等价为模型 route 成功证据
- 后续 evolve 只能把它作为辅助信号，不能直接当作自动路由收益

### 9.3 Gate C: intermediate artifact edit

- 人工编辑后的产物要带 `human_modified=true`
- 此类产物不应直接作为纯模型 skill 认证证据
- 可进入 knowledge summary，但需标注人为介入

### 9.4 Gate D: final package approval

- 只影响最终发布或提交动作
- 不反向证明所有中间 route 都是最优

## 10. 需要后续落地的硬表

本文件已经足够支持实现规划前的接口讨论，但真正开工前仍应再补四张表：

1. `Run / Stage / Branch / Action` 完整状态转移矩阵
2. callback、timeout、retry、resume 的事件仲裁表
3. evolve 发布域 / 回滚域 / 依赖矩阵
4. skill 强制契约 schema

## 11. 当前结论

到本文件为止，TRACE 已经具备：

- 运行时真相
- 基本仲裁原则
- 幂等和副作用治理基线
- 人机交互后的清算规则

这足够支持下一步做：

- `agent-kernel` 契约差距分析
- `agent-core` 能力映射
- 最终实施计划

本轮仍然先不展开实施计划。

