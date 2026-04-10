# RT-06: Skill 结晶实际可行性

> 优先级：P2
> 预计时间：7-10 天
> 前置依赖：RT-01（LLM Route Engine 跑通）+ RT-03（KnowledgeWiki 积累数据）
> 负责人：待分配
> 状态：TODO

## 1. 核心问题

§10.2 的 skill_extraction 策略声称能"从优质轨迹结晶出可复用 Skill"。这包括三种提取方法：
1. prompt_template 提取：meta-LLM 从成功的 LLM 交互记录中归纳共性模板
2. action_pattern 提取：PrefixSpan 从 Action 序列中挖掘频繁子序列
3. decision_rule 提取：从路由决策记录中归纳条件→动作规则

**必须回答的问题：**
- Q1: meta-LLM 能否从 5-20 条成功 Run 中提取出有用的 PromptTemplateContent？
- Q2: PrefixSpan 在 5-20 条短序列（每条 5-15 个 action）上能找到有意义的模式吗？
- Q3: 提取出的 Skill 注入 Task View 后，Run 成功率是否提升？
- Q4: 最少需要多少条优质 Run 才能产出第一个有效 Skill？

## 2. 实验设计

### 实验 2.1: prompt_template 提取

**目标：** 验证 meta-LLM 能否从成功的 LLM 交互中归纳有用的 prompt 模板。

**方法：**
```
前提：已有 RT-01 产出的 LLM Route Engine，hi-agent 可以跑真实 Run

Step 1: 在同一 task_family（如 "tech_research"）下跑 10 个成功的 Run
  每个 Run 的 S3 Build 阶段会产生 LLM 调用记录（task_view + model_output）

Step 2: 从 10 个 Run 中选出 acceptance_score ≥ 0.9 的 top-5（优质轨迹）

Step 3: 调用 meta-LLM 提取 prompt_template：
  """
  以下是 5 个成功完成同类任务的 LLM 交互记录（仅 S3 Build 阶段）。

  Run 1 - task_view: {...}, model_output: {...}
  Run 2 - task_view: {...}, model_output: {...}
  ...

  请归纳这些交互的共性，生成一个可复用的 PromptTemplateContent：
  {
    "system_instruction": "通用的系统指令",
    "task_framing": "任务框架模板（用 {goal}、{evidence_summary} 等占位符）",
    "few_shot_examples": [{"input_summary": "...", "expected_output": "...", "rationale": "..."}],
    "output_format": "期望输出格式",
    "guard_rails": ["负面约束1", "负面约束2"]
  }
  """

Step 4: 质量评估
  - 将提取的 prompt_template 注入到 5 个新的 Run 的 Task View 中
  - 对比：有模板注入 vs 无模板注入的 model_output 质量（LLM-as-judge）
  - 度量：quality_improvement = mean(with_skill_score - without_skill_score)
```

**验收条件：**
- 提取的 prompt_template 语法正确，所有占位符可解析
- quality_improvement > 0（有正向效果）
- 若 quality_improvement ≤ 0：prompt_template 提取方向不可行，需改为纯人工编写

### 实验 2.2: action_pattern 提取（PrefixSpan）

**目标：** 验证频繁子序列挖掘能否从 Action 序列中发现有意义的模式。

**方法：**
```
Step 1: 从 10 个成功 Run 中提取 S2 Gather 阶段的 action_kind 序列
  例：
    Run 1: [web_search, doc_parse, web_search, summarize]
    Run 2: [web_search, web_search, doc_parse, summarize]
    Run 3: [doc_parse, web_search, summarize, web_search, doc_parse]
    ...

Step 2: 运行 PrefixSpan（使用 prefixspan Python 库）
  from prefixspan import PrefixSpan
  ps = PrefixSpan(sequences)
  frequent = ps.frequent(min_support=3)  # 至少在 3 条序列中出现

Step 3: 评估频繁子序列的有意义性
  - 长度为 1 的子序列（如 [web_search]）不算有意义
  - 长度为 2+ 且 support ≥ 60% 的子序列算有意义
  - 人工判断：提取的模式是否反映了真实的领域最佳实践？

Step 4: 将有意义的模式转化为 ActionPatternContent
  - steps = 频繁子序列中的 action_kind 列表
  - postcondition = 从成功 Run 中提取的后条件（如 "evidence_count >= 3"）
```

**关键变量：** 最少需要多少条 Run 才能提取到稳定的 pattern？

| Run 数量 | 预期频繁子序列数 | 有意义的模式数 | 结论 |
|----------|---------------|-------------|------|
| 5 | ? | ? | ? |
| 10 | ? | ? | ? |
| 20 | ? | ? | ? |

**验收条件：**
- 10 条 Run 能提取到至少 1 个长度 ≥ 2、support ≥ 60% 的有意义模式
- 若 20 条 Run 仍无有意义模式：action_pattern 提取不可行于当前任务类型

### 实验 2.3: Skill 注入 A/B 效果

**目标：** 验证提取出的 Skill 注入后是否真的提升 Run 质量。

**方法：**
```
A/B 设计：
  对照组（10 个 Run）: 不注入任何 Skill
  实验组（10 个 Run）: 注入实验 2.1 提取的 prompt_template + 实验 2.2 提取的 action_pattern

评估维度：
  1. acceptance_criteria_pass_rate: 验收标准通过率
  2. avg_token_per_run: 平均 token 消耗（Skill 应该让 Run 更高效）
  3. avg_stage_duration: 各 Stage 平均耗时

统计显著性：
  因样本量小（10 vs 10），使用 Mann-Whitney U test
  p < 0.1 即认为有显著差异（放宽标准，因为样本少）
```

**验收条件：**
- acceptance_criteria_pass_rate 实验组 ≥ 对照组（至少不下降）
- avg_token_per_run 实验组 ≤ 对照组 × 1.1（token 消耗不超过 10% 增长）
- 若两个条件都不满足：Skill 注入无效，需要重新审视 §8.3 的 Skill 运行时注入方式

## 3. 产出物清单

| 产出 | 格式 | 位置 |
|------|------|------|
| prompt_template 提取 prompt | Python | `hi_agent/evolve/skill_extraction_prompts.py` |
| PrefixSpan 挖掘脚本 | Python | `hi_agent/evolve/action_pattern_miner.py` |
| 10 个 Run 的 action 序列数据 | JSON | `docs/research/data/rt-06-action-sequences/` |
| Skill 注入 A/B 对比数据 | CSV + 统计报告 | `docs/research/data/rt-06-ab-test.md` |
| 最小 Run 数量评估 | Markdown | `docs/research/data/rt-06-min-runs.md` |

## 4. 对架构的反馈（实验完成后填写）

### 验证的假设
- [ ] meta-LLM 可从 5 条优质 Run 中提取有用的 prompt_template
- [ ] PrefixSpan 可从 10 条 Run 中提取有意义的 action_pattern
- [ ] Skill 注入后 Run 质量不下降（至少无负面效果）

### 推翻的假设（如有）
（实验后填写——如果 skill_extraction 不可行，需要记录替代方案）

### 需要修改架构的地方（如有）
（实验后填写）
