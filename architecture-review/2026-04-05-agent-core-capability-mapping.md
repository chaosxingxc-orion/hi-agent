# TRACE 对 `agent-core` 的能力映射清单

> 依据：
> - `2026-04-05-trace-architecture-review-v1.2.1.md`
> - `2026-04-05-trace-contract-mapping.md`
> - 当前仓库实现扫描：`openjiuwen/core/*`

## 1. 目的

TRACE 需要一个受控 `Harness` 平面，但 `hi-agent` 不应自己重新发明所有环境能力。

`agent-core` 已经具备大量应用层能力积木。本文件的目的，是把这些现有能力映射到 TRACE 的能力面中，区分：

- 可直接复用
- 需要包装后复用
- 当前仍有缺口

## 2. 总体判断

`agent-core` 当前更像一个“应用能力供给层”，而不是 TRACE 的认知内核。

这是好事。

它非常适合做 TRACE 的：

- Harness 能力供给
- Context / Session / Workflow / System Operation 资源层
- 技能与资产的供给层

但它不应该主导：

- Task View 语义装配
- Route / CTS 决策
- Evolve / Skill 认证闭环
- Runtime arbitration

## 3. 按 TRACE 平面映射

## 3.1 Context OS 相关能力

### 当前可见能力

- `openjiuwen.core.context_engine.context_engine.ContextEngine`
- `context/processor/token` 体系
- session 绑定的 context pool
- context save / restore
- processor 插件机制

### TRACE 映射

适合作为：

- `Task View` 组装时可调用的 context resource layer
- history / context slice 的底层承载
- token 预算相关基础设施

### 结论

- `可复用，但必须包装`

原因：

- `agent-core` 的 ContextEngine 更偏“会话上下文管理”
- TRACE 的 `Task View` 是任务视图，不是直接等于 session message window
- 所以 `hi-agent` 只能把它当底层资源，而不能直接把它当 TRACE 的 Context OS

## 3.2 Session / Run 相关能力

### 当前可见能力

- `openjiuwen.core.session.*`
- agent / workflow / node / state / tracer / stream / checkpointer

### TRACE 映射

适合作为：

- 资产层 session 资源
- artifact state 和 stream 输出支撑
- 部分中间态存取载体

### 结论

- `可部分复用`

原因：

- `agent-core` 的 session 更偏应用会话与 workflow session
- TRACE 的 durable run 主体仍应以 `agent-kernel` 为真相源

## 3.3 Workflow 能力

### 当前可见能力

- `openjiuwen.core.workflow.*`
- 分支、循环、sub-workflow、router 等组件

### TRACE 映射

适合作为：

- Harness 内部的复合执行能力
- 某些稳定、标准化、低探索度任务的 action backend
- 已知流程化子任务的执行器

### 结论

- `可复用且价值高`

原因：

- TRACE 并不排斥 workflow
- workflow 不应主导整体 agent cognition
- 但它非常适合作为 `Act` 阶段中某类动作的执行载体

## 3.4 SysOperation 能力

### 当前可见能力

从 `sys_operation.py` 可以确认：

- local / sandbox 模式
- `fs`
- `shell`
- `code`
- 动态 operation registry

### TRACE 映射

适合作为：

- Harness 的基础动作层
- 文件系统操作
- shell 操作
- code 操作
- 后续自定义 operation 的统一入口

### 结论

- `可直接作为 Harness 基础能力供给`

原因：

- 这是当前 `agent-core` 对 TRACE 最直接的价值之一
- 非常适合做 `read / mutate / publish / submit` 中的前两类底层载体

## 3.5 Tool / MCP / Service API 能力

### 当前可见能力

- `foundation/tool/*`
- function tool
- MCP tool
- service_api tool

### TRACE 映射

适合作为：

- Harness 中对外工具与系统能力调用的标准化资源
- 受控 action backend

### 结论

- `可直接复用，但需纳入 side-effect class 和 evidence contract`

原因：

- 当前 tool 体系是能力入口
- TRACE 还要求附加：
  - side effect class
  - evidence ref
  - callback ref
  - approval-required

## 3.6 Retrieval / Knowledge Access 能力

### 当前可见能力

- retrieval
- vector_store
- indexing
- parser
- reranker
- retriever

### TRACE 映射

适合作为：

- `Knowledge System` 的南向知识源
- 文档、网页、向量检索能力供给
- 证据抓取与知识切片获取

### 结论

- `可高价值复用`

原因：

