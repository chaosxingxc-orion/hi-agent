# `agent-kernel` 对 TRACE / hi-agent 使用需求的系统性评估

> 评估对象：`D:\chao_workspace\agent-kernel`
> 
> 评估基线：
> - `2026-04-05-trace-architecture-review-v1.2.1.md`
> - `2026-04-05-trace-contract-mapping.md`
> - `2026-04-05-trace-runtime-arbitration.md`
> - `2026-04-05-response-to-agent-kernel-team.md`
>
> 评估方式：
> - 代码扫描
> - 关键契约对象与 facade 实现核对
> - 针对性测试执行

## 1. 结论先行

当前的 `agent-kernel`：

`已经可以满足 hi-agent 的“架构对接与单智能体 V1 接入”需求，但还不能完全满足 hi-agent 对 TRACE 的“完整运行时真相底座”需求。`

更准确地说：

- 作为 `durable runtime + LLM gateway + harness governance + recovery substrate`，它已经 `够用`
- 作为 TRACE 所要求的 `完整公共真相面`，它目前仍是 `部分到位`

因此我的总体判断是：

`可以开始集成，但不宜把当前 kernel 直接视为 TRACE 的完全闭合内核。`

如果要给一个状态标签，我会给：

- `V1 接入可行`
- `V1 运行时真相部分满足`
- `7x24 企业级闭环仍需补齐关键读模型与元数据贯通`

## 2. 已满足的核心需求

### 2.1 Durable runtime 底座已经具备

这部分是当前 kernel 最扎实的地方。

从代码和现有测试看，它已经具备：

- run 生命周期容器
- event log / projection / recovery
- callback / waiting_external / watchdog
- effect_unknown 进入 recovery path
- dedupe / idempotency store
- facade 单入口

对应代码可见于：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L89)
- [gateway.py](D:/chao_workspace/agent-kernel/agent_kernel/substrate/temporal/gateway.py#L58)
- [run_actor_workflow.py](D:/chao_workspace/agent-kernel/agent_kernel/substrate/temporal/run_actor_workflow.py#L921)
- [heartbeat.py](D:/chao_workspace/agent-kernel/agent_kernel/runtime/heartbeat.py)

这意味着：`hi-agent` 不需要自己再造一套长程任务 runtime。

### 2.2 TRACE 契约对象已经进入 kernel 公共接口

当前 `contracts.py` 里已经出现了我们需要的关键 TRACE 对象：

- `RunPolicyVersions`
- `TraceStageView`
- `TraceBranchView`
- `TraceRuntimeView`
- `TaskViewRecord`
- `OpenBranchRequest`
- `BranchStateUpdateRequest`
- `HumanGateRequest`

对应位置：

- [contracts.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/contracts.py#L2375)

这说明 kernel 不再只是“内部能做”，而是开始形成可对接的公共协议。

### 2.3 Task View 持久化与 late-bind 已经可用

这是这轮最重要的正向信号之一。

现在已经有：

- `record_task_view()`
- `get_task_view_record()`
- `get_task_view_by_decision()`
- `bind_task_view_to_decision()`

而且底层有 SQLite 持久化：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L867)
- [sqlite_task_view_log.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/persistence/sqlite_task_view_log.py#L14)

这意味着 TRACE 对 `pre-record + late-bind` 的要求已经被满足到“可调用”的程度。

### 2.4 Stage / Branch / Human Gate 已经有 facade 入口

当前 facade 已经暴露：

- `open_stage()`
- `mark_stage_state()`
- `open_branch()`
- `mark_branch_state()`
- `open_human_gate()`

对应位置：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L944)
- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L1032)
- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L1113)

这说明 kernel 至少已经接受：

- stage 是正式对象
- branch 是正式对象
- human gate 是正式对象

这对 `hi-agent` 非常关键。

### 2.5 针对性测试已经通过

我执行了两组关键测试：

```powershell
python -m pytest D:\chao_workspace\agent-kernel\python_tests\agent_kernel\adapters\test_kernel_facade_trace.py -q
python -m pytest D:\chao_workspace\agent-kernel\python_tests\agent_kernel\substrate\test_run_actor_workflow.py -q -k "timeout_signal or cancel_signal or recovery_succeeded_signal"
```

结果：

- `22 passed`
- `3 passed`

这至少说明：

- TRACE facade 不是纯文档草图
- callback / timeout / recovery 的部分运行期规则已经有回归保护

## 3. 部分满足，但还没有完全闭合的需求

### 3.1 `TraceRuntimeView` 已存在，但还不是完整 durable truth

虽然 `TraceRuntimeView` 已定义，也有 `stages` 字段：

- [contracts.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/contracts.py#L2421)

但当前 `query_trace_runtime()` 的实现仍然比较薄：

- `review_state` 直接写死为 `not_required`
- `active_stage_id` 固定为 `None`
- `policy_versions` 固定为 `None`
- `branches` / `stages` 来源于 facade 进程内存注册表，而不是事件日志重建

对应位置：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L813)

这意味着：

- 它已经是一个“接口”
- 但还不是 TRACE 需要的“单一持久真相面”

这也是当前 kernel 最大的结构性缺口。

### 3.2 policy version 字段进入了请求对象，但还没贯通到 runtime

`StartRunRequest` 已经支持：

- `task_contract_ref`
- `initial_stage_id`
- `route_policy_version`
- `skill_policy_version`
- `evaluation_policy_version`
- `task_view_policy_version`

对应位置：

