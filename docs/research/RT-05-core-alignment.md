# RT-05: agent-core (openjiuwen) 能力对齐

> 优先级：P1
> 预计时间：5-7 天
> 前置依赖：RT-04（需要 agent-kernel 接口映射结论）
> 负责人：待分配
> 状态：TODO

## 1. 核心问题

agent-core (openjiuwen) 是一个成熟的 AI Agent 框架，有丰富的 LLM/Workflow/Memory/Evolve 能力。但它的 API 是为 ReAct 循环设计的，不是为 TRACE 的 CTS（受约束轨迹空间）设计的。

**必须回答的问题：**
- Q1: hi-agent 应该直接用 agent-core 的 LLMClient，还是通过 agent-kernel 的 LLM Gateway？三层调用关系是什么？
- Q2: agent-core 的 LongTermMemory（episodic + semantic）能否作为 hi-agent L3_episodic 的存储后端？
- Q3: agent-core 的 Evaluator + Optimizer + Trainer 如何映射到 TRACE 的 EvolveSession + ChangeSet + QualityGate？
- Q4: agent-core 的 tool/workflow/retrieval 如何注册到 hi-agent 的 CapabilityRegistry？需要多少 adapter 代码？

## 2. 背景

### agent-core 已有能力（基于源码扫描）
```
openjiuwen/
  core/
    agents/         # LLMAgent, ControllerAgent, WorkflowAgent
    clients/        # LLMClient, HTTPClient, ClientRegistry（连接池 + ref counting）
    memory/         # LongTermMemory（episodic + semantic 双模式）
    logging/        # 完整日志系统
    security/       # SSL/JSON/URL 安全
    exceptions/     # 错误代码映射
  deepagents/       # 高级 Agent 能力
  agent_evolving/   # 进化框架
    evaluator/      # 评估器
    optimizer/      # 优化器（instruction/tool_call/memory）
    trainer/        # 训练器
  extensions/       # 扩展点
```

### TRACE 的期望接口
```
Capability 注册（§8.1）：
  CapabilityDescriptor { capability_id, capability_kind, version, effect_class, schema_ref, ... }

Capability 调用（§31）：
  CapabilityService.Invoke(CapabilityRequest) -> CapabilityResponse

LLM 调用路径：
  hi-agent → 构建 Task View → 通过 agent-kernel LLM Gateway 调用 LLM
  （还是直接用 agent-core 的 LLMClient？）

Memory 对接：
  hi-agent 定义了 L0/L1/L2/L3 四层（§25.3）
  agent-core 有 LongTermMemory
  如何复用？
```

## 3. 研究内容

### 3.1: 三层 LLM 调用路径分析

**目标：** 确定 hi-agent 的 LLM 调用应该走哪条路径。

```
可选路径：

路径 A: hi-agent → agent-core LLMClient → LLM Provider
  优势：直接复用 agent-core 的连接池/retry/fallback
  劣势：agent-kernel 无法记录 token 消耗（成本归因在 kernel 层做 §13.10）

路径 B: hi-agent → agent-kernel LLM Gateway → LLM Provider
  优势：token 计量和成本归因在 kernel 层统一管理
  劣势：多一跳延迟；agent-core 的 LLMClient 优化被绕过

路径 C: hi-agent → agent-core LLMClient → agent-kernel 记录 → LLM Provider
  优势：兼顾 agent-core 的客户端优化和 kernel 的 token 计量
  劣势：复杂度高，需要 agent-core 在调用时通知 kernel
```

**研究方式：**
1. 读 agent-kernel/kernel/cognitive/llm_gateway.py 了解 LLM Gateway 的实际接口
2. 读 agent-core/openjiuwen/core/clients/ 了解 LLMClient 的实际接口
3. 测量路径 A vs 路径 B 的延迟差异（同一 LLM 请求，不同路径）
4. 评估 token 计量的实现位置对成本归因（§13.10）的影响

**产出：** 路径选择建议 + 延迟对比数据 + 成本归因方案

### 3.2: Memory 对齐方案

**目标：** 确定如何复用 agent-core 的 LongTermMemory。

