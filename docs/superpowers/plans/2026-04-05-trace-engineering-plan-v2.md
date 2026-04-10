# TRACE 工程实施计划 V2（基于 7 课题研究结论修订）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 TRACE V2.8 架构落地为可运行的 hi-agent 系统，分 4 个阶段交付。

**关键发现驱动的修订（vs 原 V1 计划）：**
- RT-04：hi-agent RuntimeAdapter 只有 3/17 个方法 → **阶段 1 首要任务是扩展适配层**
- RT-01+RT-06：V1 scope 大幅简化 → **规则引擎 + human_guided Skill + flat knowledge search**
- RT-07：Temporal 覆盖超预期 → **多实例自建量减少，不做 owner_id CAS**
- RT-05：agent-core 组件级复用 → **Evaluator/ModelClient/VectorStore 直接用，框架不替代**

**Tech Stack:** Python 3.14 / pytest / ruff / agent-kernel（Temporal substrate）/ openjiuwen（组件复用）/ SQLite（dev）/ PostgreSQL（prod）

---

## 当前实现基线（2026-04-05 扫描结果）

```
hi-agent:   65 源文件 / 52 测试文件 / ~4250 行源码 / ~2950 行测试
agent-kernel: 97 源文件 / 100 测试文件 / 全栈实现（Turn FSM + Event Log + Recovery + Temporal）
agent-core:  150+ 源文件 / 成熟 SDK（LLM + Workflow + Memory + Evolve）
```

### hi-agent 已实现模块

| 模块 | 文件数 | 行数 | 完成度 | 说明 |
|---|---|---|---|---|
| contracts/ | 9 | ~230 | 80% | 核心数据模型在，缺 BranchState/RunState enum |
| trajectory/ | 8 | ~220 | 85% | DAG + greedy + backprop + dead_end + stage_graph |
| route_engine/ | 5 | ~115 | 50% | rule_engine 有，LLM engine 无，acceptance 基础版 |
| memory/ | 5 | ~115 | 40% | L0/L1/L2 框架在，异步压缩/fallback 未实装 |
| events/ | 5 | ~130 | 70% | envelope + emitter + JSONL store + payload 验证 |
| capability/ | 6 | ~250 | 70% | registry + invoker + circuit_breaker + RBAC policy |
| runtime_adapter/ | 9 | ~870 | 35% | **只有 3/17 个 Protocol 方法**；但 KernelAdapter/Backend/Client/Consistency 层丰富 |
| recovery/ | 3 | ~300 | 60% | compensator + orchestrator |
| management/ | 4 | ~465 | 50% | health + shutdown + reconcile_supervisor |
| task_view/ | 3 | ~50 | 30% | builder 框架在，分层读取未实装 |
| state/ | 2 | ~125 | 70% | RunStateSnapshot + 文件持久化 |
| replay/ | 4 | ~245 | 70% | engine + io + verify |
| runner.py | 1 | 485 | 60% | S1→S5 循环在，但与 kernel 真实 API 未对接 |

---

## 阶段 0: 架构文档拆分 + 研究报告归档（1 天）

### EP-0.1: 拆分 ARCHITECTURE.md

将 4070 行单文档拆为概览 + 6 个子规范（trajectory-spec / memory-spec / knowledge-spec / evolve-spec / security-spec / ops-spec），ARCHITECTURE.md 退化为 ~500 行概览。

**已有拆分建议：** ARCHITECTURE.md §V2.8 文档拆分建议。

### EP-0.2: 研究报告更新

将 7 个 RT 课题的结论写入各研究文档的 §5（对架构的反馈），标记已验证/已推翻的假设。

---

## 阶段 1: MVP — 第一个 Run 端到端跑通（3-4 周）

### 里程碑验收标准
```
✓ quick_task family 的 Run 走完 S1→S5（通过真实 agent-kernel，非 MockKernel）
✓ Event Log 完整记录（无 gap）
✓ 所有 ID 确定性可验证（同一 Run 重放两次，ID 一致）
✓ 死路检测工作（所有 Branch 失败时快速触发）
✓ Stage Graph 形式化验证通过（可达性 + 无死锁 + 终态）
```

