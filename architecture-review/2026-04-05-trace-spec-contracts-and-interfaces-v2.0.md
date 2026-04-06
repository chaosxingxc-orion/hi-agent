# TRACE V2.0 规约、契约与接口规范

> 状态：`V2.0 重写版`
>
> 目的：
> - 固定 TRACE V2.0 的正式规约
> - 明确 `hi-agent`、`agent-kernel`、`agent-core` 的同步契约与接口
> - 明确当前实现与目标规范之间的偏差

---

## 1. 规范范围

本规范定义：

- 核心术语
- 身份规约
- 契约对象
- 接口定义
- 状态与仲裁规则
- 失败码
- 版本与兼容规则
- 当前实现偏差

本规范不定义：

- 具体代码实现
- 存储表结构
- UI 交互协议
- 多智能体协同协议

---

## 2. 规范性关键词

- `必须`：不满足即视为不符合 TRACE V2.0
- `应该`：强烈建议满足
- `可以`：允许实现选择
- `不得`：显式禁止

---

## 3. 系统关系规约

V2.0 中，系统关系必须按以下方式理解：

- `hi-agent` 是唯一智能体主体
- `agent-core` 不是平级系统层，而是 `hi-agent` 集成的能力模块来源
- `agent-kernel` 是 `hi-agent` 依赖的运行时底座

因此，跨仓契约必须服从以下边界：

### 3.1 `hi-agent`

负责：

- 任务语义
- TRACE 认知抽象
- CTS / Stage Graph
- Route Policy
- Task View Selection
- Memory / Knowledge / Skill / Evolve
- Harness 语义编排

### 3.2 `agent-kernel`

负责：

- Run Lifecycle
- durable runtime
- callback / wait / resume / recovery
- event log / projection / replay metadata
- LLM Gateway
- Harness 执行治理
- idempotency / arbitration

### 3.3 `agent-core`

负责：

- session
- context resources
- tool / workflow / sys_operation
- retrieval
- service_api / mcp
- assets access

且：

- `agent-core` 不负责 route
- `agent-core` 不负责 task view selection
- `agent-core` 不负责 evolve
- `agent-core` 不负责 runtime truth

---

## 4. 核心术语规约

### 4.1 Task

任务契约，而不是用户输入文本。

### 4.2 Run

任务的 durable 长程运行主体。

### 4.3 Stage

任务推进的正式阶段对象。

### 4.4 Branch

轨迹树中的逻辑分支。

`Branch` 不得被定义为 child run 的别名。

### 4.5 Task View

某次模型调用前重建的最小充分上下文。

### 4.6 Harness

`hi-agent` 内部的统一执行编排面。

其中：

- 编排语义归 `hi-agent`
- 执行治理归 `agent-kernel`
- 能力供给来自 `agent-core`

### 4.7 Policy Versions

Run 创建时被冻结的版本集合。

### 4.8 Change Record

对运行中关键条件变更的显式审计记录。

---

## 5. 身份规约

### 5.1 最小身份集合

以下身份必须稳定存在：

- `task_id`
- `run_id`
- `stage_id`
- `branch_id`
- `action_id`
- `attempt_id`
- `task_view_id`
- `callback_id`
- `gate_ref`
- `change_set_id`

### 5.2 唯一性要求

- `run_id` 必须全局唯一
- `stage_id` 必须在同一 run 内唯一
- `branch_id` 必须在同一 run 内唯一
- `action_id` 必须在同一 run 内唯一
- `attempt_id` 必须在同一 action 内唯一
- `task_view_id` 必须全局唯一

### 5.3 生成责任

`hi-agent` 负责生成：

- `task_id`
- `stage_id`
- `branch_id`
- `action_id`
- `task_view_id`

`agent-kernel` 负责生成：

- commit / event / replay 相关内部身份

---

## 6. 契约对象规范

## 6.1 Task Contract

### 必填字段

- `task_id`
- `task_family`
- `goal`
- `constraints`
- `acceptance_criteria`
- `budget`
- `risk_level`

### 选填字段

- `deadline`
- `environment_scope`
- `input_refs`
- `priority`

### 所有权

- 语义归 `hi-agent`
- durable reference 归 `agent-kernel`

## 6.2 Run Start Envelope

### 必填字段

- `run_id`
- `task_contract_ref`
- `route_policy_version`
- `skill_policy_version`
- `evaluation_policy_version`
- `task_view_policy_version`

### 选填字段

- `initial_stage_id`
- `session_id`
- `parent_run_id`
- `context_ref`
- `input_ref`
- `input_json`

### 规范要求

- `agent-kernel` 在 `start_run` 时必须冻结上述版本
- 冻结版本必须可审计、可回放、可查询

## 6.3 Task View Record

### 必填字段

- `task_view_id`
- `run_id`
- `selected_model_role`
- `assembled_at`

### 选填字段

