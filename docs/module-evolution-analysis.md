# Hi-Agent 模块进化分析报告

> 基于两个第一性原理的逐模块对标分析
> 日期：2026-04-07
> 对标来源：claude-code-rev（Anthropic官方CLI）、agent_research（10个框架调研）、agent-core（openJiuwen）

## 第一性原理

- **P1**: 智能体要能持续进化
- **P2**: 智能体驱动的成本要持续降低（模型的上下文是有限的）

---

## 一、上下文工程管理

### 1.1 会话管理（Session）

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| 会话持久化 | RunStateStore写JSON | Session transcript持久化+resume | Session+Checkpoint(Redis/DB) |
| 上下文压缩 | MemoryCompressor有LLM压缩（单层） | **三层递进**：Snip(删除)→Microcompact(API原生)→Autocompact(LLM摘要) | **处理器链**：MessageOffloader(截断)→DialogueCompressor(LLM摘要) |
| 压缩触发 | 手动调用 | **惰性触发**：每轮query loop检查`contextWindow - 13000`阈值 | **双时机**：on_add_messages(入库时)+on_get_context_window(取用时) |
| Token计数 | count_tokens()简单启发式（字符数/4） | 精确token计数+cache_read/cache_creation区分 | 可插拔TokenCounter(OpenAI/DashScope) |

#### claude-code的三层递进压缩机制（关键参考）

```
每轮query loop开始时：
  1. Snip（零成本）：直接删除旧消息，保留最近N条
     - 触发条件：HISTORY_SNIP feature flag启用
     - 效果：释放token空间，零LLM调用成本
     
  2. Microcompact（零额外成本）：利用API原生能力压缩
     - 触发条件：always（作为API请求的一部分）
     - 效果：API层面的内置压缩，不产生额外调用
     
  3. Autocompact（有成本）：LLM调用做摘要
     - 触发条件：token数 > contextWindow - 13000
     - 熔断器：连续3次失败后停止尝试
     - 回退链：session memory压缩 → 完整conversation压缩
     - 效果：最彻底的压缩，但消耗LLM调用
```

#### agent-core的处理器链模式（关键参考）