---

### EP-1.1: 扩展 RuntimeAdapter Protocol（3→17 个方法）🔴 最高优先级

**依据：** RT-04 发现 kernel 已提供 17 个接口，hi-agent 只对接了 3 个。

**修改文件：**
- `hi_agent/runtime_adapter/protocol.py` — 扩展 Protocol 定义
- `hi_agent/runtime_adapter/mock_kernel.py` — 扩展 MockKernel 实现
- `hi_agent/contracts/` — 新增 RunState / BranchState enum

**新增方法（按 RT-04 接口映射表）：**

```python
class RuntimeAdapter(Protocol):
    # --- 已有（3 个）---
    def open_stage(self, run_id: str, stage_id: str, branch_id: str | None = None) -> None: ...
    def mark_stage_state(self, run_id: str, stage_id: str, target: StageState, 
                         failure_code: str | None = None) -> None: ...
    def record_task_view(self, record: TaskViewRecord) -> str: ...
    
    # --- 新增（14 个）---
    def start_run(self, request: StartRunRequest) -> StartRunResponse: ...
    def signal_run(self, request: SignalRunRequest) -> None: ...
    def query_run(self, run_id: str) -> QueryRunResponse: ...
    def query_trace_runtime(self, run_id: str) -> TraceRuntimeView: ...
    def bind_task_view_to_decision(self, task_view_id: str, decision_ref: str) -> None: ...
    def open_branch(self, request: OpenBranchRequest) -> None: ...
    def mark_branch_state(self, request: BranchStateUpdateRequest) -> None: ...
    def open_human_gate(self, request: HumanGateRequest) -> None: ...
    def submit_approval(self, request: ApprovalRequest) -> None: ...
    def cancel_run(self, run_id: str, reason: str) -> None: ...
    def resume_run(self, run_id: str) -> None: ...
    def get_manifest(self) -> KernelManifest: ...
    def stream_run_events(self, run_id: str) -> AsyncIterator[RuntimeEvent]: ...
    def submit_plan(self, plan: ExecutionPlan) -> None: ...
```

**同步修改 MockKernel：**
- 所有新方法的 strict_mode 实现（含状态机验证）
- RunState 七态状态机（§14.1-14.2）
- BranchState 六态（proposed→active→waiting→pruned/succeeded/failed）
- Branch 操作 → TrajectoryNode 映射（§6.2.1 V2.8 澄清）

**新增契约：**

```python
# hi_agent/contracts/run.py
class RunState(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    WAITING = "waiting"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"

# hi_agent/contracts/branch.py  
class BranchState(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    WAITING = "waiting"
    PRUNED = "pruned"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
```

**测试：** 扩展现有测试，覆盖所有新方法的 idempotent 和 illegal transition 场景。

**预计工作量：** 3-4 天

---

### EP-1.2: Runner 重构 — 对接完整 Protocol

**依据：** 当前 runner.py(485 行) 只使用 open_stage / mark_stage_state / record_task_view 三个方法。

**修改文件：**
- `hi_agent/runner.py` — 重构为使用完整 Protocol

**核心变更：**
```
当前流程：                          重构后流程：
for stage in STAGES:                kernel.start_run(request)
  kernel.open_stage(stage)          for stage in STAGES:
  # ... execute ...                   kernel.open_stage(run_id, stage_id)
  kernel.mark_stage_state(...)        kernel.open_branch(branch_request)
                                      # ... execute via capability ...
                                      kernel.mark_branch_state(...)
                                      tv_id = kernel.record_task_view(record)
                                      kernel.bind_task_view_to_decision(tv_id, decision_ref)
                                    kernel.mark_stage_state(run_id, stage, COMPLETED)
```

**同步修改事件发射：**
- 每次 Branch 创建/完成 → 发射 BranchProposed/BranchSucceeded 事件
- 每次 Action 执行 → 发射 ActionDispatched/ActionSucceeded 事件
- 使用 §12.1.1 的 EventEnvelope + payload schema

