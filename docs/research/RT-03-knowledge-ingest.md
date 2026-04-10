# RT-03: KnowledgeWiki ingest 实际效果

> 优先级：P1
> 预计时间：5-7 天
> 前置依赖：RT-01（需要 Run 数据作为 ingest 输入）
> 负责人：待分配
> 状态：TODO

## 1. 核心问题

§26 设计了 KnowledgeWiki——Run 完成后用 2-3 次 LLM 调用将发现编译为互相链接的知识页面。但从未验证过核心假设：LLM 能否从 Run 结果中提取有价值的、可复用的、非平庸的知识？

**必须回答的问题：**
- Q1: ingest 提取的 concept/procedure/entity/lesson 是否有实际价值（vs 泛泛之谈）？
- Q2: 知识去重（embedding 相似度 > 0.85 合并）的 false positive/negative 率是多少？
- Q3: wiki 模式检索（IndexPage → page 展开）vs flat embedding search，哪个质量更高？
- Q4: 不同 task_family 的 ingest 成本/收益比差异多大？ingest_policy 的边界在哪？

## 2. 背景

### 当前实现
- 无 KnowledgeWiki 代码。agent-core 有 LongTermMemory（episodic + semantic），但未对接 TRACE 的知识编译模型。

### 架构要求（§26 V2.7）
```
KnowledgePage: { page_id, page_type, title, content(≤1024t), links, confidence, status }
IndexPage: { ≤512 tokens 的分类目录 }
ingest: 概念提取 → 页面匹配更新 → 链接发现 → 索引重建
query: 加载 IndexPage → 匹配 page_ids → 沿 links 展开
lint: 矛盾检测 + 孤立页面 + 过期页面
```

## 3. 实验设计

### 实验 3.1: ingest 提取质量

**目标：** 验证 ingest 能否从 Run 结果中提取有价值的知识。

**方法：**

Step 1 — 构造 5 个已完成 Run 的 L1 summaries（来自同一 task_family "tech_research"）：
```
Run A: 研究 "LLM 幻觉检测方法"
  L1 summaries: [S2 的 findings 包含 3 种检测方法, S3 的 analysis 比较了各方法优劣]

Run B: 研究 "RAG 系统评估指标"
  L1 summaries: [S2 发现 5 种评估维度, S3 发现 faithfulness 和 relevance 经常矛盾]

Run C: 研究 "Agent 安全性最佳实践"
  L1 summaries: [S2 收集了 OWASP LLM Top 10, S3 整理了企业落地清单]

Run D: 研究 "LLM 微调 vs 提示工程"
  L1 summaries: [S2 对比了成本和效果, S3 得出结论：<1000 样本用提示工程]

Run E: 研究 "向量数据库选型"
  L1 summaries: [S2 测试了 Pinecone/Weaviate/Qdrant, S3 发现 Qdrant 在小规模数据上最快]
```

Step 2 — 对每个 Run 调用 ingest prompt：
```
"""
从以下任务执行记录中提取可复用的知识：

## 执行记录
{l1_summaries}

## 提取类型
- concept: 领域概念的定义和解释
- procedure: 执行某类操作的步骤和最佳实践
- entity: 具体实体（工具、API、组织）
- lesson: 从成功或失败中提炼的教训

## 输出（JSON 数组）
[
  {
    "type": "concept|procedure|entity|lesson",
    "title": "≤50 tokens 的标题",
    "content": "≤200 tokens 的内容",
    "related_to": ["可能相关的已有概念标题"]
  },
  ...
]
"""
```

Step 3 — 人工评估每个提取结果：
```
评分标准（每条知识）：
  valuable:    该知识在未来的 Run 中确实有用（如"<1000 样本用提示工程"是有价值的 lesson）
  trivial:     泛泛之谈，没有特定领域信息（如"要做好调研再得出结论"）
  wrong:       事实错误或严重过时
  duplicate:   与该 Run 中其他提取结果重复

aggregation:
  value_rate = count(valuable) / total_extracted
  trivial_rate = count(trivial) / total_extracted
```

**验收条件：**
- value_rate ≥ 60%（至少 60% 的提取结果有实际价值）
- trivial_rate ≤ 30%
- wrong_rate ≤ 5%
- 若 value_rate < 40%：ingest 不值得做，应改为 human_guided knowledge 手动录入

### 实验 3.2: 知识去重质量

**目标：** 验证 embedding 相似度 0.85 的去重阈值是否合理。