```python
# ContextEngine的处理器在两个时机介入：
# 1. on_add_messages —— 消息入库时检查是否需要截断
# 2. on_get_context_window —— 上下文取用时检查是否需要压缩

# MessageOffloader配置示例：
MessageOffloaderConfig(
    tokens_threshold=20000,    # 超过2万token触发
    large_message_threshold=1000,  # 大于1000token的消息可被截断
    trim_size=100,             # 截断后保留100 token
    keep_last_round=True,      # 始终保留最近一轮
    offload_message_type=["tool"],  # 只截断tool结果
)
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 1.1.1 | 三层递进压缩 | P2 | 在现有ContextProcessorChain基础上增加SnipProcessor和MicrocompactProcessor | token消耗降30-40% |
| 1.1.2 | 自动触发机制 | P2 | 每次Task View构建前自动检查token阈值，触发压缩链 | 消除手动压缩的遗忘风险 |
| 1.1.3 | 精确Token计数 | P2 | 替换字符数/4的启发式，采用tiktoken或可插拔计数器 | 预算计算精度提升10x |
| 1.1.4 | 压缩熔断器 | P2 | 连续N次压缩失败后停止尝试，避免浪费LLM调用 | 防止压缩本身消耗过多成本 |

#### 讨论状态：`待讨论`

---

### 1.2 记忆管理（Memory）

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| Working Memory | L0 Raw + L1 Compressed + L2 Index（三层架构） | 当前消息列表 | 模型上下文窗口 |
| Episodic Memory | EpisodicMemoryStore(JSON文件，关键词匹配) | .claude/memory/ markdown笔记(200行上限) | 向量语义搜索+长期记忆+片段管理 |
| 矛盾检测 | L0有contradiction detection | 无 | 无 |
| 记忆检索 | MemoryRetriever(task_family过滤+failure_code匹配) | 相关性评分+按需加载+prefetch | 语义embedding+BM25混合搜索+reranking |
| 记忆淘汰 | 无（全量保留） | 行数/字节数硬上限 | 窗口策略+重要性评分 |

#### hi-agent的优势（应保持）

- **三层Working Memory**（L0→L1→L2）是业界最系统的设计，无框架具备
- **矛盾检测**是独有能力，直接服务P1（进化需要发现并解决矛盾）
- **EpisodeBuilder**从Run数据自动构建Episode，形成闭环

#### 需要进化的方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 1.2.1 | 语义向量检索 | P1+P2 | Episodic Memory增加embedding，检索时用向量相似度而非关键词 | 检索精准度提升3-5x，减少无关context(P2) |
| 1.2.2 | 记忆相关性评分 | P2 | 检索结果按相关性排序，只取top-K加入Task View | 减少无效token占用 |
| 1.2.3 | 记忆淘汰策略 | P2 | 基于时间衰减+访问频率的淘汰机制 | 防止Episodic Store无限膨胀 |
| 1.2.4 | 记忆预取(Prefetch) | P2 | 参考claude-code的startRelevantMemoryPrefetch()，在Stage开始时异步预取相关记忆 | 减少同步等待时间 |

#### 讨论状态：`待讨论`

---

### 1.3 知识管理（Knowledge）

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| 知识存储 | InMemoryKnowledgeStore(内存KV) | 无独立知识系统 | 完整RAG管线(embedding+chunking+vector store) |
| 知识检索 | search_by_tags(标签匹配) | 无 | BM25+语义混合搜索+reranking+查询重写 |
| 知识摄入 | ingest_run_summary(运行摘要) | 无 | 文档chunking+索引+向量化+多格式支持 |
| 知识类型 | fact/method/rule/procedure | 无 | 向量+结构化+图谱 |

#### 这是最大差距

hi-agent的Knowledge系统目前本质上是一个`dict[str, str]`，与架构承诺的"语义知识+程序性知识"差距最大。agent-core的retrieval模块提供了工业级参考：

```
agent-core RAG管线：
  文档 → Chunking(分块) → Embedding(向量化) → Vector Store(存储)
                                                      ↓
  查询 → Query Rewriting(查询重写) → Embedding → 混合检索(BM25+向量) → Reranking → 结果
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 1.3.1 | 向量化知识存储 | P1 | 集成轻量向量库或agent-core的retrieval模块 | 知识积累从"记住"变成"理解" |
| 1.3.2 | 混合检索 | P1+P2 | 关键词+语义双路检索，取top-K | 精准检索减少无关知识(P2)，找到真正有用的知识(P1) |
| 1.3.3 | 知识自动摄入 | P1 | 每次Run的发现/决策自动入库（不只是摘要） | 知识持续积累 |
| 1.3.4 | 知识版本化 | P1 | 知识条目带版本号，Evolve可以更新知识 | 知识可以被修正和进化 |

#### 讨论状态：`待讨论`

---

### 1.4 技能管理（Skill）

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| Skill生命周期 | 5阶段(Candidate→Provisional→Certified→Deprecated→Retired) | /skills目录(静态文件) | SkillCreator(GitHub加载)+动态注册 |
| Skill匹配 | SkillMatcher(scope+preconditions+forbidden) | 无匹配机制 | 无匹配机制 |
| Skill进化 | Evolve提取(启发式+LLM) | 无 | AgentRL(强化学习优化) |
| 成本属性 | side_effect_class+rollback_policy | 无 | 无 |
| Prompt调优 | 无 | 无 | **Operator Tunables**(暴露可调参数，自动优化prompt) |

#### hi-agent的优势（应保持）

- **5阶段生命周期**是业界最严格的Skill治理模型
- **SkillMatcher**的preconditions/forbidden检查是独有的安全机制
- **side_effect_class**把Skill和Harness治理连接起来

#### agent-core的Operator Tunables模式（关键参考）