**预计工作量：** 3-4 天

---

### EP-1.3: L1 异步压缩 + Fallback 实装

**依据：** RT-02 结论——Haiku 为默认，evidence ≥ 25 条时值得压缩。

**修改文件：**
- `hi_agent/memory/compressor.py` — 实装异步 LLM 压缩
- `hi_agent/memory/l1_compressed.py` — 补全 StageSummary 生成逻辑
- 新增 `hi_agent/memory/compress_prompts.py` — 压缩 prompt 模板

**核心设计（来自 RT-02）：**
```python
class MemoryCompressor:
    async def compress_stage(self, stage_id: str, evidence: list[RawEventRecord]) -> StageSummary:
        if len(evidence) < 25:
            # 直接构建，不调用 LLM
            return self._build_summary_from_raw(evidence)
        
        # 异步 LLM 压缩（Haiku 默认）
        try:
            return await asyncio.wait_for(
                self._llm_compress(evidence), timeout=10.0
            )
        except (asyncio.TimeoutError, LLMError):
            # Fallback: L0 最近 20 条裁剪
            return self._fallback_truncate(evidence, max_items=20)
    
    def _llm_compress(self, evidence: list[RawEventRecord]) -> StageSummary:
        # 使用结构化 JSON prompt（RT-02 推荐 Prompt B）
        # 强制要求 contradiction_refs 包含所有矛盾标签
        ...
```

**L0 矛��标签预打标（RT-02 建议）：**
```python
# 在 RawEventRecord 写入时，如果与已有 evidence 矛盾，打标签
class RawMemoryStore:
    def add(self, record: RawEventRecord) -> None:
        record.tags = self._detect_contradictions(record, self.existing)
        self.records.append(record)
```

**预计工作量：** 2-3 天

---

### EP-1.4: Task View 分层构建实装

**依据：** RT-02 确认 L2→L1→L3→Knowledge 分层读取优于 flat evidence 裁剪。

**修改文件：**
- `hi_agent/task_view/builder.py` ��� 重写为分层构建
- `hi_agent/task_view/token_budget.py` — 实装固定 budget 分配

**核心流程（§25.3）：**
```python
def build_task_view(run_index: RunIndex, stage_summaries: dict, episodes: list, 
                    knowledge: list, budget: int = 9728) -> TaskView:
    sections = []
    remaining = budget
    
    # Step 1: L2 index (≤512t, 必加载)
    sections.append(format_run_index(run_index))
    remaining -= token_count(sections[-1])
    
    # Step 2: L1 current stage (≤2048t, 必加载)
    current = stage_summaries.get(run_index.current_stage)
    if current:
        sections.append(format_stage_summary(current))
        remaining -= token_count(sections[-1])
    
    # Step 3: L1 previous stage (≤2048t, 如有余量)
    # Step 4: L3 episodic (≤1024t, 如有余量)
    # Step 5: Knowledge (≤1024t, 如有余量)
    # Step 6: System reserved (512t)
    
    return TaskView(sections=sections, total_tokens=budget - remaining)
```

**预计工作量：** 2 天

---

### EP-1.5: Capability 调用对接 agent-core

**依据：** RT-05 确认——agent-core 工具通过 adapter 注册到 CapabilityRegistry。

**新增文件：**
- `hi_agent/capability/adapters/__init__.py`
- `hi_agent/capability/adapters/core_tool_adapter.py` — agent-core tool → CapabilityDescriptor
- `hi_agent/capability/adapters/descriptor_factory.py` — 自动生成 descriptor（~50% 字段可自动填充）

