# TRACE 契约映射说明

> 依据版本：`2026-04-05-trace-architecture-review-v1.2.1.md`
> 目标：冻结 `hi-agent -> agent-kernel -> agent-core` 的职责边界与核心交互契约
> 说明：本文件不是实施计划，而是接口与责任映射基线

## 1. 目的

TRACE 已经完成架构冻结前的主要收敛。接下来最重要的不是继续抽象，而是把抽象映射成清晰的契约边界。

本文件回答 4 个问题：

- 哪些概念归 `hi-agent`
- 哪些能力必须由 `agent-kernel` 提供
- 哪些资源和环境能力由 `agent-core` 供给
- 三者之间交换哪些数据与控制信号

## 2. 总体分工

一句话版本：

- `hi-agent` 决定“为什么做、做什么、怎么判断”
- `agent-kernel` 决定“如何长期活着、如何稳定执行、如何可恢复”
- `agent-core` 决定“能接触什么系统、能调用什么环境能力”

## 3. 一等概念归属

| 概念 | 主归属 | 原因 | 次级依赖 |
|------|--------|------|----------|
| `Task Contract` | `hi-agent` | 任务语义、目标、约束、验收标准属于上层智能体定义 | `agent-kernel` 持久化引用 |
| `CTS / Stage Graph` | `hi-agent` | 轨迹空间与阶段结构是上层任务建模 | `agent-kernel` 执行与记录 |
| `Route Policy` | `hi-agent` | 多轨迹探索与剪枝标准属于上层策略 | `agent-kernel` 承载执行 |
| `Task View Selection` | `hi-agent` | 选什么内容给模型看是认知策略，不是运行时策略 | `agent-kernel` 封装与回放 |
| `Run Lifecycle` | `agent-kernel` | 长程运行、暂停、恢复、等待、心跳必须是内核真相 | `hi-agent` 消费状态 |
| `Trajectory Ledger` | `agent-kernel` | 结构化事件真相与可回放记录必须稳定落内核 | `hi-agent` 解释语义 |
| `LLM Gateway` | `agent-kernel` | provider 解耦与推理传输契约必须统一 | `hi-agent` 声明能力角色 |
| `Harness Invocation` | `agent-kernel` | 所有执行都应经内核治理 | `agent-core` 提供能力 |
| `Context Resources` | `agent-core` | 文档、检索、session、workspace 资源是供给侧 | `hi-agent` 选择，`agent-kernel` 记录 |
| `Tool / Workflow / SysOperation` | `agent-core` | 外部环境能力属于应用层资产 | `agent-kernel` 承载调用 |
| `Memory Semantics` | `hi-agent` | 哪些经历属于工作记忆、情节记忆是上层定义 | `agent-kernel` 存储引用 |
| `Knowledge Semantics` | `hi-agent` | 语义知识与过程知识的抽象与更新策略在上层 | `agent-core` 可提供知识源 |
| `Skill Lifecycle` | `hi-agent` | 候选、试用、认证、弃用规则属于上层进化逻辑 | `agent-kernel` 提供版本钉住与回放 |
| `Evaluation Logic` | `hi-agent` | 质量、效率、回归、可进化判定在上层 | `agent-kernel` 暴露可计算数据 |

## 4. 仓间交互原则

### 4.1 `hi-agent -> agent-kernel`

`hi-agent` 向 `agent-kernel` 发送的是：

- 任务契约
- 当前运行上下文引用
- 当前阶段与分支语义
- Task View 选择结果
- 所需模型能力角色
- 路由、评估、进化决策

`agent-kernel` 不负责创造这些语义，只负责：

- 将其稳定持久化
- 封装成可执行记录
- 保证后续可重放、可恢复、可追溯

### 4.2 `agent-kernel -> agent-core`

`agent-kernel` 向 `agent-core` 请求的是：

- 环境能力执行
- 资源读取
- 工具/工作流调用
- 外部任务提交与状态回传

`agent-core` 不负责：

- 路由决策
- Task View 组装
- 任务质量判断
- 进化决策

### 4.3 `agent-kernel -> hi-agent`

`agent-kernel` 反向暴露的是：

- 运行状态
- 分支状态
- 证据引用
- 执行结果
- 失败分类
- 比较指标
- 版本与回放元数据

`hi-agent` 基于这些数据做：

- route compare
- prune
- evolve trigger
- skill candidate 提取
- evaluation baseline 更新

## 5. 建议的核心契约对象

这里不直接给代码，而给出结构化语义对象，后续可映射为 DTO / dataclass / protocol。

### 5.1 Task Contract

建议字段：

- `task_id`
- `task_family`
- `goal`
- `constraints`
- `acceptance_criteria`
- `budget`
- `deadline`
- `risk_level`
- `environment_scope`
- `input_refs`

归属：

- 语义定义归 `hi-agent`
- 存储与回放归 `agent-kernel`

### 5.2 Run Start Envelope

建议字段：

- `run_id`
- `task_id`
- `task_contract_ref`
- `initial_stage_id`
- `route_policy_version`
- `skill_policy_version`
- `evaluation_policy_version`
- `task_view_policy_version`

归属：

- 创建由 `hi-agent` 触发
- 落盘与生命周期管理归 `agent-kernel`

### 5.3 Task View Envelope

建议字段：

