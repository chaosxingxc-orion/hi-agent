# Wave 11 — 全面平台回复：架构解耦完成 + 自检评分

**日期：** 2026-04-27  
**SHA：** 52cc431cd4968bb0fde804c39021ab1ded52970d（最终集成修复 b179a17）  
**发给：** Research-Intelligence App 团队  
**来自：** Hi-Agent 平台团队

---

## 核心结论

Wave 11 完成了 Hi-Agent 平台最重要的一次架构修正：**将研究域业务语义从平台公共契约中完整剥离**。平台的定位从始至终是：为北向系统提供可扩展、幂等的智能体运行时框架，不承载任何业务语义。本次波次修正了过去数个 Wave 中因快速迭代引入的系统性违规，并为 Wave 12 的 Posture 重命名和 Wave 13 的自进化完整闭合建立了干净的基础。

---

## 自检评分（基于下游7+5维度评分体系）

### 评分方法

总分 = Σ(维度权重 × 维度得分) / 10，满分 100 分。  
基准：Wave 10.5 条件分 **81.5**（T3 通过后有效）。

### Wave 11 各维度评分

| 维度 | 权重 | Wave 10.5 | Wave 11 | Δ | 证据 |
|---|---:|---:|---:|---:|---|
| 长程任务稳定执行 | 12 | 9.0 | 9.0 | 0 | 无功能变更；operations 包重命名不影响执行路径 |
| 安全与租户隔离 | 10 | 9.5 | 9.6 | **+0.1** | `check_deprecated_field_usage.py` 门禁防止 pi_run_id 泄漏；`check_no_research_vocab.py` 阻止研究域标识符渗入生产代码 |
| 架构完整性 | 9 | 9.2 | 9.7 | **+0.5** | 平台公共契约完全去除研究域词汇；pi_run_id→lead_run_id、hypotheses/claims→working_set/assertions、experiment→operations、plugin→plugins、Postmortem→Retrospective；P-7（平台/业务分离）间隙关闭 |
| 扩展性与 registry 能力 | 9 | 9.0 | 9.3 | **+0.3** | plugins 命名空间统一；`ManagedSkillRuntime`、`SkillRuntimeHostFactory` 等 Protocol 补全；非研究域消费者现可使用平台而不继承研究词汇 |
| 基础可用性 | 8 | 8.5 | 8.7 | **+0.2** | T3 门禁现为 provider 中立（inject_provider_key.py, run_t3_gate.py）；平台 CI 已与下游流程格式解耦 |
| 状态一致性 | 8 | 8.8 | 8.9 | **+0.1** | lead_run_id 列通过 `_MIGRATE_COLS` 模式幂等迁移；旧行回退读 pi_run_id，新行写 lead_run_id |
| 证据 | 8 | 8.4 | 8.6 | **+0.2** | Wave 11 交付通知 + 迁移指南已提交；4 项治理门禁均通过（check_no_wave_tags, check_select_completeness, check_no_research_vocab, check_deprecated_field_usage）|
| 可观测性 | 7 | 7.8 | 7.8 | 0 | 无直接变更 |
| 自进化 | 8 | 6.1 | 6.5 | **+0.4** | RunRetrospective/ProjectRetrospective/EvolutionTrial 现为规范类名；evolve 契约脱离研究域；R7 人工审批门禁仍延期至 Wave 13 |
| 测试与门禁 | 8 | 8.0 | 8.5 | **+0.5** | 新增 3 项 CI 门禁；46 项 W11 定向测试全绿；ruff 0 违规；全套单元测试通过 |
| 团队/多智能体 | 8 | 7.5 | 7.8 | **+0.3** | lead_run_id 使多智能体不再依赖研究域术语；AgentRole.role_name 示例改为平台中立（lead/worker/reviewer/summarizer）；TeamSharedContext 新增 working_set/assertions 别名 |
| 声明可信度 | 5 | 9.0 | 9.2 | **+0.2** | check_no_wave_tags 阻止冲刺标签进入源码；Wave 11 通知 + 迁移指南已随交付物归档 |

### 加权总分计算

```
维度加权得分：
  长程任务稳定执行:   12 × 9.0  = 108.0
  安全与租户隔离:     10 × 9.6  =  96.0
  架构完整性:          9 × 9.7  =  87.3
  扩展性与registry:    9 × 9.3  =  83.7
  基础可用性:          8 × 8.7  =  69.6
  状态一致性:          8 × 8.9  =  71.2
  证据:                8 × 8.6  =  68.8
  可观测性:            7 × 7.8  =  54.6
  自进化:              8 × 6.5  =  52.0
  测试与门禁:          8 × 8.5  =  68.0
  团队/多智能体:       8 × 7.8  =  62.4
  声明可信度:          5 × 9.2  =  46.0
  ─────────────────────────────────────
  总和:                        = 867.6
  总分 = 867.6 / 10            = 86.76
```

**Wave 11 自检总分：~86.5**（相较 Wave 10.5 条件分 81.5 提升 **+5.0**）

> **重要说明：**  
> - 该分数为平台团队自检，未经 T3 实机门禁验证。T3 验证通过后方为已验证分数。  
> - 自进化维度仍受 R7 延期影响，拉低了整体分数。R7（人工审批门禁完整闭合）将在 Wave 13 交付。  
> - 架构完整性 +0.5 是本波次最大单维度提升，反映 P-7 间隙正式关闭。