**核心逻辑（RT-05 §3.4）：**
```python
class CapabilityDescriptorFactory:
    """从 agent-core 的 ToolCard/WorkflowCard 自动生成 CapabilityDescriptor。"""
    
    # 可自动推导的字段：capability_id, capability_kind, name, description, schema_ref
    # 需要 heuristic 推导的：effect_class, side_effect_class（基于命名约定）
    # 需要手动标注的：通过 capability_overrides.yaml 覆盖
    
    EFFECT_HEURISTICS = {
        "read": "read_only", "search": "read_only", "query": "read_only",
        "write": "idempotent_write", "create": "idempotent_write",
        "delete": "irreversible_write", "send": "irreversible_write",
    }
```

**预计工作量：** 2-3 天

---

### EP-1.6: agent-kernel 真实对接（LocalFSM substrate）

**依据：** RT-04 确认 kernel 有 LocalFSMAdaptor（纯 asyncio，不需要 Temporal server）可用于开发阶段。

**修改文件：**
- `hi_agent/runtime_adapter/kernel_adapter.py` — 实装 KernelFacade 调用转发
- 新增 `hi_agent/runtime_adapter/kernel_facade_adapter.py` — EP-1.1 Protocol ↔ KernelFacade 映射

**核心映射（RT-04 §1.1）：**
```python
class KernelFacadeAdapter:
    """将 hi-agent RuntimeAdapter Protocol 映射到 agent-kernel KernelFacade。"""
    
    def __init__(self, facade: KernelFacade):
        self.facade = facade
    
    def open_stage(self, run_id: str, stage_id: str, branch_id: str | None = None) -> None:
        self.facade.open_stage(stage_id=stage_id, run_id=run_id, branch_id=branch_id)
    
    def mark_stage_state(self, run_id: str, stage_id: str, target: StageState, 
                         failure_code: str | None = None) -> None:
        self.facade.mark_stage_state(
            run_id=run_id, stage_id=stage_id,
            target=target.value,  # DTO 转换
            failure_code=failure_code,
        )
    # ... 其余 14 个方法的映射 ...
```

**阶段 1 目标：** 用 LocalFSMAdaptor 跑通端到端。Temporal substrate 推迟到阶段 2。

**预计工作量：** 3-4 天

---

### EP-1.7: Stage Graph 形式化验证

**已实现：** `hi_agent/trajectory/stage_graph.py`(57 行) 有基础验证。

**补全：**
- BFS 可达性检查（从 initial_stage 出发）
- 终态可达检查（每个非终态 Stage 可达某个终态）
- Gate 完整性检查（Gate D 的 approved/rejected 路径都存在）
- CTS 预算合法性（max_active_branches ≤ max_total_branches）

**预计工作量：** 1-2 天

---

### EP-1.8: 阶段 1 集成测试

**修改/新增文件：**
- `tests/integration/test_e2e_kernel_run.py` — 通过 KernelFacadeAdapter + LocalFSM 的端到端 Run
- `tests/integration/test_branch_lifecycle.py` — Branch open/active/succeeded/failed/pruned 全流程
- `tests/integration/test_l1_compression.py` — L1 压缩 + fallback + 矛盾保护
- `tests/integration/test_task_view_layered.py` — 分层 Task View 构建 + token 预算验证
- 更新 `tests/integration/test_deterministic_replay.py` — 用新 Protocol 验证

**预计工作量：** 3-4 天

---

### 阶段 1 工作量汇总

| 任务 | 工作量 | 依赖 |
|---|---|---|
| EP-1.1 扩展 RuntimeAdapter Protocol | 3-4 天 | 无 |
| EP-1.2 Runner 重构 | 3-4 天 | EP-1.1 |
| EP-1.3 L1 异步压缩 | 2-3 天 | 无 |
| EP-1.4 Task View 分层构建 | 2 天 | EP-1.3 |
| EP-1.5 Capability 对接 agent-core | 2-3 天 | 无 |
| EP-1.6 agent-kernel 真实对接 | 3-4 天 | EP-1.1 |
| EP-1.7 Stage Graph 验证补全 | 1-2 天 | 无 |
| EP-1.8 集成测试 | 3-4 天 | EP-1.1~1.7 |
| **总计** | **~20-24 天（3-4 周）** | |

**可并行：** EP-1.1 + EP-1.3 + EP-1.5 + EP-1.7 四项无依赖可同时开始。