**方法：**
```
1. 对 5 个 Run 依次执行 ingest（每个 Run 产出 3-8 条知识）
2. 第 2-5 个 Run ingest 时，与已有知识做 embedding 相似度比较
3. 对每个 similarity > 0.85 的配对，人工判断是否应该合并：
   - true_positive:  相似度 > 0.85 且确实应该合并
   - false_positive: 相似度 > 0.85 但不应合并（不同概念被误合并）
   - false_negative: 相似度 < 0.85 但应该合并（同一概念的不同表述被遗漏）

4. 测试不同阈值的效果：0.75 / 0.80 / 0.85 / 0.90 / 0.95
```

**预期输出：**

| 阈值 | true_positive | false_positive | false_negative | F1 |
|------|--------------|---------------|---------------|-----|
| 0.75 | ? | ? | ? | ? |
| 0.80 | ? | ? | ? | ? |
| 0.85 | ? | ? | ? | ? |
| 0.90 | ? | ? | ? | ? |

**验收条件：**
- 选定阈值的 F1 ≥ 0.8
- false_positive ≤ 10%（误合并不可接受——导致知识失真）

### 实验 3.3: Wiki 检索 vs Flat Search

**目标：** 验证 KnowledgeWiki 的结构化检索是否比 flat embedding search 质量更高。

**方法：**
```
准备：
  - 5 个 Run ingest 后的 KnowledgeWiki（~20 个 pages + IndexPage + links）
  - 相同知识的 flat embedding index（每个 page 作为一个 document）

测试：
  - 10 个模拟的新 Task goal（如"评估一个新的 RAG 系统"、"选择向量数据库"）
  - 方式 A: wiki query（加载 IndexPage → 匹配 → 沿 links 展开 → ≤ 1024 tokens）
  - 方式 B: flat search（embedding top-5 → 拼接 → ≤ 1024 tokens）

评估（LLM-as-judge + 人工抽检）：
  "以下是两组检索结果用于支持任务决策。哪组更完整、更相关？评分 A/B/Tie"
```

**验收条件：**
- wiki 模式胜率 ≥ 55%（即使微弱优势也值得，因为 wiki 的维护成本已经在 ingest 时支付了）
- 若 wiki 模式胜率 < 45%：wiki 结构不值得，简化为 flat embedding + 自动摘要

### 实验 3.4: ingest 成本/收益模型

**目标：** 确定 ingest_policy 的合理配置。

**方法：**
```
对每个 Run，记录：
  - ingest 的 LLM 调用次数和 token 消耗
  - ingest 产出的 valuable 知识条数
  - Run 本身的 LLM token 消耗

计算：
  ingest_cost_ratio = ingest_tokens / run_total_tokens
  knowledge_yield = valuable_items / ingest_calls

按 task_family 特征分类：
  | 类型 | 典型 Run token | ingest token | ingest_cost_ratio | knowledge_yield |
  |------|--------------|-------------|------------------|----------------|
  | quick_task（30min） | ~5K | ~3K | ~60% | ? |
  | deep_analysis（4h） | ~50K | ~3K | ~6% | ? |
```

**验收条件：**
- deep_analysis: ingest_cost_ratio < 10% 且 knowledge_yield ≥ 2 → 推荐 always
- quick_task: 若 ingest_cost_ratio > 30% 且 knowledge_yield < 1 → 推荐 disabled 或 on_labeled

## 4. 产出物清单

| 产出 | 格式 | 位置 |
|------|------|------|
| ingest prompt 最终版 | Python | `hi_agent/knowledge/ingest_prompts.py` |
| 5 个测试 Run 的 L1 数据集 | JSON | `docs/research/data/rt-03-test-runs/` |
| 知识质量评估报告 | Markdown | `docs/research/data/rt-03-quality.md` |
| 去重阈值校准数据 | CSV | `docs/research/data/rt-03-dedup.csv` |
| Wiki vs Flat Search 对比 | Markdown | `docs/research/data/rt-03-retrieval.md` |
| ingest_policy 推荐配置 | Markdown | `docs/research/data/rt-03-policy.md` |
| KnowledgeWiki prototype | Python | `hi_agent/knowledge/wiki.py` |

## 5. 对架构的反馈（实验完成后填写）

### 验证的假设
- [ ] LLM 能从 Run 结果中提取有价值的知识（value_rate ≥ 60%）
- [ ] embedding 相似度 0.85 的去重 F1 ≥ 0.8
- [ ] wiki 结构检索优于 flat search
- [ ] ingest_policy 的 always/on_success/on_labeled/disabled 边界可量化

### 推翻的假设（如有）
（实验后填写）

### 需要修改架构的地方（如有）
（实验后填写）
