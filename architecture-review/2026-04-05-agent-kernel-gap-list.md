# TRACE 对 `agent-kernel` 的差距清单

> 依据：
> - `2026-04-05-trace-architecture-review-v1.2.1.md`
> - `2026-04-05-trace-contract-mapping.md`
> - `2026-04-05-trace-runtime-arbitration.md`
> - 当前仓库实现扫描：`agent_kernel/*`

## 1. 结论先行

`agent-kernel` 当前并不是从零开始。

它已经具备 TRACE 最重要的一批底座能力：

- `KernelFacade` 单入口
- `KernelRuntime` 单系统生命周期
- Temporal / Local 双 substrate
- event log / projection / recovery / dedupe
- callback / waiting_external / heartbeat watchdog
- LLMGateway 协议入口
- effect_unknown / idempotency envelope / external idempotency checks

所以，这份差距清单不是“要不要做 durable runtime”，而是：

`如何把现有 kernel 从可靠执行内核，收敛成 TRACE 所需的企业级长程任务内核。`

## 2. 当前已具备的 TRACE 对应能力

### 2.1 Lifecycle and Durable Runtime

当前可见能力：

- `KernelRuntime` 已统一装配运行时与 substrate
- `KernelFacade` 已暴露 `start_run / signal_run / stream_run_events / query_run` 等入口
- `run_actor_workflow.py` 已存在 signal、callback、recovery、child-run 等路径
- `runtime/heartbeat.py` 已有 watchdog 与 waiting state 监测

判断：

- TRACE 的 durable run 底座已经存在
- 不需要从头设计 runtime 容器

### 2.2 Idempotency and Recovery

当前可见能力：

- `kernel/turn_engine.py` 已有 idempotency envelope 解析与 external idempotency policy 检查
- `sqlite_colocated_bundle.py` 已实现 dispatch key reserve / mark_dispatched / mark_acknowledged / mark_unknown_effect
- `recovery/compensation_registry.py` 已有 compensation 路径
- `run_actor_workflow.py` 已使用 `effect_unknown`

判断：

- TRACE 的“幂等与恢复”不是空白
- 但现有语义仍偏 action-level，尚未完全提升到 TRACE 的 branch/stage/run 协议层

### 2.3 LLM Gateway and Cognitive Hooks

当前可见能力：

- `contracts.py` 和 `runtime/bundle.py` 已有 `LLMGateway` 协议接线
- `substrate/temporal/activity_gateway.py` 已有 inference activity
- `kernel/cognitive/*` 已有 context_port、output_parser、script_runtime 等协议积木

判断：

- `agent-kernel` 已经可以承载 TRACE 的 `LLM Gateway`
- 但 public contract 仍需按 TRACE 的粗粒度角色整理

### 2.4 Events, Projection, Observability

当前可见能力：

- `RuntimeEvent / ActionCommit / RunProjection` 等核心 DTO 已存在
- SQLite event log / projection / recovery outcome store 已存在
- `event_export.py / otel_export.py / observability_hooks.py` 已存在

判断：

- TRACE 的 ledger substrate 已有基础
- 重点不在“有没有事件日志”，而在“事件语义是否够 TRACE 使用”

## 3. 与 TRACE 对齐后仍然存在的关键差距

## 3.1 Gap A: `RunProjection` 与 TRACE Runtime Truth 不完全对齐

现状：

- `RunProjection` 目前更偏 lifecycle + dispatch readiness 视图
- TRACE 需要显式的：
  - `RunState`
  - `StageState`
  - `BranchState`
  - `ActionState`
  - `WaitState`
  - `ReviewState`

问题：

- 当前 kernel 里虽然有 waiting_external、recovering、effect_unknown 等事实，但没有统一的 TRACE 级真相模型
- `BranchState` / `ReviewState` 在 facade/public projection 中还不明确

建议：

- 新增 TRACE-compatible runtime truth DTO，至少不要让上层靠事件拼状态

优先级：

- `P0`

## 3.2 Gap B: `ActionState` 仍需显式建模而不是隐含在事件里

现状：

- kernel 已有 dispatch / ack / effect_unknown 相关逻辑
- 但 TRACE 要求 action 至少能明确区分：
  - `prepared`
  - `dispatched`
  - `acknowledged`
  - `succeeded`
  - `effect_unknown`
  - `failed`

问题：

- 当前状态更多散落在 workflow、event、dedupe store 中
- 上层要进行 runtime arbitration 时，缺乏一个统一 action truth surface

建议：

- 为 action 增加统一状态读模型，而不是只依赖 commit event 还原

优先级：

- `P0`

## 3.3 Gap C: `Task View` 还不是 kernel 的一等记录对象

现状：

- kernel 已有 `context_port`、context adapter、capability snapshot 等
- 但 TRACE 要求 kernel 明确记录：
  - 某次模型决策看到的 Task View 内容引用
  - 所属 run/stage/branch
  - 使用的 policy version

问题：

- 目前更像“有上下文接线能力”，但不是“有可回放的 Task View record”

建议：

