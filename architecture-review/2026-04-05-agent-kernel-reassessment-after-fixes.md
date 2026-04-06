# `agent-kernel` 修订后系统性复评

> 评估对象：`D:\chao_workspace\agent-kernel`
>
> 评估背景：
> - `agent-kernel` 团队已根据上一轮建议修改源码
> - 本次目标不是重复架构审查，而是验证这些修改是否真正提升了 `hi-agent` 的可接入性
>
> 评估方式：
> - 源码核查
> - 关键接口“真值检查”
> - 相关测试执行

## 1. 结论先行

这轮修改 `确实把 agent-kernel 往前推进了一步`，但我的总体结论仍然是：

`它现在可以满足 hi-agent 的 V1 集成需求，而且比上一轮更接近 TRACE；但还没有完全满足“把 kernel 直接当作 TRACE authoritative runtime truth surface”的要求。`

和上一轮相比，最大的进展是：

- TRACE 启动元数据已经开始真正贯通到 workflow 启动输入
- workflow 内部已经持有 `policy_versions / initial_stage_id / task_contract_ref`
- `run.policy_versions_pinned` 事件已经在 workflow 启动路径里显式落账

但最关键的两个上游消费面仍未闭合：

- `query_run / query_trace_runtime` 还没有把这些新增真相稳定读回来
- `KernelManifest.supported_trace_features` 仍然是空集

所以，如果给一个更准确的状态标签，我会给：

- `V1 接入：满足`
- `TRACE 元数据写入链路：部分满足，较上轮明显改善`
- `TRACE 公共读模型：仍然部分满足`

## 2. 这轮确认已经修到位的部分

### 2.1 TRACE 启动元数据已经进入 Temporal 启动输入

上一轮最明确的问题之一是：

- `StartRunRequest` 有 TRACE 字段
- 但 `TemporalSDKWorkflowGateway.start_workflow()` 没有把这些字段继续灌进 `RunInput`

这一点现在已经被修了。

当前代码：