- `run_id`
- `stage_id`
- `branch_id`
- `task_contract_slice`
- `must_keep_evidence_refs`
- `memory_refs`
- `knowledge_refs`
- `budget_slice`
- `selected_model_role`

归属：

- 内容选择归 `hi-agent`
- 封装、持久化、provider 传输映射归 `agent-kernel`

### 5.4 Harness Action Envelope

建议字段：

- `run_id`
- `stage_id`
- `branch_id`
- `action_id`
- `attempt_id`
- `action_kind`
- `side_effect_class`
- `approval_required`
- `idempotency_key`
- `input_payload_ref`
- `timeout_policy`
- `retry_policy`

归属：

- 行动语义归 `hi-agent`
- 执行治理归 `agent-kernel`
- 实际能力实现归 `agent-core`

### 5.5 Trajectory Event

建议字段：

- `event_id`
- `run_id`
- `stage_id`
- `branch_id`
- `event_type`
- `event_time`
- `input_ref`
- `output_ref`
- `evidence_ref`
- `failure_code`
- `policy_versions`

归属：

- 存储归 `agent-kernel`
- 语义解释归 `hi-agent`

### 5.6 Evolve Change Set

建议字段：

- `change_set_id`
- `change_scope`
- `task_family`
- `candidate_refs`
- `baseline_ref`
- `evaluation_result_ref`
- `rollout_scope`
- `rollback_policy`

归属：

- 生成与解释归 `hi-agent`
- 版本钉住、旧 run 回放兼容由 `agent-kernel` 支持

## 6. Task View 责任边界

这一条必须钉死，否则三个仓会反复打架。

### 6.1 `hi-agent` 负责

- 定义 Task View 的语义装配策略
- 决定哪些证据必须进入当前窗口
- 决定使用什么 memory / knowledge 切片
- 决定何时触发降级

### 6.2 `agent-kernel` 负责

- 记录本次实际展示给模型的内容引用
- 保证同一决策可回放
- 将 Task View 封装为 provider 调用格式
- 保证旧 run 在旧 policy 版本下仍可重演

### 6.3 `agent-core` 负责

- 提供可被引用的资源
- 提供检索、工具、系统操作、工作流等能力
- 不参与认知级裁剪与拼装

## 7. Harness 责任边界

### 7.1 `hi-agent`

- 决定要执行什么动作
- 决定动作语义与目标
- 决定动作是否值得执行

### 7.2 `agent-kernel`

- 为动作分配身份
- 附加幂等键
- 应用超时/重试/审批/恢复规则
- 接收回调并做仲裁
- 写入 trajectory ledger

### 7.3 `agent-core`

- 提供具体执行能力
- 屏蔽底层系统差异
- 返回结构化结果和证据引用

## 8. LLM Gateway 契约边界

### 8.1 `hi-agent`

- 使用粗粒度能力角色调用模型
- 例如：`heavy_reasoning` / `light_processing` / `evaluation`
- 具体的 route compare、写作、审稿等细粒度语义留在上层策略中

### 8.2 `agent-kernel`

- 将能力角色路由到具体 provider / model
- 记录调用上下文引用和版本信息
- 保证 provider 可替换、决策可回放

### 8.3 `agent-core`

- 不应拥有模型路由与模型契约抽象
- 如有模型资源，只能作为资源供给而非认知中枢

## 9. 对 `agent-kernel` 的明确接口诉求

为了支持 TRACE，`agent-kernel` 至少需要提供以下协议能力：

### 9.1 Run Protocol

- `start_run`
- `resume_run`
- `pause_run`
- `abort_run`
- `query_run`

### 9.2 Branch Protocol

- `open_branch`
- `mark_branch_waiting`
- `mark_branch_pruned`
- `mark_branch_succeeded`
- `mark_branch_failed`

### 9.3 Task View Replay Protocol

- `record_task_view`
- `get_task_view_record`
- `replay_task_view_by_decision`

### 9.4 Harness Execution Protocol

- `dispatch_action`
- `acknowledge_action`
- `complete_action`
- `consume_callback`
- `resolve_effect_unknown`

### 9.5 Evolution Support Protocol

- `pin_policy_versions_for_run`
- `record_change_scope`
- `query_metrics_for_evaluation`
- `replay_old_run_under_old_versions`

## 10. 对 `agent-core` 的明确接口诉求

### 10.1 Capability Supply

- tool
- workflow
- sys operation
- context retrieval
- asset access
- experiment execution

### 10.2 Result Contract

`agent-core` 返回的每类结果最好统一至少包含：

- `status`
- `output_ref`
- `evidence_ref`
- `side_effect_class`
- `callback_ref`（如有）
- `error_code`（如有）

## 11. 首批冻结项

这些词汇和边界建议在实施前冻结：

- `Task`
- `Run`
- `Stage`
- `Branch`
- `Action`
- `Task View`
- `CTS`
- `Harness`
- `Evolve`
- `Skill Candidate / Provisional / Certified / Deprecated / Retired`
- `change_scope`
- `side_effect_class`
- `failure taxonomy`

## 12. 本文件之后的工作

本文件完成后，下一步自然衔接为：

1. 运行时状态转移与事件仲裁表
2. `agent-kernel` 契约差距清单
3. `agent-core` 能力映射清单
4. 实施计划

本轮先不展开实施计划。