```python
# agent-core的每个Operator暴露可调参数：
class LLMCallOperator:
    def get_tunables(self):
        tunables = {}
        if not self._freeze_system_prompt:
            tunables["system_prompt"] = TunableSpec(
                name="system_prompt",
                kind="prompt",
                path="system_prompt",
            )
        return tunables

# 这意味着：
# 1. 每个Skill的prompt可以被自动优化（P1：进化）
# 2. 优化后的prompt更短更精准（P2：降成本）
# 3. freeze_*标志控制哪些参数不可变（安全边界）
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 1.4.1 | Skill Prompt Tunables | P1+P2 | 每个Skill暴露可调prompt参数，Evolve可以优化它们 | Skill的prompt持续变短变精准 |
| 1.4.2 | Skill效果评估 | P1 | 借鉴AgentRL，对Skill的质量/效率做量化评估 | 数据驱动的Skill进化 |
| 1.4.3 | Skill成本标签 | P2 | 每个Skill标注预期token消耗，RouteEngine在选择时考虑成本 | 优先选择低成本Skill |
| 1.4.4 | Skill组合优化 | P1 | 分析哪些Skill组合效果最好，自动推荐Skill序列 | 减少试错成本 |

#### 讨论状态：`待讨论`

---

## 二、任务管理

### 2.1 任务通信

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| 父子通信 | Orchestrator→RunExecutor(同步函数调用) | AgentTool→Worker(进程隔离)+task-notification XML | LLMController→Task[](ReAct循环) |
| 异步通知 | 无 | **task-notification**：子任务完成→XML通知→父任务继续 | Event驱动callback(@emit_after) |
| 广播 | 无 | SendMessageTool支持"*"广播所有Worker | 多Agent Team |
| 结构化消息 | 无 | shutdown_request/response, plan_approval | 无 |
| Agent继续 | 无 | SendMessageTool({to: agentId, message})继续已完成的Agent | 无 |

#### claude-code的task-notification模式（关键参考）

```xml
<!-- 子任务完成后，父任务收到结构化通知 -->
<task-notification>
  <task-id>a1b2c3d4e</task-id>
  <status>completed</status>
  <summary>Analyzed Q4 revenue data</summary>
  <result>Revenue grew 15% YoY...</result>
  <usage>
    <total_tokens>12500</total_tokens>
    <tool_uses>8</tool_uses>
    <duration_ms>45000</duration_ms>
  </usage>
</task-notification>

<!-- 关键设计：
  1. 异步：子任务在后台运行，完成后通知
  2. 结构化：包含状态、摘要、结果、用量
  3. 可继续：用SendMessage(to=task-id)继续对话
  4. 成本可见：usage字段直接暴露token消耗
-->
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 2.1.1 | 异步任务通知 | P2 | Orchestrator子任务完成后发结构化通知，父任务不阻塞等待 | 并行提升效率，减少等待时间 |
| 2.1.2 | 任务用量透传 | P2 | 通知中包含token/cost用量，父任务可做预算决策 | 成本可见→可控 |
| 2.1.3 | 子任务继续 | P1 | 支持向已完成的子任务发消息继续工作 | 迭代优化而非重新执行 |
| 2.1.4 | Event装饰器 | P1 | 参考agent-core的@emit_after，关键操作自动发事件 | 观测粒度提升，Evolve数据更丰富 |

#### 讨论状态：`待讨论`

---

### 2.2 任务观测

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| 事件流 | EventEmitter(内存，同步) | AsyncGenerator yield(流式) | 异步callback框架 |
| 进度报告 | DAGProgress回调(批量) | TaskProgressMessage(实时流) | Event驱动 |
| 成本观测 | LLMBudgetTracker(调用数+token数) | **精确USD成本**：per-model定价×用量，含cache折扣 | Operator级别追踪 |
| 用量聚合 | 无 | per-model累加+session持久化+OTel export | 无 |
| 可观测性导出 | 无 | OpenTelemetry(counter+histogram) | 无 |

#### claude-code的成本追踪模型（关键参考）