- [gateway.py](D:/chao_workspace/agent-kernel/agent_kernel/substrate/temporal/gateway.py#L87)

已经把以下字段送入 `RunInput`：

- `policy_versions`
- `initial_stage_id`
- `task_contract_ref`

这是实质性改进，不是文档层修复。

### 2.2 Workflow 已开始持有 TRACE 元数据

`RunInput` 现在明确包含：

- `policy_versions`
- `initial_stage_id`
- `task_contract_ref`

位置：

- [run_actor_workflow.py](D:/chao_workspace/agent-kernel/agent_kernel/substrate/temporal/run_actor_workflow.py#L72)

而在 `RunActorWorkflow.run()` 中，也已经显式接收：

- `self._policy_versions`
- `self._active_stage_id`

位置：

- [run_actor_workflow.py](D:/chao_workspace/agent-kernel/agent_kernel/substrate/temporal/run_actor_workflow.py#L302)

这说明：TRACE 元数据不再只停留在 facade/request DTO 层。

### 2.3 `run.policy_versions_pinned` 已真正进入启动路径

现在 workflow 启动时，只要有 policy versions，就会追加：

- `run.policy_versions_pinned`

位置：

- [run_actor_workflow.py](D:/chao_workspace/agent-kernel/agent_kernel/substrate/temporal/run_actor_workflow.py#L308)

这点很重要，因为它意味着：

- 版本冻结开始有 durable event 证据
- 后续做 replay /审计 / evolve 对账时，不再只是靠内存或参数透传

### 2.4 合同层确实继续往 TRACE 靠近了

当前合同定义里已经出现：

- `RunProjection.policy_versions`
- `RunProjection.task_contract_ref`
- `QueryRunResponse.policy_versions`
- `QueryRunResponse.active_stage_id`

位置：

- [contracts.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/contracts.py#L260)
- [contracts.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/contracts.py#L693)

这说明团队不是只修 workflow，也在同步往公共契约面收口。

## 3. 这轮还没有真正修到位的部分

### 3.1 `query_run()` 仍然没有把新增字段回传出来

虽然 `QueryRunResponse` 已经新增了：

- `policy_versions`
- `active_stage_id`

但 `KernelFacade.query_run()` 当前返回时，并没有填这两个字段。

位置：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L423)

我做了直接校验，结果是：

- `query_run.policy_versions = None`
- `query_run.active_stage_id = None`

即使底层 `RunProjection` 已经带了 `policy_versions`，上层仍然读不到。

这说明：

- 合同字段加了
- 读路径还没贯通

### 3.2 `query_trace_runtime()` 仍然停留在过渡态

当前 `query_trace_runtime()` 仍然是：

- `review_state = "not_required"`
- `active_stage_id = None`
- `policy_versions = None`
- `branches / stages` 仍来自 facade 内存注册表

位置：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L813)

我做了直接校验，结果是：

- `trace.policy_versions = None`
- `trace.active_stage_id = None`
- `trace.review_state = not_required`

所以这一层现在仍不能算 TRACE 的完整公共真相面。

### 3.3 `KernelManifest.supported_trace_features` 仍未宣告

这条仍然没动。

虽然 `KernelManifest` 已经定义了：

- `trace_protocol_version`
- `supported_trace_features`

位置：

- [contracts.py](D:/chao_workspace/agent-kernel/agent_kernel/kernel/contracts.py#L2368)

但 `get_manifest()` 现在返回时，`supported_trace_features` 还是空集。

位置：

- [kernel_facade.py](D:/chao_workspace/agent-kernel/agent_kernel/adapters/facade/kernel_facade.py#L540)

我实际调用的结果是：

- `trace_protocol_version = 1.2.1`
- `supported_trace_features = frozenset()`

这意味着：

- 协议版本号有了
- 能力协商面还没有正式形成

### 3.4 TRACE 相关测试仍主要覆盖“接口存在”，未完全覆盖“真相读回”

当前测试虽然都通过了，但从内容看：

- `test_kernel_facade_trace.py` 里的 `query_trace_runtime` 仍然只验证旧行为
- 它仍然预期 `review_state == "not_required"`
- 没有验证 `policy_versions`、`active_stage_id`、真正的 review 状态读回

位置：

- [test_kernel_facade_trace.py](D:/chao_workspace/agent-kernel/python_tests/agent_kernel/adapters/test_kernel_facade_trace.py#L68)

这意味着：

- 当前回归网主要在保护“接口可调用”
- 还没有保护“TRACE 真相面已闭合”

## 4. 本次测试结果

我实际跑了以下测试：

```powershell
python -m pytest D:\chao_workspace\agent-kernel\python_tests\agent_kernel\adapters\test_kernel_facade_trace.py -q
python -m pytest D:\chao_workspace\agent-kernel\python_tests\agent_kernel\contracts\test_temporal_interface_contract.py -q
python -m pytest D:\chao_workspace\agent-kernel\python_tests\agent_kernel\substrate\test_run_actor_workflow.py -q -k "policy_versions or initial_stage_id or timeout_signal or query"
```

结果：

- `22 passed`
- `10 passed`
- `2 passed`

结论是：

- 这轮修改没有破坏现有接口
- 启动链路和 workflow 层的修复至少没有回归
- 但测试覆盖面仍然没有逼近“完整 TRACE 读模型”

## 5. 相比上一轮的判断变化

如果和上一轮评估相比，我会这样更新结论：

### 上一轮

- TRACE 元数据“写入链路”不完整
- 启动参数只到 facade/request 层

### 这一轮

- TRACE 元数据“写入链路”已经开始闭合
- workflow 内部也已经接住并落了一部分 durable event

所以这轮不是“没改到点子上”，而是：

`他们已经把最关键的写入面修了一半以上，但读模型和能力宣告面还没跟上。`

## 6. 对 hi-agent 的实际意义

从 `hi-agent` 的角度看，这轮修改后：

### 6.1 可以更放心开始 V1 集成

因为以下几条已经比较稳了：

- start_run 时 TRACE 元数据不会在 gateway 层丢失
- workflow 内部已经知道 policy versions 和 initial stage
- Task View 记录与 late-bind 仍然可用
- branch / stage / human gate 接口仍然在

### 6.2 但不能把上层状态判断完全交给 kernel 读模型

在当前版本里，如果 `hi-agent` 完全依赖：

- `query_run()`
- `query_trace_runtime()`

来做：

- review gate 判定
- 当前 active stage 判定
- policy version 对账

那么得到的仍然是不完整结果。

所以在这一阶段，更实际的接法应该是：

- 让 `agent-kernel` 承担 durable execution truth
- 但 `hi-agent` 仍暂时保留一部分 TRACE 语义层状态聚合
- 直到 kernel 的公共读模型真正补齐

## 7. 最终判断

我的最新结论是：

`当前 agent-kernel 已经比上一轮更接近 hi-agent 的需求，且足以支持 V1 集成启动；但还没有完全达到“hi-agent 可无保留依赖其 TRACE 公共真相面”的程度。`

如果要更凝练地说：

- `写入面：明显进步，部分闭合`
- `读模型：仍未闭合`
- `能力协商面：仍未闭合`

## 8. 还剩下最关键的 3 个收口点

如果只保留最小剩余项，我认为只剩这 3 个最关键：

1. `KernelFacade.query_run()` 真正回传 `policy_versions` 和 `active_stage_id`
2. `KernelFacade.query_trace_runtime()` 不再写死 `review_state / active_stage_id / policy_versions`
3. `KernelManifest.supported_trace_features` 正式宣告已实现的 TRACE 能力

这 3 个点补完之后，我会更愿意把 `agent-kernel` 评价为：

`基本满足 hi-agent 对 TRACE V1 内核的使用需求。`