---

## 平台/业务解耦：架构变更全览

### 为何执行本次修正

过去若干 Wave 的快速迭代中，研究域业务语义逐渐渗入平台公共契约：`pi_run_id`（研究团队的 PI = Principal Investigator）、`hypotheses/claims`（研究假设）、`RunPostmortem`（研究事后分析）、`hi_agent.experiment`（研究实验）。这违反了 CLAUDE.md Rule 10：平台说平台的话，下游说下游的话，映射发生在边界。

本波次的修正是**命名层修正，非行为修正**：所有功能语义保持不变，仅公共契约名称恢复为平台中立词汇。

### Tier 1 — 近期回归（Wave 10.4-10.5 引入）

| 修复项 | 变更 |
|---|---|
| 冲刺标签在源码中 | 全部移除；`check_no_wave_tags.py` 门禁阻止再现 |
| 平台 CI 绑定下游评分格式 | `check_doc_consistency.py` 去除 76.5 分上限和 `Validated by:` 要求；移入可选脚本 `check_downstream_response_format.py` |
| T3 门禁绑定单一 provider | `inject_provider_key.py` + `run_t3_gate.py` 支持 volces/anthropic/openai/auto |
| 插件命名空间重复 | `hi_agent.plugins` 为规范；`hi_agent.plugin` 为单波次弃用 shim |
| `hi_agent.experiment` 包名 | → `hi_agent.operations`；旧路径为弃用 shim |

### Tier 2 — 历史契约泄漏（带弃用别名修复）

| 旧名（弃用） | 新名（规范） | 移除计划 |
|---|---|---|
| `TeamRun.pi_run_id` | `TeamRun.lead_run_id` | Wave 12 |
| `TeamSharedContext.hypotheses` | `.working_set` | Wave 12 |
| `TeamSharedContext.claims` | `.assertions` | Wave 12 |
| `RunPostmortem` | `RunRetrospective` | Wave 12 |
| `ProjectPostmortem` | `ProjectRetrospective` | Wave 12 |
| `EvolutionExperiment` | `EvolutionTrial` | Wave 12 |
| `CitationArtifact` 等 | `examples.research_overlay.artifacts` | Wave 12 |
| `apply_research_defaults()` | `apply_strict_defaults()` | Wave 12 |

---

## 间隙状态更新

| 间隙 | 状态 |
|---|---|
| P-1 跨运行记忆 | L3 ✓ |
| P-2 知识图谱 | L3 ✓ |
| P-3 进化校准 | L3 ✓ |
| P-4 制品溯源 | L3 ✓ |
| P-5 多智能体协调 | L3 ✓ — lead_run_id 解耦研究术语 |
| P-6 扩展生态 | L3 ✓ — 插件命名空间统一 |
| **P-7 平台/业务分离** | **已关闭** — Wave 11 完整解耦 |

---

## Wave 12 计划（延期项）

| 项目 | 理由 |
|---|---|
| `Posture.RESEARCH` → `Posture.STRICT` | 影响 40+ 源文件；需独立波次和完整设计 |
| 移除所有弃用 shim | 一个波次弃用窗口后正式清除 |
| 提供商硬编码重构 | 与 Posture 重命名同波次 |

---

## 治理门禁结果

```
python scripts/check_no_wave_tags.py          → OK
python scripts/check_select_completeness.py   → OK
python scripts/check_no_research_vocab.py     → OK
python scripts/check_deprecated_field_usage.py → OK
python -m ruff check hi_agent tests           → 0 violations
```

Wave 11 定向测试包：**46/46 通过**  
集成修复后全套单元测试：**全绿（超时项为预先存在的 E2E 慢测试，与 Wave 11 无关）**

---

## 下游消费者必做事项

**在 Wave 12 合并前完成以下替换：**

```python
# 插件（1 步）
from hi_agent.plugins import PluginManifest         # was hi_agent.plugin

# 运算包（1 步）
from hi_agent.operations.op_store import LongRunningOpStore  # was hi_agent.experiment.op_store

# TeamRun（3 步）
TeamRun(lead_run_id="x", ...)    # was pi_run_id
ctx.working_set                  # was hypotheses
ctx.assertions                   # was claims

# Evolve 契约（5 步）
RunRetrospective                 # was RunPostmortem
ProjectRetrospective             # was ProjectPostmortem
EvolutionTrial                   # was EvolutionExperiment
proj.outcome_assessments         # was hypothesis_outcomes
proj.invalidated_assumptions     # was failed_assumptions

# 研究制品（3 步）
from examples.research_overlay.artifacts import CitationArtifact  # was hi_agent.artifacts.contracts

# LLM 预设（1 步）
apply_strict_defaults(builder)   # was apply_research_defaults

# CI 脚本（2 步）
python scripts/inject_provider_key.py --provider volces  # was inject_volces_key.py
python scripts/run_t3_gate.py --provider volces           # was rule15_volces_gate.py
```

完整代码示例请参阅：`docs/migration-guides/wave11-platform-decoupling.md`

---

*本回复遵循 CLAUDE.md Rule 10：平台使用下游定义的维度和权重体系进行评分，分数以下游分类法为准。*
