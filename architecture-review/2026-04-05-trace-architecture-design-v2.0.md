# TRACE 企业级智能体架构设计 V2.0

> 状态：`V2.0 重写版`
>
> 仓库：
> - `D:\chao_workspace\hi-agent`
> - `D:\chao_workspace\agent-kernel`
> - `D:\chao_workspace\external\agent-core`
>
> 目的：
> - 给出 `hi-agent` 的正确系统装配架构
> - 明确 `hi-agent / agent-kernel / agent-core` 的真实关系
> - 作为后续单智能体实现的正式设计基线

---

## 1. 设计结论

V2.0 的核心结论只有一句话：

`系统主体只有一个：hi-agent。`

`hi-agent` 是智能体产品本体；它选择性集成 `agent-core` 的能力模块，并通过适配层使用 `agent-kernel` 作为运行时底座。

因此，正确的系统关系不是：

- `hi-agent`
- `agent-kernel`
- `agent-core`

三个系统平级协作。

而是：

- `hi-agent` 在最上层，作为唯一智能体主体
- `agent-core` 是 `hi-agent` 内部集成的能力来源
- `agent-kernel` 是 `hi-agent` 下方依赖的 durable runtime

---

## 2. 系统定位

`hi-agent` 不是科研专用系统，而是一套企业级智能体架构。

科研任务只是第一阶段验证域，因为它天然具备：

- 长程任务执行
- 多阶段推进
- 多轨迹探索
- 数据/代码/写作/交付闭环
- 明确的质量与效率反馈

所以 V2.0 的正式定位是：