- TRACE 的 knowledge plane 不必重造检索系统
- 但上层仍要决定“取什么”和“什么时候取”

## 3.7 Memory 能力

### 当前可见能力

- `openjiuwen.core.memory.*`
- graph memory
- memory config
- parsing and storage support

### TRACE 映射

适合作为：

- 作为长期经验与知识资产的潜在底层存储或辅助记忆引擎

### 结论

- `可探索复用，但不建议在 V1 作为唯一记忆真相`

原因：

- TRACE 当前最需要的是可控的 `Working / Episodic / Semantic / Procedural` 分层
- `agent-core` memory 可以做供给层，但不应直接定义 TRACE 的 memory semantics

## 3.8 Skill 能力

### 当前可见能力

从 `single_agent/skills/skill_manager.py` 可见：

- 技能注册
- 技能发现
- 基于 `Skill.md` 的元数据加载

### TRACE 映射

适合作为：

- 技能资源发现与元数据管理层
- 技能目录与文件级资产供给

### 结论

- `可部分复用`

原因：

- 当前 skill manager 更像技能注册表
- TRACE 的 skill lifecycle、认证、弃用、回滚，仍应由 `hi-agent` 定义

## 3.9 Task Manager / Callback 能力

### 当前可见能力

- `common/task_manager/*`
- callback framework
- task events
- timeout / failed / completed callback

### TRACE 映射

适合作为：

- 局部异步任务执行能力
- agent-core 内部资源层事件桥接

### 结论

- `可参考，不应替代 agent-kernel runtime`

原因：

- TRACE 的 durable runtime 主体必须是 `agent-kernel`
- `agent-core` task_manager 更适合做局部资源层工具，不适合做全局 run 真相

## 4. 按可用性分类

## 4.1 可直接复用

- `sys_operation` 的 `fs / shell / code`
- tool / MCP / service_api 能力入口
- workflow 作为某些动作的 backend
- retrieval 作为知识源入口

## 4.2 需要包装后复用

- `ContextEngine`
- session / checkpointer / tracer
- memory
- skill manager
- task manager / callback framework

## 4.3 当前主要缺口

`agent-core` 当前没有显式提供 TRACE 所需的以下一等能力：

- side-effect class contract
- evidence ref first-class return contract
- approval-required action contract
- callback ref standardization across all capability types
- experiment environment as explicit capability family
- final package generation as explicit reusable capability family

## 5. 对 Harness 装配的具体建议

## 5.1 第一批直接接入的 capability families

建议首批接入：

- `sys_operation.fs`
- `sys_operation.shell`
- `sys_operation.code`
- `tool.function`
- `tool.mcp`
- `workflow`
- `retrieval`

原因：

- 这批能力已经足够支撑 research closed loop 的最小执行面

## 5.2 第二批再接入

- memory-backed retrieval
- richer session state synchronization
- graph memory
- specialized business tools

## 5.3 不建议在 V1 直接承担的职责

`agent-core` 不建议在 V1 承担：

- durable run truth
- CTS routing
- task contract ownership
- evolve orchestration
- task-view semantic assembly

## 6. 对 `agent-core` 的接口统一诉求

为了让 `agent-core` 真正成为 TRACE Harness 的供给层，建议为能力返回结果逐步统一为最小结构：

- `status`
- `output_ref`
- `evidence_ref`
- `error_code`
- `callback_ref`
- `side_effect_class`

即使内部实现不同，也建议通过 adapter 统一成这个返回面。

## 7. research closed loop 对应映射

针对第一期科研闭环，推荐的能力映射是：

### 7.1 调研与资料读取

- retrieval
- context_engine
- tool.mcp / service_api
- sys_operation.fs

### 7.2 数据分析与实验

- workflow
- sys_operation.code
- sys_operation.shell

### 7.3 写作与打包

- workflow
- sys_operation.fs
- tool.function / service_api

### 7.4 人工审阅前交付

- session / stream / tracer
- callback framework
- artifact storage refs

## 8. 最终判断

`agent-core` 当前已经足够作为 TRACE 的 Harness 供给层启动第一阶段工作。

真正需要补的不是“有没有能力”，而是：

- 如何统一结果契约
- 如何补 side-effect / evidence / callback 元数据
- 如何避免 `agent-core` 越权进入认知组装与运行时真相

所以我的判断是：

`agent-core` 不需要大改，只需要通过 adapter 和 contract normalization，被纳入 TRACE 的 Harness 平面。`