- `decision_ref`
- `stage_id`
- `branch_id`
- `task_contract_ref`
- `evidence_refs`
- `memory_refs`
- `knowledge_refs`
- `policy_versions`

### 规范要求

- `record_task_view()` 必须发生在模型调用前
- `decision_ref` 可以为空
- 调用后应通过 `bind_task_view_to_decision()` 完成 late-bind
- kernel 必须只存引用，不存大块内容本体

## 6.4 Harness Action Envelope

### 必填字段

- `run_id`
- `stage_id`
- `branch_id`
- `action_id`
- `attempt_id`
- `action_kind`
- `effect_class`
- `side_effect_class`
- `idempotency_key`

### 选填字段

- `approval_required`
- `input_payload_ref`
- `timeout_policy`
- `retry_policy`
- `callback_ref`

### 规范要求

- 每个外部动作必须具备稳定 `idempotency_key`
- callback 型动作应带稳定关联标识
- 高风险动作应支持审批标记

## 6.5 Trace Runtime View

### 必填字段

- `run_id`
- `run_state`
- `wait_state`
- `review_state`
- `branches`
- `stages`
- `projected_at`

### 选填字段

- `active_stage_id`
- `policy_versions`

### 规范要求

- 应由 durable state 重建
- 不应长期依赖进程内存注册表
- `review_state / active_stage_id / policy_versions` 不应长期写死为空

## 6.6 Evolve Change Set

### 必填字段

- `change_set_id`
- `change_scope`
- `task_family`
- `candidate_refs`
- `baseline_ref`

### 选填字段

- `evaluation_result_ref`
- `rollout_scope`
- `rollback_policy`

### 规范要求

- 每次 evolve 必须声明 `change_scope`
- 同一次 change set 不应混改互相评估的核心面

---

## 7. 接口规范

## 7.1 `hi-agent -> agent-kernel`

### `start_run(StartRunRequest) -> StartRunResponse`

#### 语义

- 创建一个 durable run
- 冻结策略版本
- 写入任务与初始阶段元数据

#### 最小输入

- `run_id`
- `task_contract_ref`
- 四个 policy versions

#### 最小输出

- `run_id`
- workflow identity
- 初始生命周期状态

### `signal_run(SignalRunRequest) -> None`

#### 语义

- 向已有 run 注入外部信号

#### 允许信号族

- callback
- resume
- cancel
- approval
- change record
- child completed

### `query_run(QueryRunRequest) -> QueryRunResponse`

#### 语义

- 返回 projection-safe 运行摘要

#### 最小返回字段

- `run_id`
- `lifecycle_state`
- `projected_offset`
- `waiting_external`
- `current_action_id`
- `recovery_mode`
- `recovery_reason`
- `active_child_runs`
- `policy_versions`
- `active_stage_id`

### `query_trace_runtime(run_id) -> TraceRuntimeView`

#### 语义

- 返回 TRACE 面向上层认知与治理的真相视图

#### 最小返回字段

- `run_state`
- `wait_state`
- `review_state`
- `active_stage_id`
- `branches`
- `stages`
- `policy_versions`
- `projected_at`

### `record_task_view(TaskViewRecord) -> task_view_id`

#### 语义

- 记录模型调用前的 Task View 引用

### `bind_task_view_to_decision(task_view_id, decision_ref) -> None`

#### 语义

- 执行 `pre-record + late-bind`

### `open_stage(...) -> None`
### `mark_stage_state(...) -> None`
### `open_branch(...) -> None`
### `mark_branch_state(...) -> None`
### `open_human_gate(...) -> None`

#### 语义

- 把 TRACE 语义对象推进到 kernel durable truth

## 7.2 `agent-kernel -> agent-core`

### 语义约束

kernel 只能请求能力，不得把认知职责下沉到 `agent-core`。

### 最小能力族

- `context resources`
- `tool`
- `workflow`
- `sys_operation`
- `retrieval`
- `service_api`
- `mcp`

### 最小返回建议

- `status`
- `output_ref`
- `evidence_ref`
- `callback_ref`
- `error_code`

## 7.3 `agent-kernel -> hi-agent`

kernel 应对上暴露：

- run truth
- stage truth
- branch truth
- action truth
- evidence refs
- failure code
- policy versions
- replay metadata

---

## 8. 状态规范

### 8.1 RunState

- `created`
- `active`
- `waiting`
- `recovering`
- `completed`
- `failed`
- `aborted`

### 8.2 StageState

- `pending`
- `active`
- `blocked`
- `completed`
- `failed`

### 8.3 BranchState

- `proposed`
- `active`
- `waiting`
- `pruned`
- `succeeded`
- `failed`

### 8.4 ActionState

- `prepared`
- `dispatched`
- `acknowledged`
- `succeeded`
- `effect_unknown`
- `failed`

### 8.5 WaitState

- `none`
- `external_callback`
- `human_review`
- `scheduled_resume`

### 8.6 ReviewState