---

## 阶段 2: 生产就绪 — 安全 + 可观测 + Inline Evolution（3-4 周）

### 里程碑验收标准
```
✓ mTLS + JWT 认证链路跑通（RBAC 端到端 enforce）
✓ 核心指标（run_success_rate + avg_token_per_run + 7 个 V2.8 新指标）可采集
��� Inline Evolution 自动触发（L3 episodic 生成 + knowledge ingest）
✓ Human Gate 审批 API 可用（Gate A-D 四种类型）
✓ 多实例环境可运行（LocalFSM → Temporal substrate 切换）
```

---

### EP-2.1: 安全 — RBAC 执行层

**新增文件：**
- `hi_agent/auth/jwt_middleware.py` — JWT 验证（aud="hi-agent"）
- `hi_agent/auth/rbac_enforcer.py` �� 操作→角色映射 enforce
- `hi_agent/auth/soc_guard.py` — SoC defense-in-depth（submitter ≠ approver 硬校验）

**预计工作量：** 3-4 天

### EP-2.2: Human Gate 审批 API

**依据：** RT-04 确认 kernel 已完整支持 HumanGateRequest + ApprovalRequest + Signal wait。

**新增文件：**
- `hi_agent/management/gate_api.py` — POST /management/gates/{gate_ref}/resolve
- `hi_agent/management/gate_context.py` — GateContext 构建（§32.1）
- `hi_agent/management/gate_timeout.py` — 超时自动处理（§32.3）

**预计工作量：** 3-4 天

### EP-2.3: 可观测 — 核心指标 + 追踪

**新增文件：**
- `hi_agent/observability/metrics.py` — run_success_rate, avg_token_per_run, propagated_score 等
- `hi_agent/observability/tracing.py` — TraceContext 传递 + span 管理
- `hi_agent/observability/notification.py` — NotificationBackend（webhook/slack）

**预计工作量：** 4-5 天

### EP-2.4: Inline Evolution — L3 Episodic + Knowledge Ingest

**依据��** RT-03 结论——V1 用 flat search + tag，不启用 wiki link 遍历。

**新增文件：**
- `hi_agent/memory/l3_episodic.py` — Episode 生成 + embedding 去重（阈值 0.80）
- `hi_agent/knowledge/__init__.py`
- `hi_agent/knowledge/store.py` — flat embedding search + metadata tag（不做 link 遍历）
- `hi_agent/knowledge/ingest.py` — Run 完成后 LLM 概念提取 + 页面匹配
- `hi_agent/knowledge/query.py` — Task View Step 5 的知识检索

**核心简化（vs 架构 §26）：**
```
架构设计：KnowledgeWiki 链接页面网络 + ingest/query/lint
V1 实现：flat embedding search + metadata tag + ingest/query（无 lint，无 link 遍历）
RT-03 依据：<200 页时 link ROI 为负，flat search 够用
```

**ingest_policy 默认配置（RT-03 建议）：**
- deep_analysis → on_success
- quick_task → on_labeled（实际等价于大部分跳过）

**预计工作量：** 5-6 天

### EP-2.5: Temporal Substrate 对接

**依据：** RT-07 确认——Run=Workflow(方案 C)正确，Stage/Branch 是应用层状态。

**修改文件：**
- `hi_agent/runtime_adapter/kernel_facade_adapter.py` — 适配 Temporal 模式
- 新增 `hi_agent/runtime_adapter/temporal_health.py` — TemporalConnectionHealthCheck

**核心：** 从 LocalFSM 切换到 Temporal substrate。大部分逻辑不变（adapter 层屏蔽差异）。主要新增网络分区三态检测。

**预计工作量：** 3-4 天

### EP-2.6: 运行时配置热更新

**新增文件：**
- `hi_agent/management/runtime_config.py` — PATCH /management/runtime-config
- `hi_agent/management/config_history.py` — 版本化 + 历史记录

**预计工作量：** 2 天

### EP-2.7: 阶段 2 集成测试

