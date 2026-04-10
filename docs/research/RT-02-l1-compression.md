# RT-02: 分层记忆 L1 压缩质量与延迟

> 优先级：P0
> 预计时间：3-4 天
> 前置依赖：无
> 负责人：待分配
> 状态：TODO

## 1. 核心问题

§25.3 设计了 L1 Stage 压缩——每个 Stage 完成时用 LLM 将全量 evidence 压缩到 ≤ 2048 tokens 的 StageSummary。这是分层记忆的核心环节：如果 L1 质量差，后续所有 Stage 的 Task View 都基于错误的摘要做决策。

**必须回答的问题：**
- Q1: LLM 压缩后，关键信息的保留率是多少？特别是矛盾证据。
- Q2: L1 压缩的 P99 延迟是多少？能否在 Stage 转移的热路径上异步完成？
- Q3: L1 压缩结果 vs L0 临时裁剪（fallback），哪个让后续 LLM 调用质量更高？
- Q4: 不同 evidence 数量（10 条 vs 50 条）对压缩质量和延迟的影响？

## 2. 背景

### 当前实现
- `hi_agent/memory/l1_compressed.py`：框架存在，压缩逻辑待实装
- `hi_agent/memory/compressor.py`：LLM 压缩调用封装

### 架构要求（§25.3 V2.7+V2.8）
```
L1_compressed 触发：Stage 进入 completed / failed 时
算法：llm_compress(stage_evidence, budget=2048_tokens)
输出：StageSummary { findings, decisions, open_questions, outcome }
模式：异步压缩 + 同步 fallback
矛盾保护：findings 必须包含所有 contradictory evidence 的引用
```

## 3. 实验设计

### 实验 3.1: 压缩 prompt 设计与关键信息保留率

**目标：** 找到最佳压缩 prompt，测量关键信息保留率。

**方法：**

Step 1 — 构造测试数据（10 个 Stage 场景）：
```
每个场景包含：
- stage_name: S2_gather / S3_build 等
- evidence 列表: 10-50 条，每条 100-500 tokens
- 人工标注的"关键信息"标签：
  - critical_finding: 必须保留的发现（每个场景 2-5 条）
  - contradictory_pair: 互相矛盾的证据对（每个场景 0-2 对）
  - decision_made: Stage 内做出的关键决策
  - open_question: 未解决的问题

场景设计：
| # | stage | evidence 数 | critical findings | contradictions | 难度 |
|---|-------|------------|-------------------|---------------|------|
| 1 | S2_gather | 10 | 2 | 0 | 简单 |
| 2 | S2_gather | 30 | 5 | 1 | 中等 |
| 3 | S2_gather | 50 | 5 | 2 | 困难 |
| 4 | S3_build | 15 | 3 | 0 | 简单 |
| 5 | S3_build | 40 | 4 | 2 | 困难（矛盾证据多） |
| 6-10 | 混合 | 10-50 | 2-5 | 0-2 | 混合 |
```

Step 2 — 测试 3 种压缩 prompt 变体：

```
Prompt A（简洁版）：
"""
将以下 Stage 执行记录压缩为摘要，不超过 2048 tokens。
提取：关键发现、决策、未解决问题。
{evidence_list}
"""

Prompt B（结构化版）：
"""
将以下 Stage 执行记录压缩为结构化摘要。

## 输出格式（JSON）
{
  "findings": ["发现1", "发现2", ...],
  "decisions": ["决策1 及理由", ...],
  "open_questions": ["问题1", ...],
  "contradiction_refs": ["evidence_id_1 vs evidence_id_2", ...],
  "outcome": "succeeded|failed"
}

## 约束
- 总长不超过 2048 tokens
- 所有互相矛盾的证据必须在 contradiction_refs 中列出（即使摘要正文省略了细节）
- findings 按重要性降序排列

## 输入
{evidence_list}
"""

Prompt C（分步版）：
"""
Step 1: 列出所有互相矛盾的证据对（必须完整，不可遗漏）
Step 2: 列出最重要的 5 条发现
Step 3: 列出做出的决策及理由
Step 4: 列出未解决的问题
Step 5: 将以上合并为 JSON，不超过 2048 tokens

{evidence_list}
"""
```

Step 3 — 度量：
```python
def evaluate_compression(original_evidence, human_labels, compressed_summary):
    """评估压缩质量。"""
    results = {
        # 关键发现保留率：人工标注的 critical_finding 中有多少出现在 findings 中
        "critical_finding_recall": count_matches(
            human_labels["critical_findings"],
            compressed_summary["findings"]
        ) / len(human_labels["critical_findings"]),
        
        # 矛盾证据保留率：所有矛盾对是否都在 contradiction_refs 中
        "contradiction_recall": count_matches(
            human_labels["contradictory_pairs"],
            compressed_summary.get("contradiction_refs", [])
        ) / max(1, len(human_labels["contradictory_pairs"])),
        
        # 信息密度：有用 token 数 / 总 token 数（人工判断每个 finding 是否有价值）
        "information_density": useful_tokens / total_tokens,
        
        # token 数是否在预算内
        "within_budget": total_tokens <= 2048,
    }
    return results
```