```
agent-core 的 LongTermMemory:
  - episodic: 存储历史交互的 episode
  - semantic: 存储稳定知识

hi-agent 的分层记忆（§25.3）:
  - L0_raw: agent-kernel event log（不在 agent-core）
  - L1_compressed: hi-agent 管理（不在 agent-core）
  - L2_index: hi-agent 管理（不在 agent-core）
  - L3_episodic: 跨 Run 情景记忆

KnowledgeWiki（§26）:
  - 链接页面网络（不在 agent-core）

问题：
  1. agent-core 的 episodic memory 能作为 L3_episodic 的存储后端吗？
     - 数据格式是否兼容？
     - 去重逻辑（embedding 相似度 > 0.85）谁执行？
  2. agent-core 的 semantic memory 与 KnowledgeWiki 是什么关系？
     - 替代？互补？冲突？
```

**研究方式：**
1. 读 agent-core/openjiuwen/core/memory/ 的完整源码，理解 episodic/semantic 的数据结构
2. 设计 L3_episodic 到 agent-core episodic memory 的 adapter
3. 评估 KnowledgeWiki 是否需要独立实现还是可以基于 agent-core semantic memory 扩展

**产出：** Memory 对齐方案文档 + adapter prototype

### 3.3: Evolve 框架映射

**目标：** 确定如何复用 agent-core 的进化框架。

```
agent-core 的进化能力：
  agent_evolving/
    evaluator/: 评估 agent 表现
    optimizer/: 优化 instruction / tool_call / memory
    trainer/:  训练流程

hi-agent 的 Evolve（§10）:
  - EvolveSession 状态机
  - 4 种 ChangeSet 生成策略（human_guided / parameter_tuning / skill_extraction / knowledge_discovery）
  - 3 种离线评估方法（route_replay / counterfactual / full_simulation）
  - QualityGate 量化门
  - A/B 实验

映射：
  agent-core optimizer → hi-agent parameter_tuning 策略？
  agent-core evaluator → hi-agent QualityGate 评估？
  agent-core trainer → hi-agent skill_extraction？
```

**研究方式：**
1. 读 agent-core/openjiuwen/agent_evolving/ 的源码
2. 逐一对照 hi-agent 的 4 种 ChangeSet 生成策略，判断哪些可以直接复用 agent-core
3. 写一个 mapping 文档：每个 TRACE Evolve 操作 → 对应的 agent-core 组件 + adapter 需求

**产出：** Evolve 映射方案 + 哪些组件直接复用 / 哪些需要 adapter / 哪些需要从零实现

### 3.4: Capability 注册 adapter

**目标：** 设计 agent-core 的工具/工作流如何注册到 hi-agent 的 CapabilityRegistry。

```
agent-core 的能力：
  - tools: 通过 LLMAgent 的 tool binding
  - workflows: 通过 WorkflowAgent 的 DAG 调度
  - retrieval: 通过 LLM + embedding 检索

hi-agent 的 CapabilityRegistry（§8.1）:
  每个能力需要声明：
    capability_id, capability_kind, version, effect_class, side_effect_class,
    schema_ref, sandbox_class, hot_update_policy, expected_p99_latency, max_retries

问题：
  - agent-core 的 tool 如何生成 CapabilityDescriptor？
  - effect_class / side_effect_class 谁来标注？
  - schema_ref 从哪里获取？
```

**研究方式：**
1. 选 3 个 agent-core 的典型能力（一个 tool、一个 workflow、一个 retrieval）
2. 手动构造它们的 CapabilityDescriptor
3. 评估自动化注册的可行性（从 agent-core 的 tool 定义自动生成 descriptor）

**产出：** 3 个 Capability adapter 示例 + 自动注册方案评估

## 4. 产出物清单

| 产出 | 格式 | 位置 |
|------|------|------|
| 三层 LLM 调用路径选择 | Markdown + 延迟数据 | `docs/research/data/rt-05-llm-path.md` |
| Memory 对齐方案 | Markdown + adapter prototype | `docs/research/data/rt-05-memory.md` |
| Evolve 框架映射 | Markdown 映射表 | `docs/research/data/rt-05-evolve-mapping.md` |
| 3 个 Capability adapter 示例 | Python | `hi_agent/capability/adapters/` |
| 完整对齐评估 | Markdown | 本文件 §5 |

## 5. 对架构的反馈（实验完成后填写）

### 验证的假设
- [ ] agent-core 的能力可以通过 adapter 注册到 CapabilityRegistry
- [ ] agent-core 的 LongTermMemory 可作为 L3 存储后端
- [ ] agent-core 的 Evolve 框架可部分复用于 TRACE 的 parameter_tuning

### 推翻的假设（如有）
（实验后填写）

### 需要修改架构的地方（如有）
（实验后填写）