- `tests/integration/test_auth_flow.py` — JWT + RBAC 端到端
- `tests/integration/test_human_gate.py` — Gate A-D 审批流
- `tests/integration/test_inline_evolution.py` — L3 生成 + ingest 触发
- `tests/integration/test_temporal_run.py` — Temporal substrate 端到端
- `tests/chaos/test_partition.py` — 网络分区降级（Toxiproxy）

**预计工作量：** 4-5 天

### 阶段 2 工作量汇总

| 任务 | 工作量 |
|---|---|
| EP-2.1 RBAC | 3-4 天 |
| EP-2.2 Human Gate API | 3-4 天 |
| EP-2.3 可观测 | 4-5 天 |
| EP-2.4 Inline Evolution | 5-6 天 |
| EP-2.5 Temporal 对接 | 3-4 天 |
| EP-2.6 运行时配置 | 2 天 |
| EP-2.7 集成测试 | 4-5 天 |
| **总计** | **~24-30 天（3-4 周）** |

---

## 阶段 3: 完整功能 — Batch Evolution + Skill + 高级轨迹（4-6 周）

### 里程碑验收标准
```
✓ human_guided EvolveSession 成功完成（手动提交 ChangeSet → route_replay 评估 → 晋升）
✓ parameter_tuning 自动生成候选参数变更并通过 QualityGate
✓ prompt_template Skill 手动创建 → 注入 Task View → Run 成功
✓ A/B 实验流量分配可用（标准路径 + 低频轻量路径）
```

---

### EP-3.1: Batch Evolve — human_guided + parameter_tuning

**新增文件：**
- `hi_agent/evolve/__init__.py`
- `hi_agent/evolve/session.py` — EvolveSession 状态机
- `hi_agent/evolve/changeset.py` — ChangeSet 数据模型
- `hi_agent/evolve/strategies/human_guided.py` — 人工提交 ChangeSet
- `hi_agent/evolve/strategies/parameter_tuning.py` — 统计信号 → 候选参数
- `hi_agent/evolve/evaluation/route_replay.py` — 历史 TaskView 重放评估
- `hi_agent/evolve/quality_gate.py` — QualityGate 数字门

**预计工作量：** 7-8 天

### EP-3.2: Skill 系统 V1

**依据：** RT-06 结论——V1 只做 prompt_template + human_guided。

**新增文件：**
- `hi_agent/skill/__init__.py`
- `hi_agent/skill/registry.py` — SkillRecord CRUD + 版本管理 + retirement 安全门
- `hi_agent/skill/content.py` — SkillContent（仅 prompt_template 类型）
- `hi_agent/skill/injector.py` — Skill → Task View 注入
- `hi_agent/skill/selector.py` — task_family + stage_affinity 匹配

**核心简化（vs 架构 §8.3）：**
```
架构设计：4 种 content_type（prompt_template / action_pattern / decision_rule / composite）
V1 实现：仅 prompt_template
RT-06 依据：PrefixSpan 在小样本无统计意义，decision_rule 最难自动化
```

**预计工作量：** 5-6 天

### EP-3.3: A/B 实�� + 低频路径

**新增文件：**
- `hi_agent/evolve/experiment.py` — ExperimentConfig + 流量分配
- `hi_agent/evolve/strategies/low_frequency.py` — 强化离线评估 + 人工审批（跳过 A/B）

**预计工作量：** 3-4 天

### EP-3.4: LLM Route Engine（V1.5 混合策略）

**依据：** RT-01 结论——规则引擎覆盖 60-70%，LLM 做 fallback。

**新增文件：**
- `hi_agent/route_engine/llm_engine.py` — LLM-based Route Engine
- `hi_agent/route_engine/llm_prompts.py` — 路由 prompt 模板
- `hi_agent/route_engine/hybrid_engine.py` — 规则优先 + LLM fallback

**预计工作量：** 4-5 天

### EP-3.5: EvalDataset + 标注流程