- 增加 `TaskViewRecord` 或等价 DTO
- 支持 `record_task_view / get_task_view_record / replay_task_view_by_decision`

优先级：

- `P0`

## 3.4 Gap D: TRACE 的 `change_scope` 与 policy version pinning 还未成公共契约

现状：

- facade 和 contracts 已有 manifest、plan type、approval 等一些治理能力
- 但 TRACE 需要：
  - evolve `change_scope`
  - run-level policy version pinning
  - old-run replay under old versions

问题：

- 当前代码中还没有看到清晰的 evolve rollout metadata contract

建议：

- 将以下内容显式入 contract：
  - `route_policy_version`
  - `skill_policy_version`
  - `evaluation_policy_version`
  - `task_view_policy_version`
  - `change_scope`

优先级：

- `P0`

## 3.5 Gap E: callback / timeout / resume 的事件仲裁规则还没进入公共接口

现状：

- runtime 已有 heartbeat watchdog
- workflow 已处理 signal、waiting_external、effect_unknown

问题：

- 这些规则仍偏实现内逻辑，而不是对上层清晰暴露的仲裁协议
- TRACE 需要内核提供“可预期”的 race resolution

建议：

- 至少在 kernel 侧定义并稳定以下仲裁面：
  - callback beats timeout when callback already validated
  - timeout after effect_unknown enters recovery path
  - waiting run resumes under pinned policy versions

优先级：

- `P0`

## 3.6 Gap F: failure taxonomy 尚未与 TRACE 对齐

现状：

- kernel 已有 `FailureEnvelope`、`effect_unknown`、reflection/recovery 相关失败信号

TRACE 需要至少冻结：

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

问题：

- 当前 kernel failure code 更偏局部实现语义
- 上层 evolve、human gate、route pruning 需要稳定 failure taxonomy

建议：

- 增加一个 TRACE-facing failure code normalization layer

优先级：

- `P1`

## 3.7 Gap G: branch-level APIs 不够显式

现状：

- kernel 内部已处理 parallel branch、child run、successful_branches 等概念

问题：

- TRACE 的 CTS 需要更明确的 branch 协议，而不只是 workflow 内部有分支事实

建议：

- 对上层暴露 branch-level primitives：
  - `open_branch`
  - `mark_branch_waiting`
  - `mark_branch_pruned`
  - `mark_branch_succeeded`
  - `mark_branch_failed`

优先级：

- `P1`

## 3.8 Gap H: Human Gate 仍然是间接能力，不是统一治理对象

现状：

- kernel 已有 `approval_request`、`human_actor` interaction target 等能力

问题：

- TRACE 要求 Human Gate A/B/C/D 进入生命周期与审计语义
- 当前更像通用 approval/signal 能力，而不是统一 human gate contract

建议：

- 不一定要新建复杂系统，但至少需要：
  - `gate_type`
  - `trigger_reason`
  - `review_state`
  - `resolution_ref`

优先级：

- `P1`

## 3.9 Gap I: side-effect taxonomy 与现有 effect_class 不完全一致

现状：

- kernel 当前 `EffectClass` 是：
  - `read_only`
  - `idempotent_write`
  - `compensatable_write`
  - `irreversible_write`

TRACE 文档里同时还要求 operational side-effect class：

- `read_only`
- `local_write`
- `external_write`
- `irreversible_submit`

问题：

- 两套分类并不完全同一维度
- 一个偏恢复/幂等语义
- 一个偏 blast radius / operational governance

建议：

- 不要强行二选一
- 推荐保留双维度：
  - `effect_class`：恢复与幂等维度
  - `side_effect_class`：风险与治理维度

优先级：

- `P1`

## 4. 建议的分层改造顺序

### 第一层：直接补 contract

- TRACE runtime truth DTO
- TaskViewRecord
- policy version pinning DTO
- normalized failure taxonomy

### 第二层：补 facade / gateway surface

- branch protocol
- task-view replay protocol
- human gate contract

### 第三层：补内核仲裁规则

- callback vs timeout
- waiting resume under pinned policies
- action acknowledged vs succeeded distinction

## 5. 可以明确复用、避免重复建设的部分

建议直接复用而非重造：

- `KernelRuntime`
- `KernelFacade`
- `TemporalAdaptor / LocalFSMAdaptor`
- `RuntimeEvent / ActionCommit / RunProjection`
- SQLite event log / dedupe store / recovery outcomes
- `LLMGateway` 接线
- heartbeat watchdog
- recovery gate / compensation registry

## 6. 最终判断

`agent-kernel` 当前更像一个“可靠执行与恢复内核”，而 TRACE 想把它提升成“企业级长程任务内核”。

两者之间不是推翻关系，而是：

- 当前内核已经覆盖了 60%-70% 的底座
- 剩余差距主要集中在：
  - public runtime truth
  - task view replay
  - policy/version/change_scope
  - branch/human gate/failure normalization

所以我的判断是：

`agent-kernel` 不需要重做，只需要沿着 TRACE 所要求的 contract surface 做一轮有边界的升级。`

