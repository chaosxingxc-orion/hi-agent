# RT-01: LLM-based Route Engine 可行性与成本模型

> 优先级：P0
> 预计时间：3-5 天
> 前置依赖：无
> 负责人：待分配
> 状态：TODO

## 1. 核心问题

当前 Route Engine 只有 rule_engine.py（固定规则映射）。架构 §21 要求 Route Engine 能用 LLM 做路由决策——给定 Task View + 可用 Capability + 轨迹历史，输出 BranchProposal（含 rationale + confidence）。

**必须回答的问题：**
- Q1: LLM 能否在单次调用中输出结构化的 BranchProposal？
- Q2: 每次路由决策的 P99 延迟和 token 成本是多少？
- Q3: LLM 自评的 confidence 与实际 Run 成功率的偏差（calibration error）有多大？
- Q4: MCTS rollout（counterfactual scoring）每次需要多少 token？8 轮 MCTS 的总成本是否可控？

## 2. 背景

### 当前实现（hi-agent/route_engine/）
- `protocol.py`：RouteEngineInput / RouteEngineOutput 接口定义
- `rule_engine.py`：固定映射 stage → action，无 LLM 调用，无 confidence
- `base.py`：基类

### 架构要求（§21.1-21.2）
```
RouteEngineInput:
  task_view:               TaskViewRecord
  current_stage:           Stage
  trajectory_tree:         TrajectoryTree
  cts_budget_remaining:    CTSBudget
  available_capabilities:  [CapabilityDescriptor]
  policy:                  RoutePolicyContent

RouteEngineOutput:
  proposed_branches:       [BranchProposal]
  prune_branches:          [BranchPruneRecord]
  route_rationale:         str
  confidence:              float (0-1)
```

### 约束
- Route Engine 必须是纯函数（ADR-03）：不访问全局状态
- confidence < 0.6 触发 Gate B
- confidence 必须经过校准（§21.2 V2.5）：声称 0.8 → 实际成功率 ≥ 0.7

## 3. 实验设计

### 实验 3.1: 结构化输出能力验证

**目标：** 验证 LLM 能否可靠地输出符合 BranchProposal schema 的 JSON。

**方法：**
```
输入 prompt 模板：

"""
你是一个任务路由引擎。基于以下信息，决定下一步应该做什么。

## 当前状态
- 任务目标：{task_goal}
- 当前阶段：{current_stage}
- 已完成的工作：{trajectory_summary}
- 剩余预算：{cts_budget_remaining}

## 可用能力
{available_capabilities_list}

## 输出要求
返回 JSON，格式如下：
```json
{
  "proposed_branches": [
    {
      "branch_id": "自动生成",
      "rationale": "为什么选择这条路径",
      "action_kind": "要使用的能力类型",
      "estimated_complexity": "low|medium|high",
      "priority": 1
    }
  ],
  "prune_branches": [],
  "route_rationale": "整体决策理由",
  "confidence": 0.0到1.0的浮点数
}
```
只返回 JSON，不要其他内容。
"""
```

**测试用例（最少 20 个）：**

| # | task_goal | current_stage | expected_action_kind | 难度 |
|---|-----------|---------------|---------------------|------|
| 1 | "总结最近的 AI 论文趋势" | S2_gather | web_search | 简单 |
| 2 | "分析竞品的技术架构" | S2_gather | web_search + doc_parse | 中等 |
| 3 | "基于矛盾证据决定路径" | S3_build | 应触发 Gate C 或分支 | 困难 |
| 4 | "预算已用 90%，还在 S2" | S2_gather | 应建议跳到 S4 收敛 | 边界 |
| 5-20 | ... | ... | ... | 混合 |

**度量指标：**
- JSON 解析成功率（目标 ≥ 95%）
- schema 合规率（所有必填字段存在，类型正确）
- action_kind 合理性（人工判断，目标 ≥ 80%）

**所需资源：**
- LLM API（Claude / GPT-4 / 本地模型各测一次对比）
- 20 个测试用例（手动构造）

### 实验 3.2: 延迟与 token 成本基准

**目标：** 测量不同模型、不同 Task View 大小下的路由决策延迟和 token 消耗。

**方法：**
```python
# benchmark_route_engine.py

import time, json
from dataclasses import dataclass

@dataclass
class BenchmarkResult:
    model: str
    task_view_tokens: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    json_parse_success: bool
    confidence: float | None

def benchmark_single(model: str, task_view_tokens: int, prompt: str) -> BenchmarkResult:
    """调用 LLM，测量延迟和 token 消耗。"""
    start = time.monotonic()
    response = call_llm(model, prompt)  # 适配不同 API
    latency = (time.monotonic() - start) * 1000
    
    try:
        parsed = json.loads(response.content)
        confidence = parsed.get("confidence")
        json_ok = True
    except json.JSONDecodeError:
        confidence = None
        json_ok = False
    
    return BenchmarkResult(
        model=model,
        task_view_tokens=task_view_tokens,
        latency_ms=latency,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        json_parse_success=json_ok,
        confidence=confidence,
    )

# 测试矩阵
MODELS = ["claude-sonnet-4-20250514", "gpt-4o", "claude-haiku"]
TASK_VIEW_SIZES = [500, 1000, 2000, 4000]  # tokens

for model in MODELS:
    for tv_size in TASK_VIEW_SIZES:
        results = [benchmark_single(model, tv_size, make_prompt(tv_size)) for _ in range(10)]
        # 输出 P50/P95/P99 延迟、平均 token、JSON 成功率
```