- [contracts.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/contracts.py#L603)

`KernelFacade.start_run()` 也会把这些字段原样传给 gateway。

但 `TemporalSDKWorkflowGateway.start_workflow()` 在构造 `RunInput` 时，并没有把这些 TRACE 元数据继续传下去：

- [gateway.py](D:/chao_workspace/agent-kernel/agent_kernel/substrate/temporal/gateway.py#L76)

这意味着：

- 上层契约已经有了
- facade 也没丢
- 但 runtime substrate 还没真正消费和持久化它们

所以 `policy version freeze` 目前更像“接口就绪”，而不是“端到端闭合”。

### 3.3 `QueryRunResponse` 仍然太薄，导致 TRACE 读模型需要绕路

当前 `QueryRunResponse` 只有：

- lifecycle
- projected_offset
- waiting_external
- current_action_id
- recovery_mode
- recovery_reason
- active_child_runs

对应位置：

- [contracts.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/contracts.py#L693)

没有：

- `policy_versions`
- `review_state`
- `active_stage_id`
- `stage views`

结果就是：

- `query_trace_runtime()` 只能靠 facade 做额外拼装
- 但它拼装出来的又还不是 durable truth

所以这里还处于“读模型过渡态”。

### 3.4 Action truth 有了，但接口粒度和我们协商稿仍不完全一致

当前 `get_action_state()` 能返回：

- `reserved`
- `dispatched`
- `acknowledged`
- `succeeded`

而且 dedupe store 路径是实的。

对应位置：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L1140)

但这里目前的查询键是：

- `dispatch_idempotency_key`

而不是协商稿里更接近 TRACE 语义的：

- `run_id + action_id`

这不算阻断问题，但意味着：

- 当前 action truth 更偏执行层
- 还没有完全变成 TRACE 层的公共对象接口

## 4. 当前仍未满足的关键需求

### 4.1 `review_state` 还没有真正闭环

虽然有 `HumanGateRequest`，也能发出 `human_gate_opened` 信号：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L1113)

但 `query_trace_runtime()` 中：

- `review_state` 仍然固定是 `not_required`

这说明：

- gate 打开这件事能发出去
- 但 read model 还没有把 gate 状态可靠读回来

对于 TRACE 来说，这意味着：

- `ReviewState != approved` 的阻断逻辑还没形成完整公共真相

### 4.2 branch / stage 现在还是 facade 进程内存态，不是重建态

当前 branch/stage 的来源是：

- `self._branch_registry`
- `self._stage_registry`

对应位置：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L157)

这意味着一旦：

- facade 重启
- 多实例部署
- 读写分离

这些 branch/stage 视图并不能天然恢复。

所以它们虽然已经“有接口”，但还不能算真正 durable truth。

### 4.3 `supported_trace_features` 还没有对外声明

`KernelManifest` 已经包含：

- `trace_protocol_version`
- `supported_trace_features`

但当前 manifest 实际返回时：

- `supported_trace_features = frozenset()`

这意味着从平台协商角度看：

- kernel 虽然实现了不少 TRACE 特性
- 但还没有把它们正式宣告成稳定能力面

这会影响后续 `hi-agent` 的能力探测与降级策略。

### 4.4 事件类型已注册，不代表运行期已稳定落账

事件注册表里已经有：

- `branch.opened`
- `branch.state_updated`
- `task_view.recorded`
- `human_gate.opened`
- `run.policy_versions_pinned`

对应位置：

- [event_registry.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/event_registry.py#L475)

但从当前代码路径看，至少以下几项我还没看到端到端落账闭合：

- `task_view.recorded`
- `run.policy_versions_pinned`

也就是说：

- “事件类型已声明”是对的
- “运行期已经稳定写入并可查询”还不能完全确认

## 5. 对 hi-agent 的实际意义

如果回到最实际的问题：

`现在的 agent-kernel 能不能支撑 hi-agent 开始做单智能体 TRACE 落地？`

我的判断是：

`能。`

但更准确地说，它能支撑的是：

- `hi-agent` 先把 TRACE 的上层任务模型、CTS、Task View 选择、Skill/Evolve 逻辑搭起来
- 并通过现有 kernel 完成 run lifecycle、callback/recovery、Task View 记录、branch/stage/human gate 基本接入

它暂时还不够支撑的是：

- 把 kernel 当成“TRACE 全部公共真相的最终 authoritative surface”
- 直接把 7x24 长程运行的所有读模型和仲裁面都完全托付给现有实现

## 6. 我的最终判断

我会给出一个分层结论：

### 6.1 作为 V1 接入底座

`满足`

理由：

- durable runtime 已有
- LLM gateway 已有
- Task View 持久化已可用
- branch/stage/human gate 接口已存在
- 关键测试已通过

### 6.2 作为 TRACE 完整运行时真相面

`部分满足`

理由：

- TraceRuntimeView 存在，但还不是 durable reconstructed truth
- review/policy/stage active 等核心读模型仍不完整
- stage/branch 仍偏 facade 内存态

### 6.3 作为 7x24 企业级单智能体长期内核

`接近可用，但尚未完全满足`

必须优先补的 4 件事：

1. 把 `policy_versions`、`task_contract_ref`、`initial_stage_id` 真正贯通到 runtime 启动与回读路径
2. 让 `TraceRuntimeView` 从事件/投影重建，而不是依赖 facade 内存注册表
3. 补齐 `review_state` / `active_stage_id` / `policy_versions` 的公共读模型
4. 把 `supported_trace_features` 正式宣告出来，形成能力协商面

## 7. 一句话结论

`当前 agent-kernel 已经足够作为 hi-agent 的 V1 集成内核，但还不足以被视为 TRACE 已完全闭合的企业级长程运行时真相底座。`