**新增文件：**
- `hi_agent/evolve/eval_dataset.py` — RunSnapshot 管理 + 版本化
- `hi_agent/evolve/labeling.py` — 标注 API（集成 Gate 审批副产品）

**预计工作量：** 3-4 天

### EP-3.6: 阶段 3 集成测试

- `tests/integration/test_evolve_session.py` — human_guided 完整流程
- `tests/integration/test_parameter_tuning.py` — 统计信号 → 候选 → 评估 → 晋升
- `tests/integration/test_skill_injection.py` — Skill 创建 → 注入 → Run 完成
- `tests/integration/test_ab_experiment.py` — 流量分配 + 对照组
- `tests/integration/test_llm_route.py` — 混合路由 + confidence

**预计工作量：** 4-5 天

### 阶段 3 工作量汇总

| 任务 | 工作量 |
|---|---|
| EP-3.1 Batch Evolve | 7-8 天 |
| EP-3.2 Skill V1 | 5-6 天 |
| EP-3.3 A/B + 低频 | 3-4 天 |
| EP-3.4 LLM Route V1.5 | 4-5 天 |
| EP-3.5 EvalDataset | 3-4 天 |
| EP-3.6 集成测试 | 4-5 天 |
| **总计** | **~26-32 天（4-5 周）** |

---

## 阶段 4: 高级功能 — 远期路线图（不在当前工程范围）

以下列出但不估工作量，在阶段 3 完成后再规划：

| 模块 | 内容 |
|---|---|
| **MCTS 优化器** | UCB1 选择 + counterfactual rollout + 成本预算控制 |
| **beam_search 优化器** | top-K 并行路径 + S4 合并 |
| **todo_dag 优化器** | 子目标 DAG 分解 + Phase 1.5 检查点 |
| **KnowledgeWiki link 遍历** | link 发现 + 图遍历检索 + lint 审计 |
| **Skill 进阶** | action_pattern(PrefixSpan) + decision_rule + composite |
| **skill_extraction 自动化** | meta-LLM 提取 + ≥15 条 Run 数据积累 |
| **knowledge_discovery** | 矛盾检测 + 模式泛化 + 知识候选生成 |
| **counterfactual / full_simulation** | 进阶离线评估方法 |
| **confidence 校准** | isotonic regression + 200+ RunSnapshot 校准集 |
| **多租户** | tenant 概念 + 配额 + 数据分区 |
| **成本归因** | CostRecord 采集 + 预算预警 + 实时消耗视图 |

---

## 总时间线

```
Week 0:       阶段 0 — 文档拆分 + 研究归档（1 天）
Week 1-4:     阶段 1 — MVP（RuntimeAdapter 扩展 + Runner 重构 + L1 + TaskView + kernel 对接）
Week 5-8:     阶段 2 — 生产就绪（安全 + 可观测 + Inline Evolution + Temporal + Human Gate）
Week 9-13:    阶段 3 — 完整功能（Batch Evolve + Skill + A/B + LLM Route + EvalDataset）
Week 14+:     阶段 4 — 高级功能（远期路线图）
```

**总计约 13 周（~3 个月）到达阶段 3 完成。**

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| agent-kernel KernelFacade API 与 hi-agent Protocol 语义不匹配 | 中 | 阻塞 EP-1.6 | EP-1.1 先用 MockKernel 验证，EP-1.6 再做真实对接 |
| L1 压缩质量不达标（矛盾证据丢失） | 低 | 认知正确性下降 | RT-02 的 L0 预打标签 + compress prompt 强制要�� |
| LLM Route Engine confidence 校准不足 | 中 | Gate B 误触发/漏触发 | RT-01 建议：初期设 0.7 阈值，规则引擎优先 |
| Temporal LocalFSM → 真实 Temporal 切换困难 | 低 | 阻塞 EP-2.5 | RT-07 确认 adapter 层屏蔽差异，方案 C 正确 |
| agent-core Memory/Evolve 接口对齐成本超预期 | 中 | 延长 EP-2.4 和 EP-3.1 | RT-05 建议：组件级复用，不做框架级替代 |