```typescript
// 定价表（per million tokens）
COST_TIER_15_75 = {
  input: 15,      // $15/M input tokens
  output: 75,     // $75/M output tokens  
  write: 18.75,   // $18.75/M cache write tokens
  read: 1.5       // $1.5/M cache read tokens (90%折扣！)
}

// 成本计算
cost = (input_tokens / 1M) × inputPrice
     + (output_tokens / 1M) × outputPrice
     + (cache_read_tokens / 1M) × cacheReadPrice    // 极低成本
     + (cache_creation_tokens / 1M) × cacheWritePrice
     + web_search_count × webSearchPrice

// 关键洞察：cache_read只有input的1/10成本
// 意味着：最大化prompt caching是P2的最高ROI策略
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 2.2.1 | CostTracker模块 | P2 | per-model定价表+精确USD成本计算+cache折扣 | 成本从"不可见"变为"精确到分" |
| 2.2.2 | 三层成本聚合 | P2 | Stage级→Run级→Session级成本累计 | 知道钱花在哪里 |
| 2.2.3 | 流式事件观测 | P1+P2 | EventEmitter改为AsyncGenerator/callback | 实时观测→实时干预 |
| 2.2.4 | 成本超限自动响应 | P2 | 成本超预算→触发Gate B或自动降级模型 | 防止成本失控 |

#### 讨论状态：`待讨论`

---

### 2.3 任务控制

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| 预算执行 | CTS Budget(branch/action计数) | **Token Budget**：90%阈值+递减检测(delta<500×3轮=停止) | Processor threshold触发 |
| 模型降级 | 无 | **Fallback chain**：streaming失败→fallback model→非流式重试 | 无 |
| 递减检测 | 无 | continuationCount≥3 AND lastDelta<500 AND delta<500 → 自动停止 | 无 |
| 任务取消 | cancel_run通过kernel | AbortController+sibling abort(Bash失败取消同级) | 无 |

#### claude-code的递减检测机制（关键参考）

```
Token Budget执行逻辑：
  
  每轮迭代后检查：
  1. 如果 turnTokens < budget × 90% → 继续（重新查询累积上下文）
  2. 如果 连续3轮 且 每轮delta < 500 tokens → 停止（递减回报）
  3. 否则 → 停止
  
  这个机制的精妙之处：
  - 不是硬停，而是检测"还在产出有价值内容吗？"
  - 防止模型在低效循环中浪费token（P2直接受益）
  - budget continuation message会提示模型"你还有X%预算"
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 2.3.1 | Token级预算 | P2 | 不只计action数，追踪实际token消耗并执行预算 | 预算执行精度从"次数"提升到"token" |
| 2.3.2 | 模型降级链 | P2 | Opus超预算→Sonnet→Haiku，per-Stage可配 | 成本弹性控制 |
| 2.3.3 | 递减检测 | P2 | 连续N轮低产出自动停止当前Stage | 防止低效循环浪费token |
| 2.3.4 | 预算续传 | P2 | 参考claude-code的taskBudgetRemaining，压缩后更新剩余预算 | 压缩不会"欺骗"预算计数 |

#### 讨论状态：`待讨论`

---

## 三、模型驱动管理

### 3.1 模型选择与路由

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| 选择策略 | TraceConfig.default_model(全局固定) | **4级优先级链**：session→启动参数→配置→默认 | per-operator配置 |
| 任务级路由 | 无 | 无（有fast/standard speed切换） | 无 |
| Stage级路由 | 无 | 无 | 无 |
| Provider路由 | ModelRouter(前缀匹配) | 单provider(Anthropic) | 多provider(OpenAI/DashScope/自定义) |

#### 这是hi-agent最大的创新机会

**所有框架都没有做Stage级模型路由。** TRACE的5-Stage流水线天然支持这个：