- `not_required`
- `requested`
- `in_review`
- `approved`
- `rejected`

---

## 9. 仲裁规范

### 9.1 callback vs timeout

1. callback 携带有效 `action_id/callback_id` 时优先。
2. timeout 不得覆盖已确认 callback 结果。
3. timeout 先触发后进入 `effect_unknown` 时，后续 callback 必须通过 recovery 面仲裁。

### 9.2 human review vs scheduled resume

- `human_review` 高于 `scheduled_resume`
- `ReviewState != approved` 前，不得自动推进高风险动作

### 9.3 policy version changed while waiting

- waiting run 恢复时默认继续使用冻结版本
- 无显式授权不得中途切换
- 切换必须留下 `change_record`

### 9.4 acknowledged but no final result

- `ActionState` 保持 `acknowledged`
- `WaitState` 进入 `external_callback`
- 到 watchdog 阈值后进入恢复评估，而不是直接重发

---

## 10. Failure Taxonomy

当前冻结失败码：

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

### 用途约束

- `missing_evidence`：task view 检视 / route 降级
- `invalid_context`：模型调用前阻断
- `harness_denied`：权限或安全阻断
- `model_output_invalid`：模型输出重试或降级
- `model_refusal`：替代模型或人工介入
- `callback_timeout`：callback 型恢复
- `no_progress`：watchdog
- `contradictory_evidence`：Gate C
- `unsafe_action_blocked`：审批流
- `budget_exhausted`：预算耗尽治理

---

## 11. Human Gate 规范

V2.0 保留 4 类 Gate：

- `contract_correction`
- `route_direction`
- `artifact_review`
- `final_approval`

### 11.1 必要约束

- Gate 打开必须 durable 记录
- Gate 结果必须显式写入运行时真相
- 不得隐式视为批准

### 11.2 数据清算

- Gate A 改 contract 后，branch 必须重新做兼容检查
- Gate B 的人工选择不得直接作为模型路由成功证据
- Gate C 的人工编辑产物必须标记 `human_modified`
- Gate D 只影响最终高风险动作

---

## 12. Task View 规范

### 12.1 责任边界

- `hi-agent`：语义选择、证据优先级、降级策略
- `agent-kernel`：引用记录、provider 封装、回放元数据
- `agent-core`：资源供给

### 12.2 生命周期

1. `hi-agent` 选择 Task View 引用
2. `agent-kernel` 执行 `record_task_view`
3. 模型调用发生
4. 产生 `decision_ref`
5. `agent-kernel` 执行 `bind_task_view_to_decision`

### 12.3 完整性规则

- 若 must-keep evidence 无法放入窗口，不得静默裁剪后继续运行
- 必须触发降级、切换模型或人工介入

---

## 13. 版本冻结与兼容规范

### 13.1 版本冻结

- run 创建时必须冻结四个 policy version
- waiting run 恢复时默认沿用冻结版本

### 13.2 版本变更

- 中途升级必须通过显式 `change_record`
- existing run 不得隐式跟随新版本

### 13.3 兼容原则

- 新 run 可以直接使用新版本
- 旧 run 是否升级取决于授权流

---

## 14. Manifest 能力协商规范

`KernelManifest` 应至少包含：

- `trace_protocol_version`
- `supported_trace_features`

### 14.1 最小建议特性集

- `policy_version_pinning`
- `task_view_record`
- `task_view_late_bind`
- `branch_protocol`
- `stage_protocol`
- `human_gate_protocol`
- `trace_runtime_view`
- `callback_arbitration`
- `action_state_surface`

### 14.2 协商原则

- `hi-agent` 不得假设 kernel 支持全部 TRACE 能力
- 启动时应读取 manifest 决定启用能力与降级策略

---

## 15. 当前实现偏差

### 15.1 已基本对齐

- TRACE 启动元数据已进入 run 启动链路
- workflow 已接住 policy versions / initial stage / task contract ref
- `run.policy_versions_pinned` 已落账
- `TaskViewRecord` 与 late-bind 已可用
- stage / branch / human gate 入口已存在

### 15.2 尚未完全闭合

- `query_run()` 尚未稳定回传 `policy_versions / active_stage_id`
- `query_trace_runtime()` 尚未稳定回传：
  - `review_state`
  - `active_stage_id`
  - `policy_versions`
- `TraceRuntimeView` 仍偏 facade 聚合视图
- `supported_trace_features` 尚未正式宣告

### 15.3 对集成方的现实要求

在这些偏差补齐前：

- `hi-agent` 可以启动 V1 集成
- 但仍应保留部分上层语义聚合

---

## 16. 一句话总结

`TRACE V2.0 规范要求 hi-agent 作为唯一智能体主体，集成 agent-core 的能力模块，并通过适配层使用 agent-kernel 作为 durable runtime 底座；当前实现已经支持 V1 集成，但其公共读模型和能力协商面仍需继续闭合。`