**预期输出表格：**

| 模型 | Task View 大小 | P50 延迟 | P99 延迟 | 平均 input tokens | 平均 output tokens | JSON 成功率 |
|------|---------------|---------|---------|-------------------|--------------------|-----------| 
| claude-sonnet | 500 | ? | ? | ? | ? | ? |
| claude-sonnet | 2000 | ? | ? | ? | ? | ? |
| ... | ... | ... | ... | ... | ... | ... |

**验收条件：**
- P99 延迟 < 5s（否则需要在 CTS 预算中预留更多时间）
- JSON 成功率 ≥ 95%（否则需要 retry 机制或 output parser）

### 实验 3.3: Confidence 校准

**目标：** 测量 LLM 输出的 confidence 与实际路由质量的对齐程度。

**方法：**
```
1. 使用实验 3.1 的 20 个测试用例，每个运行 3 次（收集 confidence 分布）
2. 对每个 case，人工标注"最优路由"作为 ground truth
3. 计算 alignment：
   - 若 LLM 选择了最优路由 → actual_quality = 1.0
   - 若 LLM 选择了次优路由 → actual_quality = 0.5
   - 若 LLM 选择了错误路由 → actual_quality = 0.0
4. 按 confidence 分桶（0-0.3, 0.3-0.6, 0.6-0.8, 0.8-1.0）
5. 每个桶：mean(actual_quality) vs mean(confidence)
6. calibration_error = mean(|confidence - actual_quality|) per bucket
```

**预期输出：**
```
Confidence 桶    | 平均 confidence | 平均 actual_quality | calibration_error
0.0 - 0.3       | 0.2             | ?                   | ?
0.3 - 0.6       | 0.45            | ?                   | ?
0.6 - 0.8       | 0.7             | ?                   | ?
0.8 - 1.0       | 0.9             | ?                   | ?
```

**验收条件：**
- 整体 calibration_error < 0.15（§21.2 的要求）
- 若不满足：需要在实施中加入后校准步骤（如 Platt scaling）

### 实验 3.4: MCTS Rollout 成本评估

**目标：** 评估 MCTS 模式下 counterfactual rollout 的 token 成本是否可控。

**方法：**
```
模拟一个 8 轮 MCTS 循环：
  for cycle in range(8):
    # Selection: 选择一个叶子节点（纯算法，0 token）
    # Expansion: 调用 Route Engine 生成 1-3 个候选（1 次 LLM 调用）
    # Simulation: 对每个候选做 counterfactual scoring
    
    counterfactual_prompt = """
    以下是一个任务执行的历史上下文：
    {task_view}
    
    候选路径：{branch_proposal}
    
    问题：如果执行这条路径，预期结果是什么？评分（-1 到 +1）。
    """
    # 每个候选 1 次 LLM 调用
    
    # Backpropagation: 纯算法，0 token

计算总 token 消耗：
  total = 8 × (1 expansion call + 1-3 simulation calls) = 8-32 次 LLM 调用
  total_tokens = sum(each call's input + output tokens)
```

**预期输出：**

| MCTS 循环数 | Route Engine 调用数 | Rollout 调用数 | 总 token | 总成本 ($) | 总延迟 (s) |
|-------------|--------------------|--------------|---------|-----------|-----------| 
| 4 | 4 | 4-12 | ? | ? | ? |
| 8 | 8 | 8-24 | ? | ? | ? |

**验收条件：**
- 8 轮 MCTS 总 token < max_mcts_simulation_token_budget（默认 4096 per cycle × 8 = 32K）
- 8 轮 MCTS 总延迟 < 60s（否则 quick_task 的 30min 预算不够用）
- 若不满足：建议降低默认 MCTS 循环数或使用更便宜的模型做 rollout

## 4. 产出物清单

| 产出 | 格式 | 位置 |
|------|------|------|
| Route Engine LLM prompt 模板 | Markdown + Python | `hi_agent/route_engine/llm_prompts.py` |
| 延迟/成本基准数据 | CSV + 表格 | `docs/research/data/rt-01-benchmarks.csv` |
| Confidence 校准报告 | Markdown + 图表 | `docs/research/data/rt-01-calibration.md` |
| MCTS 成本评估 | 表格 | `docs/research/data/rt-01-mcts-cost.md` |
| LLM Route Engine prototype | Python | `hi_agent/route_engine/llm_engine.py` |
| 对架构的反馈 | Markdown | 本文件 §5 |

## 5. 对架构的反馈（实验完成后填写）

> 以下在实验完成后更新：

### 验证的假设
- [ ] LLM 能可靠输出结构化 BranchProposal（§21.1）
- [ ] P99 延迟 < 5s（§24.7 性能基线）
- [ ] confidence 校准 calibration_error < 0.15（§21.2）
- [ ] MCTS 8 轮总 token < 32K（§6.3 CTS 预算）

### 推翻的假设（如有）
（实验后填写）

### 需要修改架构的地方（如有）
（实验后填写）