```
S1 Understand（理解任务）→ 用便宜模型(Haiku)，因为只需要理解指令
S2 Gather（收集信息）    → 用便宜模型(Haiku/Sonnet)，大量工具调用不需要强推理
S3 Build/Analyze（核心工作）→ 用最强模型(Opus)，这是产出质量的关键
S4 Synthesize（综合）     → 用中等模型(Sonnet)，组织已有信息
S5 Review（审查）         → 用便宜模型(Haiku)，检查格式和明显错误

成本对比（假设每Stage等量token）：
  全程Opus：  100% × 5 = 500% 成本单位
  分级路由：  20% + 20% + 100% + 40% + 20% = 200% 成本单位
  节省：      60%
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 3.1.1 | Stage级模型路由 | P2 | 每个Stage配置model_tier(cheap/medium/strong)，RouteEngine自动选择 | 成本降50-60% |
| 3.1.2 | 任务复杂度分级 | P2 | 根据task_family和goal复杂度自动选择模型配置 | 简单任务全程用便宜模型 |
| 3.1.3 | 动态降级 | P2 | Stage执行中如果模型输出质量足够，自动降到更便宜的模型 | 按需升级而非默认最贵 |
| 3.1.4 | Speed模式 | P2 | 参考claude-code的fast/standard切换，提供速度-成本权衡 | 用户可选成本档位 |

#### 讨论状态：`待讨论`

---

### 3.2 成本追踪与优化

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| Token计数 | LLMBudgetTracker(调用数+总token) | **5维计数**：input/output/cache_read/cache_creation/web_search | Operator级 |
| USD成本 | 无 | per-model定价表×用量=精确USD | 无 |
| 会话累计 | 无 | per-session持久化+项目级存储+OTel export | 无 |
| Cache利用 | 无 | **追踪cache_read比例**，cache_read成本仅为input的10% | 无 |

#### Prompt Caching的巨大价值（P2的最高ROI）

```
Anthropic Prompt Caching 定价：
  普通input:       $15/M tokens
  cache_creation:  $18.75/M tokens (首次缓存，贵25%)
  cache_read:      $1.5/M tokens  (后续复用，便宜90%!)

这意味着：
  如果系统prompt(~2000 tokens)被缓存后复用100次：
    无缓存：100 × 2000 × $15/M = $3.00
    有缓存：1 × 2000 × $18.75/M + 99 × 2000 × $1.5/M = $0.0375 + $0.297 = $0.33
    节省：  89%

  策略：将系统prompt + CTS定义 + Skill描述放在消息最前面（cacheable prefix）
  每次Stage的Task View前缀尽量不变 → 命中cache
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 3.2.1 | CostTracker模块 | P2 | per-model定价×5维用量=精确USD，Stage级+Run级聚合 | 成本可见 |
| 3.2.2 | Prompt Caching策略 | P2 | Task View的前缀部分（系统prompt+CTS+Skill）设计为稳定可缓存 | input成本降80-90% |
| 3.2.3 | Cache命中率追踪 | P2 | 追踪cache_read/input比例，低命中率时自动优化prompt结构 | 持续优化缓存效率 |
| 3.2.4 | 成本预测 | P2 | 根据task_family历史成本预测新任务成本，超预算前预警 | 成本可预期 |

#### 讨论状态：`待讨论`

---

### 3.3 Prompt工程

#### 现状

| 维度 | hi-agent | claude-code | agent-core |
|------|----------|------------|------------|
| Prompt模板 | route_engine/llm_prompts.py(静态) | 动态system prompt组装(多section拼接) | PromptTemplate(变量替换)+PromptBuilder(自动生成) |
| Prompt优化 | 无 | microcompact(API原生压缩) | **Operator Tunables**：暴露prompt参数，自动优化 |
| Prompt缓存 | 无 | 追踪cache_creation/cache_read | 无 |
| Prompt版本 | 无 | 无 | 无 |

#### agent-core的Prompt Tunables模式（关键参考）

```python
# 每个Operator的prompt可以被"调优"：
class LLMCallOperator:
    # freeze_system_prompt=False → 允许Evolve优化这个prompt
    # freeze_user_prompt=True → 用户prompt不可变
    
    def get_tunables(self):
        return {
            "system_prompt": TunableSpec(kind="prompt"),
            # Evolve可以迭代优化system_prompt：
            # 1. 原始prompt → 执行 → 评估质量
            # 2. 优化prompt → 执行 → 评估质量
            # 3. 选择更好的版本
            # 结果：更短、更精准的prompt（P1+P2双赢）
        }
```