**验收条件：**
- critical_finding_recall ≥ 90%（最多丢失 10% 的关键发现）
- contradiction_recall = 100%（矛盾证据不可丢失——§25.3 V2.8 的硬约束）
- within_budget = 100%

### 实验 3.2: L1 vs L0-fallback 的 Task View 质量对比

**目标：** 当 L1 压缩不可用（异步未完成或失败）时，L0 临时裁剪的质量够用吗？

**方法：**
```
设计：
  - 同一个 Stage 的 evidence，分别用两种方式构建 Task View：
    方式 A: L1 压缩结果（StageSummary）
    方式 B: L0 最近 20 条 evidence 直接截断
  - 两种 Task View 分别输入到下一 Stage 的 Route Engine / LLM 调用
  - 比较输出质量

评估方法：
  - 使用 LLM-as-judge：
    "以下两个 Task View 用于同一个任务的下一步决策。哪个提供了更好的上下文？评分 A/B/Tie"
  - 10 个场景，每个场景 3 次 judge 评估（取多数）

记录：
  | 场景 # | evidence 数 | A(L1) 胜 | B(L0-fallback) 胜 | Tie | L1 token 数 | L0-fallback token 数 |
```

**验收条件：**
- L1 胜率 ≥ 70%（证明压缩有价值，值得异步等待）
- 若 L1 胜率 < 50%：压缩 prompt 需要重新设计，或者 fallback 已经够用（简化架构）

### 实验 3.3: 延迟基准

**目标：** 测量不同 evidence 数量下的 L1 压缩延迟。

**方法：**
```python
# benchmark_l1_compression.py

EVIDENCE_COUNTS = [10, 20, 30, 50]
MODELS = ["claude-sonnet-4-20250514", "claude-haiku"]
PROMPT_VARIANTS = ["A", "B", "C"]  # 实验 3.1 的三种 prompt

for model in MODELS:
    for count in EVIDENCE_COUNTS:
        for prompt_var in PROMPT_VARIANTS:
            evidence = generate_mock_evidence(count)  # 每条 200 tokens
            for _ in range(10):
                start = time.monotonic()
                result = llm_compress(model, prompt_var, evidence)
                latency = (time.monotonic() - start) * 1000
                # 记录 latency, input_tokens, output_tokens, within_budget
```

**预期输出：**

| 模型 | evidence 数 | Prompt 变体 | P50 延迟(ms) | P99 延迟(ms) | 输入 tokens | 输出 tokens |
|------|-----------|------------|-------------|-------------|-----------|-----------|
| sonnet | 10 | B | ? | ? | ? | ? |
| sonnet | 50 | B | ? | ? | ? | ? |
| haiku | 10 | B | ? | ? | ? | ? |
| haiku | 50 | B | ? | ? | ? | ? |

**验收条件：**
- 50 条 evidence 的 P99 延迟 < 10s（异步模式下可接受）
- 10 条 evidence 的 P99 延迟 < 3s
- 若延迟过高：考虑用 haiku 做 L1 压缩（牺牲质量换速度）

### 实验 3.4: 压缩的可重复性

**目标：** 同一组 evidence 压缩两次，结果是否一致（影响 replay 一致性）。

**方法：**
```
- 同一组 evidence，同一 prompt，调用 LLM 两次（temperature=0）
- 比较两次输出的 findings / decisions / contradiction_refs 列表
- 不要求 token 级别一致，但要求语义级别一致：
  - findings 的主题集合相同（允许措辞不同）
  - contradiction_refs 完全相同（引用的 evidence_id 必须一致）
```

**验收条件：**
- contradiction_refs 一致率 = 100%（硬约束）
- findings 主题一致率 ≥ 90%
- 若不满足：L1 压缩结果必须在首次生成后持久化，不允许重新压缩（与 §25.3 的 fallback 逻辑一致）

## 4. 产出物清单

| 产出 | 格式 | 位置 |
|------|------|------|
| 最佳压缩 prompt（A/B/C 选择 + 理由） | Python 常量 | `hi_agent/memory/compress_prompts.py` |
| 10 个测试场景数据集 | JSON | `docs/research/data/rt-02-test-scenarios/` |
| 关键信息保留率数据 | CSV + 表格 | `docs/research/data/rt-02-recall.csv` |
| L1 vs L0-fallback 对比数据 | 表格 | `docs/research/data/rt-02-l1-vs-fallback.md` |
| 延迟基准数据 | CSV + 表格 | `docs/research/data/rt-02-latency.csv` |
| LLM 压缩器 prototype | Python | `hi_agent/memory/compressor.py`（更新） |

## 5. 对架构的反馈（实验完成后填写）

### 验证的假设
- [ ] L1 压缩到 ≤ 2048 tokens 可保留 ≥ 90% 关键信息（§25.3）
- [ ] 矛盾证据保留率 100%（§25.3 V2.8 矛盾保护）
- [ ] 50 条 evidence 的压缩延迟 P99 < 10s（§24.7）
- [ ] L1 压缩比 L0 裁剪提供更好的 Task View（§25.3 设计动机）

### 推翻的假设（如有）
（实验后填写）

### 需要修改架构的地方（如有）
（实验后填写）