`hi-agent` 是一个以任务为中心、以 TRACE 为核心抽象、以 agent-kernel 为运行时底座、以 agent-core 为能力模块来源的企业级单智能体系统。`

---

## 3. TRACE 核心抽象

统一抽象为：

`TRACE = Task -> Route -> Act -> Capture -> Evolve`

五个阶段定义如下：

- `Task`：把用户请求提升为任务契约
- `Route`：在受约束轨迹空间中生成、比较、选择路径
- `Act`：通过 Harness 操作外部世界
- `Capture`：沉淀证据、结果、失败和轨迹状态
- `Evolve`：基于反馈持续优化质量与效率

TRACE 与 ReAct 的差异不在于“多几个模块”，而在于：

- `ReAct` 以短程交互循环为中心
- `TRACE` 以长程任务运行体为中心

---

## 4. 两个硬约束

### 4.1 模型是认知驱动，但上下文窗口有限

这意味着：

- 智能体不能等于无限增长的会话历史
- 长程执行不能依赖一段永不结束的 prompt
- 每次模型调用必须基于重建的 `Task View`

### 4.2 模型能力会演进，provider 会变化

这意味着：

- 必须充分利用模型进步
- 但不得把系统认知结构绑定到某个 provider
- provider 差异必须隐藏在 `LLM Gateway` 之后

---

## 5. 系统装配架构

这一节只回答一个问题：

`hi-agent 这个系统是怎么装起来的？`

### 5.1 顶层装配图

```text
+----------------------------------------------------------------------------------+
|                                    hi-agent                                      |
|----------------------------------------------------------------------------------|
|  TRACE Agent Runtime                                                             |
|  - Task Runtime                                                                  |
|  - Route Engine                                                                  |
|  - Context OS                                                                    |
|  - Memory / Knowledge / Skill / Evolve                                           |
|  - Harness Orchestrator                                                          |
|                                                                                  |
|  Integrated Capability Modules                                                   |
|  - integrated from agent-core                                                    |
|  - session / context resources / tool / workflow / sys_operation / retrieval     |
|                                                                                  |
|  Runtime Adapter                                                                 |
|  - adapt TRACE runtime operations to agent-kernel                                |
+----------------------------------------------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                                 agent-kernel                                     |
|----------------------------------------------------------------------------------|
|  Durable Runtime Substrate                                                       |
|  - run lifecycle                                                                 |
|  - wait / resume / callback / recovery                                           |
|  - event log / projection / replay metadata                                      |
|  - LLM Gateway                                                                   |
|  - harness governance / idempotency / arbitration                                |
+----------------------------------------------------------------------------------+
```

### 5.2 关键解释

- `hi-agent` 是唯一的智能体系统
- `agent-core` 不以一个完整系统层出现，而是以“被集成能力模块”出现在 `hi-agent` 内部
- `agent-kernel` 不参与上层认知建模，它只提供运行时底座

---

## 6. hi-agent 内部结构

V2.0 中，`hi-agent` 内部应拆成 3 个面：

### 6.1 TRACE Agent Runtime

这是智能体本身。

包含：

- `Task Runtime`
- `Route Engine`
- `Context OS`
- `Memory System`
- `Knowledge System`
- `Skill System`
- `Evolution Engine`
- `Harness Orchestrator`

### 6.2 Integrated Capability Modules

这是从 `agent-core` 选择性集成进来的能力。

包括：

- session
- context resources
- tool
- workflow
- sys_operation
- retrieval
- service_api
- mcp
- asset access

说明：

- `hi-agent` 不应整仓复制 `agent-core` 的认知结构
- 只应复用它作为能力模块库和资源模块库的部分

### 6.3 Runtime Adapter

这是 `hi-agent` 和 `agent-kernel` 之间的适配层。

它负责：

- `start_run / signal_run / query_run / query_trace_runtime`
- `record_task_view / bind_task_view_to_decision`
- `open_stage / mark_stage_state`
- `open_branch / mark_branch_state`
- `open_human_gate`
- callback / recovery / replay 相关转换

---

## 7. 职责边界图

这一节只回答：

`谁负责什么？`

### 7.1 `hi-agent`

负责“智能体是什么、怎么思考、怎么进化”。

具体包括：

- Task Contract
- CTS / Stage Graph
- Route Policy
- Task View Selection
- Memory / Knowledge 语义
- Skill Lifecycle
- Evaluation Logic
- Evolve Logic

### 7.2 `agent-kernel`

负责“任务如何长期活着并被可靠执行”。

具体包括：

- Run Lifecycle
- durable runtime
- wait / resume / callback wakeup
- event log / projection / replay metadata
- recovery / idempotency / arbitration
- LLM Gateway
- Harness invocation governance

### 7.3 `agent-core`

负责“可被复用的应用能力与资源供给”。

具体包括：

- session
- context resources
- tool / mcp / service_api
- workflow
- sys_operation
- retrieval
- asset access

关键边界：

- `agent-core` 不负责 route
- `agent-core` 不负责 task view selection
- `agent-core` 不负责 evolve
- `agent-core` 不负责 runtime truth

---

## 8. 一等概念

V2.0 保留以下 10 个一等概念：

- `Task`
- `Run`
- `Stage`
- `Branch`
- `Task View`
- `Action`
- `Memory`
- `Knowledge`
- `Skill`
- `Feedback`

### 8.1 Task

任务契约，而不是用户一句话。

### 8.2 Run

任务的长程运行主体。

### 8.3 Stage

任务推进的正式阶段对象。

### 8.4 Branch

轨迹树中的逻辑分支。

`Branch` 是 TRACE 语义对象，不等于 child run。

### 8.5 Task View

某次模型调用前被重建出来的最小充分上下文。

### 8.6 Action

通过 Harness 执行的外部动作。

### 8.7 Memory

保存经历过什么。

### 8.8 Knowledge

保存稳定知道什么。

### 8.9 Skill

从优质轨迹中结晶出来的可复用过程单元。

### 8.10 Feedback

把业务结果、人工评价、实验结果转成优化信号。

---

## 9. CTS：受约束轨迹空间

TRACE 的核心机制是：

`CTS = Constrained Trajectory Space`

CTS 包含两层：

- `Stage Graph`
- `Trajectory Tree`

### 9.1 Stage Graph

定义：

- 允许经过哪些阶段
- 允许哪些阶段间转移
- 每阶段允许哪些动作
- 何时回退
- 何时触发 Human Gate

默认阶段图可抽象为：

- `S1 Understand`
- `S2 Gather`
- `S3 Build / Analyze`
- `S4 Synthesize / Package`
- `S5 Review / Finalize`

### 9.2 Trajectory Tree

定义某个 Run 实际探索过的分支。

每个 Branch 至少要表达：

- 所属 stage
- 当前状态
- 失败原因
- 成功与否
- 效率优劣
- 是否等待 callback

### 9.3 CTS 预算

至少包括：

- `max_active_branches_per_stage`
- `max_total_branches_per_run`
- `max_route_compare_calls_per_cycle`
- `max_route_compare_token_budget`
- `max_exploration_wall_clock_budget`

---

## 10. 知识、记忆、数据系统、IT 系统的位置

### 10.1 Memory

记录智能体经历。

- `Working Memory`
- `Episodic Memory`

### 10.2 Knowledge

记录智能体稳定知道什么。

- `Semantic Knowledge`
- `Procedural Knowledge`

### 10.3 Data Systems

外部资源，不是 memory。

包括：

- database
- data warehouse
- vector store
- object store
- experiment result store

### 10.4 IT Systems

外部操作对象，不是 knowledge。

包括：

- workflow tools
- code repositories
- office systems
- business systems
- publishing / delivery preparation systems

### 10.5 正式边界

```text
Memory / Knowledge = hi-agent 内部可进化资产
Data Systems / IT Systems = Harness 操作的外部环境
agent-core = 提供访问这些外部环境的能力模块
agent-kernel = 治理执行与记录真相
```

---

## 11. Harness 正式定义

Harness 在 V2.0 中属于 `hi-agent` 内部的编排面，不是独立平级系统。

但它的执行治理由 `agent-kernel` 承载，能力实现主要来自 `agent-core`。

因此：

- Harness 的“语义编排”归 `hi-agent`
- Harness 的“执行治理”归 `agent-kernel`
- Harness 的“能力供给”来自 `agent-core`

### 11.1 Harness 最小职责

- 统一能力调用协议
- 统一权限与安全边界
- timeout / retry / budget 控制
- callback 支持
- evidence 采集
- 输出归一化

### 11.2 双维度副作用治理

V2.0 保留：

- `effect_class`
  - `read_only`
  - `idempotent_write`
  - `compensatable_write`
  - `irreversible_write`

- `side_effect_class`
  - `read_only`
  - `local_write`
  - `external_write`
  - `irreversible_submit`

---

## 12. 运行时真相模型

TRACE 运行时至少包含：

- `RunState`
- `StageState`
- `BranchState`
- `ActionState`
- `WaitState`
- `ReviewState`

### 12.1 RunState

- `created`
- `active`
- `waiting`
- `recovering`
- `completed`
- `failed`
- `aborted`

### 12.2 StageState

- `pending`
- `active`
- `blocked`
- `completed`
- `failed`

### 12.3 BranchState

- `proposed`
- `active`
- `waiting`
- `pruned`
- `succeeded`
- `failed`

### 12.4 ActionState

- `prepared`
- `dispatched`
- `acknowledged`
- `succeeded`
- `effect_unknown`
- `failed`

### 12.5 WaitState

- `none`
- `external_callback`
- `human_review`
- `scheduled_resume`

### 12.6 ReviewState

- `not_required`
- `requested`
- `in_review`
- `approved`
- `rejected`

---

## 13. 当前实现状态

这一节只描述：

`当前实现到了哪里？`

### 13.1 当前已具备

- `StartRunRequest` 已支持 TRACE 元数据
- gateway 已开始向 `RunInput` 传入：
  - `policy_versions`
  - `initial_stage_id`
  - `task_contract_ref`
- workflow 已接住这些字段
- `run.policy_versions_pinned` 已在 workflow 启动路径落账
- `TaskViewRecord` 持久化与 late-bind 已可用
- `open_stage / mark_stage_state / open_branch / mark_branch_state / open_human_gate` 已存在
- callback / timeout / recovery 基础仲裁已可用

### 13.2 当前未完全闭合

- `query_run()` 尚未稳定回传 `policy_versions / active_stage_id`
- `query_trace_runtime()` 尚未稳定回传：
  - `review_state`
  - `active_stage_id`
  - `policy_versions`
- `TraceRuntimeView` 仍偏 facade 聚合视图
- `KernelManifest.supported_trace_features` 尚未正式宣告

### 13.3 对 hi-agent 的现实含义

当前阶段：

- 可以基于 `agent-kernel` 启动 V1 集成
- 但 `hi-agent` 仍需暂时保留一部分上层语义聚合
- 在 kernel 的公共读模型闭合前，不应完全依赖其 TRACE 读面

---

## 14. V2.0 最终结论

`TRACE V2.0 的正确架构不是 hi-agent、agent-core、agent-kernel 三层平级，而是：hi-agent 作为唯一智能体主体，集成 agent-core 的部分能力模块，并通过适配层使用 agent-kernel 作为 durable runtime 底座。`