#### 进化方向

| # | 改进项 | 服务原理 | 具体方案 | 预估收益 |
|---|--------|---------|---------|---------|
| 3.3.1 | Prompt Tunables | P1+P2 | 每个Stage/Skill的system prompt暴露为可调参数 | prompt持续变短变精准 |
| 3.3.2 | Prompt版本管理 | P1 | prompt变更追踪，可回退到上一版本 | 安全的prompt进化 |
| 3.3.3 | Prompt A/B测试 | P1 | Champion/Challenger模式对比prompt版本效果 | 数据驱动的优化 |
| 3.3.4 | 动态Prompt组装 | P2 | 根据任务复杂度动态增减prompt section | 简单任务用短prompt |

#### 讨论状态：`待讨论`

---

## 综合优先级排序

按 **P2（降成本）ROI** 从高到低排序：

| 优先级 | 模块.改进项 | 原理 | 预估成本收益 | 实现难度 |
|--------|------------|------|------------|---------|
| **1** | 3.1.1 Stage级模型路由 | P2 | 成本降50-60% | 中（需要per-stage config） |
| **2** | 3.2.2 Prompt Caching策略 | P2 | input成本降80-90% | 低（调整Task View结构） |
| **3** | 1.1.1 三层递进压缩 | P2 | token消耗降30-40% | 中（增加2个Processor） |
| **4** | 2.2.1 CostTracker模块 | P2 | 可见→可优化（基础设施） | 低（定价表+计算） |
| **5** | 2.3.2 模型降级链 | P2 | 超预算自动降级 | 低（fallback逻辑） |
| **6** | 2.3.3 递减检测 | P2 | 防止低效循环 | 低（delta检测） |
| **7** | 1.4.1 Skill Prompt Tunables | P1+P2 | prompt持续优化 | 中（Tunables框架） |
| **8** | 1.3.1 向量化知识检索 | P1+P2 | 精准检索减token | 高（需要向量库） |
| **9** | 2.1.1 异步任务通知 | P2 | 并行效率提升 | 中（通信协议） |
| **10** | 1.2.1 语义向量检索 | P1 | 跨Run学习精准度 | 高（需要embedding） |

---

## 附录：参考实现索引

### claude-code-rev关键文件

| 文件 | 关键机制 |
|------|---------|
| `src/services/compact/autoCompact.ts` | 三层递进压缩：阈值计算、熔断器、回退链 |
| `src/query.ts:401-543` | 每轮query loop的压缩触发逻辑 |
| `src/utils/modelCost.ts` | per-model定价表 + USD成本计算 |
| `src/services/cost-tracker.ts` | 5维token追踪 + 会话累计 + OTel导出 |
| `src/query/tokenBudget.ts` | Token预算执行：90%阈值 + 递减检测 |
| `src/utils/model/model.ts` | 4级模型选择优先级链 |
| `src/coordinator/coordinatorMode.ts` | task-notification协议 + Worker工具约束 |
| `src/memdir/memdir.ts` | 持久化记忆：200行上限 + 25KB cap |
| `src/Task.ts` | 7种任务类型 + 5种状态 + terminal检测 |

### agent_research关键参考

| 框架 | 关键模式 |
|------|---------|
| agent-core ContextEngine | 处理器链：on_add(入库) + on_get(取用)双时机 |
| agent-core MessageOffloader | Token阈值触发截断：tokens_threshold + keep_last_round |
| agent-core DialogueCompressor | LLM摘要压缩：compression_token_limit |
| agent-core Operator Tunables | 可调参数暴露：freeze_* + get_tunables() |
| agent-core AgentRL | 强化学习技能优化：轨迹学习 + 效果评估 |
| LangGraph Checkpoint | 状态快照：InMemory/Postgres + 时间旅行 |
| Agno SessionSummary | 定期会话摘要：LLM生成summary+topics |
