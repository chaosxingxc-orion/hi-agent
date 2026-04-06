# TRACE 企业级智能体架构设计 V2.9

> 状态：`V2.9 任务拆解与并行执行版`
>
> 基础：`2026-04-05-trace-architecture-design-v2.0.md` + `2026-04-05-trace-spec-contracts-and-interfaces-v2.0.md`
>
> 演进路径：V2.0→V2.1→V2.2→V2.3→V2.4→V2.5→V2.6→V2.7→V2.8→ **V2.9**
>
> V2.7 核心重构（参考 Karpathy autoresearch + LLM Wiki）：轨迹优化器 / 分层压缩记忆 / KnowledgeWiki / Inline+Batch 双轨进化
>
> V2.8 内聚修复：TrajectoryNode 与 Branch 关系统一 / §18.4→§25.3 权威声明 / L1 异步压缩+fallback / Inline 失败不阻塞 / MCTS 成本预算 / ingest_policy / 轨迹&记忆&知识指标 / Batch Evolve 冻结 wiki 版本 / todo_dag 分解检查点 / 文档拆分建议
>
> V2.9 任务拆解：TaskPlan 一等概念 / Coordinator-Worker 执行模型 / DAG+Tree+Linear 三种拆解结构 / Worker 自闭环（独立 Run+CTS+Memory）/ 子图子树分派 / 级联回退与计划修订 / PlanFeedback 进化集成（§34）
>
> 仓库：
> - `D:\chao_workspace\hi-agent`（本仓库）
> - `D:\chao_workspace\agent-kernel`
> - `D:\chao_workspace\external\agent-core`

---

## 开发者快速入门（V2.4 新增）

### 推荐阅读路径

本文 2000+ 行，完整阅读需数小时。按角色选择入口：

**角色 A：初次了解系统（产品/架构师）**
```
§3（TRACE 核心抽象）→ §5（一等概念）→ §6（CTS）→ §7（职责边界）→ §27（架构总结）
预计阅读时间：30 分钟
```

**角色 B：实现 hi-agent 认知逻辑（hi-agent 工程师）**
```
§3 → §5 → §6 → §7 → §18（Task View）→ §21（Route Engine）→ §22（认知进展检测）→ §11（幂等）→ §8（可扩展）→ §20（实现状态）
然后按 P0/P1/P2 优先级顺序深入对应章节
```

**角色 C：对接 agent-kernel（内核适配层工程师）**
```
§7（职责边界）→ §14（状态机）→ §15（仲裁）→ §13（运维 API）→ §19（身份规约）→ §11（幂等）→ §28（认证）→ §29（通信安全）
```

**角色 D：构建 agent-core Capability（能力模块工程师）**
```
§7（职责边界）→ §8.1（Capability Registry）→ §31（Capability 调用契约）→ §11.4（副作用治理）→ §29（通信安全）
```

**角色 E：运维与 SRE**
```
§13（可运维设计）→ §12（可观测）→ §30（运维 Runbook）→ §28.2（RBAC 执行）→ §13.6（多实例协调）
```

### 最小可运行里程碑（MVP）

完成以下 P0 + 核心 P1 项后，系统可以运行**第一个真实 Run**：

```
阶段 1：Run 骨架（可运行但无 Evolve）
  ✓ P0: action_id + task_view_id 确定性生成算法（§11.1.1, §19.4）
  ✓ P0: query_run() / query_trace_runtime() 稳定实现
  ✓ P1: Capability Registry（含沙箱 none/light，暂不实现 strict）
  ✓ P1: Task Family 配置管理 + 注册校验
  ✓ P1: Event Schema + 事件日志（payload_ref 模式）
  ✓ P1: Route Engine 最小实现（规则引擎，不需要 LLM-based）
  ✓ P1: 健康检查 + 优雅停机
  → 里程碑验收：提交一个 quick_task family 的 Run，能走完 S1→S5 并成功完成

阶段 2：安全与可观测（生产就绪）
  ✓ P0: RBAC 执行层（mTLS + JWT，§28）
  ✓ P1: 多实例协调（心跳 + 孤儿接管）
  ✓ P2: 核心指标埋点（run_success_rate + avg_token_per_run）
  ✓ P2: Secret 管理集成
  → 里程碑验收：能在多实例环境跑通，有基础告警覆盖

阶段 3：进化能力（完整功能）
  ✓ P2: Evolve Pipeline 骨架 + QualityGate
  ✓ P2: Task View 优先级算法（§18.4）
  ✓ P2: 认知进展检测（§22）
  → 里程碑验收：第一个 EvolveSession 成功晋升一个 Skill 版本
```

### 关键架构决策记录（ADR）

#### ADR-01：为什么选择 CTS（受约束轨迹空间）而非 ReAct 式循环

**问题**：企业 agent 需要执行复杂长程任务（数小时级），传统 ReAct 的 Thought→Action→Observation 循环没有形式化的"任务进度"概念，任务状态不可恢复、不可审计。

**考虑过的替代方案**：
- ReAct 循环：简单但没有 checkpoint 语义，崩溃后整个任务重跑
- Plan-and-Execute：计划固化，无法应对探索中的发现（如证据矛盾）
- 树搜索（MCTS）：理论上最优，但计算成本不可控，与企业 SLO 不兼容

**选择 CTS 的原因**：Stage Graph 提供了可版本化的任务推进规则（支持 Evolve 优化），Trajectory Tree 提供了断点恢复的能力，两层结构的职责分离使得"规则演进"和"单次探索"可以独立迭代。

#### ADR-02：为什么 Memory 和 Knowledge 是两个独立概念

**问题**：很多 agent 系统只有一个"记忆"概念，TRACE 将其分为 Memory（经历过什么）和 Knowledge（稳定知道什么）。

**选择原因**：Memory（尤其 Episodic）是观察性的、可能过时的、不应作为高置信决策依据；Knowledge 是经过多次 Run 验证的、有置信度的、可随 Evolve 主动管理的。将两者合并会导致过期的历史记录和稳定知识混用，评估和淘汰策略无法分别设计。Knowledge 有 TTL/revalidation/status 生命周期（§26），Memory 没有。

#### ADR-03：为什么 Route Engine 必须是纯函数（不得访问全局状态）

**问题**：允许 Route Engine 访问全局状态（如 MemoryStore、当前活跃 Run 列表）会让它更"聪明"，为什么禁止？

**选择原因**：
1. **可测试性**：纯函数输入确定则输出可预测，支持 LLM Fixture（§24.2）的 record/replay 测试
2. **可替换性**：Route Engine 实现可以是 LLM-based 或规则引擎，统一接口（§21.1）只有在纯函数约束下才能保证替换透明
3. **Evolve 可评估性**：两个 Route Engine 实现的质量对比需要在相同输入下得到可比较的输出；允许访问全局状态会使实验组和对照组的行为差异不可分解

#### ADR-04：为什么 agent-kernel 不做业务 RBAC（只做 mTLS 认证）

**问题**：让 agent-kernel 也做业务角色检查会更安全，为什么只在 hi-agent 层做？

**选择原因**：业务角色（`gate_approver` / `evolve_manager`）的语义绑定到 TRACE 的业务概念（Gate 类型、task_family、EvolveSession），这些概念 agent-kernel 不知道（职责边界 §7）。若在 kernel 层做业务 RBAC，要么 kernel 必须理解 TRACE 语义（破坏边界），要么做不了细粒度控制。mTLS 保证"调用者是合法的 hi-agent 实例"已经足够——业务角色控制属于 hi-agent 的认知层职责。

### 文档拆分建议（V2.8 新增）

本文已达 4000+ 行，超过单文档的有效承载能力。实现阶段建议拆分为以下子规范，本文退化为**概览 + 索引**：

| 子规范 | 包含章��� | 独立交付的条件 |
|---|---|---|
| `trajectory-spec.md` | §6（CTS + TrajectoryNode + 优化器）+ §14（状态机）+ §22（认知进展检测） | Route Engine 开发团队可独立参考 |
| `memory-spec.md` | §25.3（分层压缩）+ §18（Task View）+ L0/L1/L2/L3 全部细节 | Task View 开发者可独立参考 |
| `knowledge-spec.md` | §26（KnowledgeWiki）+ ingest/query/lint 操作 | Knowledge 系统开发者可独立参考 |
| `evolve-spec.md` | §10（Inline+Batch）+ §8.3（Skill）+ §24.4（EvalDataset） | Evolve 开发团队可独立参考 |
| `security-spec.md` | §23（RBAC）+ §28（认证）+ §29（通信安全）+ §32（Gate 界面） | 安全审计可独立参考 |
| `ops-spec.md` | §13（运维��+ §30（Runbook）+ §12（可观测）+ §33（多租户） | SRE 可独立参考 |

拆分原则：每个子规范 500-800 行，包含完整的数据结构定义（不跨文件引用结构体字段）。跨规范的引用使用 `{spec_name}§{section}` 格式。

---

## 全局约定（V2.3 新增）

### 版本号格式

本文所有版本号统一采用 `{major}.{minor}.{patch}` 格式（semver）：

| 变更类型 | 版本号变更 | 典型示例 |
|---|---|---|
| **major** | 破坏性变更，需联合双方协商迁移计划 | 状态机重构、必填字段语义修改 |
| **minor** | 向后兼容的新增能力 | 新增可选字段、新增 API |
| **patch** | Bug 修复、文档更正，不改变接口语义 | 校正阈值、补充说明 |

跨层接口（hi-agent ↔ agent-kernel ↔ agent-core）的 major 版本变更必须：
1. 由发起方提前 14 天通知对方团队
2. 双方联合 review 迁移计划
3. 在 KernelManifest / CapabilityDescriptor 中更新 `min_compatible_version`
4. 新旧版本并行运行期 ≥ 1 个完整 sprint，直到存量 client 全部升级

### deprecated 版本最小存活窗口

任何版本（policy / skill / schema）进入 `deprecated` 状态后，至少保持 **7 个自然日** 才可申请 retirement 检查，以防止新版本上线后立即 retire 旧版本导致存量 Run 阻断。对于 SLO 关键 policy（`primary_metric = success_rate`），最小存活窗口延长为 **30 天**。

---

## 1. 核心设计结论

V2.0 的核心结论保持不变：

**系统主体只有一个：`hi-agent`。**

- `hi-agent` 是唯一智能体主体，负责所有认知逻辑
- `agent-core` 是 `hi-agent` 选择性集成的能力模块来源
- `agent-kernel` 是 `hi-agent` 依赖的 durable runtime 底座

后续版本在此基础上，逐步补齐运营质量（V2.1）、生产信任（V2.2）、安全与可运维（V2.3）、契约完备（V2.4）四个阶段的设计缺口。

---

## 2. 系统装配架构

```text
+----------------------------------------------------------------------------------+
|                                    hi-agent                                      |
|----------------------------------------------------------------------------------|
|  TRACE Agent Runtime                                                             |
|  - Task Runtime          - Route Engine          - Context OS                   |
|  - Memory System         - Knowledge System      - Skill Registry               |
|  - Evolution Engine      - Harness Orchestrator                                 |
|                                                                                  |
|  Integrated Capability Modules                                                   |
|  - session / context resources / tool / workflow / sys_operation                |
|  - retrieval / service_api / mcp / asset access                                 |
|  - Capability Registry（new）                                                    |
|                                                                                  |
|  Runtime Adapter                          Observability Plane（new）             |
|  - adapt TRACE ops to agent-kernel        - metrics / tracing / audit log       |
|                                                                                  |
|  Management API（new）                                                            |
|  - run management / task family management / health check                       |
+----------------------------------------------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                                 agent-kernel                                     |
|----------------------------------------------------------------------------------|
|  Durable Runtime Substrate                                                       |
|  - run lifecycle / wait / resume / callback / recovery                           |
|  - event log / projection / replay metadata                                      |
|  - LLM Gateway                                                                   |
|  - harness governance / idempotency / arbitration                                |
+----------------------------------------------------------------------------------+
```

---

## 3. TRACE 核心抽象

```
TRACE = Task → Route → Act → Capture → Evolve
```

- **Task**：把用户请求提升为任务契约对象
- **Route**：在受约束轨迹空间中生成、比较、选择路径
- **Act**：通过 Harness 操作外部世界
- **Capture**：沉淀证据、结果、失败记录和轨迹状态
- **Evolve**：基于反馈持续优化质量与效率

TRACE 以**长程任务运行体**为中心，而非 ReAct 式的短程交互循环。

---

## 4. 两个硬约束

### 4.1 上下文窗口有限

- 每次模型调用必须基于重建的 `Task View`，不依赖无限增长的会话历史

### 4.2 模型与 Provider 持续演进

- Provider 差异隐藏在 `LLM Gateway` 之后，系统认知结构不绑定任何 provider

---

## 5. 一等概念

| 概念 | 定义 |
|---|---|
| **Task** | 任务契约，不是用户一句话 |
| **Run** | 任务的长程 durable 运行主体 |
| **Stage** | 任务推进的正式阶段对象 |
| **Branch** | 轨迹树中的逻辑分支（语义对象，不等于 child run） |
| **Task View** | 某次模型调用前重建的最小充分上下文 |
| **Action** | 通过 Harness 执行的外部动作 |
| **Memory** | 智能体经历过什么（Working + Episodic） |
| **Knowledge** | 智能体稳定知道什么（Semantic + Procedural） |
| **Skill** | 从优质轨迹结晶出的可复用过程单元 |
| **Feedback** | 业务结果、人工评价、实验结果转化的优化信号 |
| **TaskPlan** | 任务拆解方案：子任务结构（DAG/Tree/Linear）及依赖关系、调度与聚合规则（V2.9，§34） |

---

## 6. CTS：受约束轨迹空间

### 6.1 两层结构

- **Stage Graph**：允许的阶段、转移规则、每阶段允许的动作、回退时机、Human Gate 触发时机
- **Trajectory Tree**：某个 Run 实际探索过的分支记录

### 6.2 默认阶段序列与认知目标（V2.3 新增）

```
S1 Understand → S2 Gather → S3 Build/Analyze → S4 Synthesize → S5 Review/Finalize
```

每个阶段有明确的**认知目标**、**进入条件**和**退出条件**，Route Engine 必须依据这些条件判断阶段推进合法性：

| 阶段 | 认知目标 | 进入条件 | 退出条件（至少满足其一） |
|---|---|---|---|
| **S1 Understand** | 形成明确的任务契约；消除歧义；确认 acceptance_criteria 可评估 | Run 创建后自动进入 | TaskContract 所有必填字段通过校验；或 Gate A 已解决歧义 |
| **S2 Gather** | 采集足够的 evidence 支撑后续决策；识别缺失信息 | S1 退出条件满足 | 关键 evidence 采集率 ≥ 阈值（注 1）；或 evidence_overlap_ratio 触发认知停滞检测 |
| **S3 Build/Analyze** | 对 evidence 进行推理、建模或构建中间产物（draft、分析报告、代码等） | S2 退出条件满足 | 至少一个 Branch 产出可评估的中间产物；或进入 Gate C |
| **S4 Synthesize** | 整合多 Branch 产物，形成统一最终产物 | S3 退出条件满足 | 最终产物已生成；acceptance_criteria 初步自评通过率 ≥ 70% |
| **S5 Review/Finalize** | 执行 acceptance_criteria 正式评估；准备最终交付或 Gate D | S4 退出条件满足 | `AcceptanceCriteriaEvaluator.evaluate()` 返回 `passed=true`；或触发 Gate D 等待批准 |

**注 1（V2.5 新增）："关键 evidence"的判定**：S2 退出条件中的"关键 evidence 采集率"存在认识论上的循环——你需要知道什么才能判断你已经知道了足够多。实际操作中，"关键 evidence"通过以下两种方式定义：(a) TaskContract.acceptance_criteria 中显式引用的 evidence 类型（如"需要至少 3 篇相关论文"）——这是确定性的；(b) 该 task_family 的历史统计基线（平均在 S2 阶段采集 N 个 evidence 后 S3 成功率开始收敛）——这由 Evolve 通过 EvalDataset 校准。新 task_family 冷启动时只能依赖 (a)；(b) 在积累足够 Run 后由 Evolve 自动发现并写入 route_policy.parameters。

**回退规则**：任意阶段可通过 Stage Graph 中配置的回退边退回前序阶段，但每次回退必须在 TrajectoryTree 中记录 `stage_revisit_count`，超过 N 次触发 `no_progress (cognitive_level)` 检测（§22）。

### 6.2.1 轨迹节点数据结构（V2.7 新增）

当前的 Trajectory Tree 是被动的日志。V2.7 将其重建为**主动优化的数据结构**——每个节点携带质量信号，优化器根据信号决定扩展、剪枝或回溯：

```
TrajectoryNode（DAG 节点，不限于树——允许合并点）：
  node_id:         str
  node_type:       decision | action | evidence | synthesis | checkpoint
  parent_ids:      [str]    # DAG：可有多个 parent（如 S4 Synthesize 合并多个 S3 分支）
  children_ids:    [str]
  stage_id:        str
  branch_id:       str
  
  # 内容
  content:
    description:   str      # 人类可读的节点描述
    decision_ref:  str      # 若 node_type=decision，关联的 Route Engine 决策
    action_ref:    str      # 若 node_type=action，关联的 Action 记录
    evidence_ref:  str      # 若 node_type=evidence，采集到的证据
    artifact_ref:  str      # 若 node_type=synthesis，生成的产物
  
  # 质量信号（核心：使轨迹可优化）
  quality:
    local_score:     float  # 本节点的直接质量（如 Action 成功=1.0，失败=0.0，部分成功=0.5）
    propagated_score: float # 从后代节点回传的质量信号（越深越衰减）
    visit_count:     int    # 该节点被访问/扩展的次数（MCTS 用）
    confidence:      float  # 节点质量估计的置信度（visit_count 越高越高）
  
  # 状态
  state:           open | expanded | pruned | succeeded | failed
  created_at:      datetime
  completed_at:    datetime (可选)

质量信号回传算法：
  当一个叶子节点完成时（succeeded 或 failed）：
    leaf.local_score = outcome_to_score(action_result)  # 成功=1.0，失败=0.0
    for ancestor in leaf.ancestors_up_to_root():
      ancestor.propagated_score = (
        decay_factor * mean([child.propagated_score for child in ancestor.children if child.state != pruned])
      )
      ancestor.visit_count += 1
    # decay_factor 由 route_policy.quality_propagation_decay 配置（默认 0.9）
```

**TrajectoryNode 与 Branch 的关系（V2.8 澄���）：**

```
Branch 是 TrajectoryNode DAG 上的一条路径视图，不是独立的一等实体：

  Branch = 从某个 decision 节点到其后代叶子节点的一条连续路径
  branch_id = 该路径起点 decision 节点的 node_id

映射关系：
  §14.4 BranchState    →  由路径上所有节点的状态聚合：
    proposed            =  起点 decision 节点 state=open，尚未扩展子节点
    active              =  路径中存在 state=expanded 的节点
    waiting             =  路径末端节点在等待外部回调
    pruned              =  起点或任意祖先被标记 state=pruned
    succeeded           =  路径末端节点 state=succeeded
    failed              =  路径末端节点 state=failed 且无可扩展的兄弟节点

  §14.4 BranchState 保留为 API 层的查询视图（向后兼容），
  但运行时权威状态由 TrajectoryNode.state 驱动。
  open_branch() / mark_branch_state() 等 API 内部转换为 TrajectoryNode 操作。
```

### 6.2.2 轨迹优化器（V2.7 新增）

不同 task_family 适合不同的轨迹优化策略。TrajectoryOptimizer 定义了 4 种模式，在 `TaskFamilyConfig` 中配置：

```
TaskFamilyConfig 新增字段：
  trajectory_optimizer_mode:  greedy | mcts | beam_search | todo_dag
```

**模式 1: greedy（贪心——最简单，类似 autoresearch）**

```
适用：快速任务（quick_task）、确定性高的流程型任务
行为：
  - 单条路径推进，每步选 propagated_score 最高的 child
  - 若当前节点失败：回退到 parent，尝试次优 child
  - 若所有 children 失败：继续回退（但受 stage_revisit_count 限制）
  - 不并行探索
优势：token 成本最低，实现最简单
劣势：可能陷入局部最优，不适合高不确定性任务
实现成本：V1 首选——与当前单 Branch 推进逻辑兼容

greedy 模式下的 TrajectoryNode 简化（V2.8 澄清）：
  greedy 模式只走一条路径���visit_count 始终��� 1，propagated_score = local_score × decay。
  因此 greedy 模式可使用 TrajectoryNode 的轻量实现：
    - 不需要 visit_count 字段（恒等于 1）
    - propagated_score 可退化为简单的 success/failure 布尔值
    - DAG 退化为链表（无并行 children）
  但 TrajectoryNode ��据结构本身必须完整保存（支持后续切换到 mcts/beam 模式时回溯历史）。
```

**模式 2: mcts（蒙特卡洛树搜索——探索与利用的平衡）**

```
适用：研究型任务（deep_analysis）、证据不确定性高的任务
行为：
  Selection:  从根到叶，每层用 UCB1 选子节点
    UCB1(node) = propagated_score / visit_count + C * sqrt(ln(parent.visit_count) / visit_count)
    C = route_policy.exploration_temperature（默认 1.41）
  Expansion:  到达叶子后，调用 Route Engine 生成 1-3 个候选子节点
  Simulation: 对每个候选用轻量 rollout 估计质量
    rollout 方式：counterfactual scoring（§10.2 离线评估方法 2）或规则启发
  Backpropagation: 质量信号沿路径回传（§6.2.1 的回传算法）
  
  每个 MCTS 循环消耗 1 次 Route Engine 调用 + 1-3 次 rollout
  循环数由 CTS 预算控制：max_route_compare_calls_per_cycle

优势：在不确定环境中自动平衡 exploration/exploitation
劣势：需要 rollout 的额外 token 成本
实现成本：中等——需要 UCB1 选择 + 轻量 rollout（可复用 §10.2 的 counterfactual 方法）
```

**模式 3: beam_search（束搜索——创造性任务的多路径保持）**

```
适用：报告撰写、代码生成等需要比较多个完整方案的任务
行为：
  - 维护 top-K 条并行路径（K = max_active_branches_per_stage）
  - 每步：每条路径各扩展 1 个子节点
  - 每步后：按 propagated_score 排序，保留 top-K，剪枝其余
  - 到达 S4 Synthesize 时：所有存活路径合并为最终产物
  
  与 greedy 的区别：greedy 只保留 1 条路径；beam 保留 K 条
  与 mcts 的区别：beam 不回溯，只向前；mcts 会回溯到高 UCB1 的历史节点

优势：产物多样性高，S4 合并时有多个视角
劣势：K 倍的 token 成本
实现成本：低——本质是当前 multi-Branch 并行的规范化
```

**模式 4: todo_dag（TODO 列表 DAG——结构化任务分解）**

```
适用：任务目标可分解为子目标的场景（如"写一份包含 5 章的分析报告"）
行为：
  Phase 1（任务分解，在 S1 Understand 完成）：
    Route Engine 将 TaskContract.goal 分解为子目标 DAG：
    TodoNode:
      todo_id:      str
      description:  str              # 子目标描述
      depends_on:   [todo_id]        # 前置依赖
      assigned_stage: stage_id       # 该子目标对应的 Stage
      status:       pending | in_progress | completed | blocked
      result_ref:   str              # 完成后的产物引用
    
  Phase 2（执行，S2-S4）：
    按 DAG 拓扑顺序执行 TodoNode
    无依赖的 TodoNode 可并行执行（作为不同 Branch）
    每个 TodoNode 完成后更新 status + result_ref
    所有 TodoNode completed 后进入 S5
    
  Phase 1.5（分解质量检查，V2.8 新增）：
    S1 完成任务分解后，自动触发一次分解质量验证：
    - 检查 1：所有 acceptance_criteria 是否被至少一个 TodoNode 覆盖
      （遍历 criteria → 每条 criterion 的关键词在某个 TodoNode.description 中出现）
    - 检查 2：DAG 无环（拓扑排序可完成）
    - 检查 3：无孤立 TodoNode（每个 node 要么无 depends_on（根节点），要么 depends_on 指向存在的 node）
    - 任一检查失败：触发 Gate B（route_direction），请人工修正分解
    - 全部通过：进入 Phase 2
    
  Phase 3（变更管理）：
    若 Gate A 修改了 TaskContract.goal → 重新分解 DAG
    新旧 DAG diff：保留未受影响的 completed 节点，重做受影响的节点

优势：适合目标明确、可分解的任务，进度可视，人类可介入调整
劣势：不适合探索性任务（目标本身不明确）
实现成本：中等——需要 Route Engine 输出 TodoNode 分解 + DAG 调度器

V2.9 扩展：当 TodoNode 需要并行执行且复杂度超过单 Run Branch 能力时，
可升级为 TaskPlan 模式（§34），将子目标分派为独立的子 Run 由 Worker 自闭环执行。
todo_dag 是单 Run 内的轻量分解；TaskPlan 是跨 Run 的重量级分解。
两者的选择由 DecompositionPolicy 自动判断（§34.5）。
```

**模式选择矩阵：**

| task_family 特征 | 推荐模式 | 理由 |
|---|---|---|
| 目标明确、步骤确定、低不确定性 | greedy | 成本最低，不需要探索 |
| 高不确定性、需要权衡多种可能 | mcts | 自动平衡探索与利用 |
| 需要多个完整方案供比较 | beam_search | 保持多样性到合并点 |
| 目标可分解为子目标、有依赖关系 | todo_dag | 结构化执行，进度可视 |

**与 Route Engine 的交互：** TrajectoryOptimizer 不替代 Route Engine，而是**指导** Route Engine 在哪个节点扩展：
- greedy/beam: 在叶子节点扩展
- mcts: 在 UCB1 选中的节点扩展
- todo_dag: 在下一个 ready 的 TodoNode 对应位置扩展

Route Engine 仍然负责"在给定位置生成什么候选"（§21.1 接口不变）。

### 6.3 CTS 预算

| 参数 | 说明 |
|---|---|
| `max_active_branches_per_stage` | 每 Stage 最大并发 Branch 数 |
| `max_total_branches_per_run` | 单 Run 最大 Branch 总数 |
| `max_route_compare_calls_per_cycle` | 单路由周期最大比较调用次数 |
| `max_route_compare_token_budget` | 路由比较 token 预算 |
| `max_exploration_wall_clock_budget` | 探索总挂钟时长预算 |
| `max_mcts_simulations_per_cycle` | MCTS 模式下每个路由周期的最大 rollout 次数（V2.8，默认 3，greedy/beam/todo_dag 模式忽略此字段） |
| `max_mcts_simulation_token_budget` | MCTS rollout 的 token 预算（V2.8，默认 4096，超出则终止 simulation 阶段直接用已有 score 回传） |

### 6.4 Stage Graph 版本化

- Stage Graph 独立版本（`stage_graph_version`），随 `task_family` 归档
- 新 Stage Graph 版本只影响新建 Run；存量 Run 沿用创建时的 Stage Graph 版本
- Stage Graph 变更分类：
  - **兼容变更**：新增可选 Stage，放宽 Gate 触发条件
  - **破坏性变更**：删除 Stage，修改 Stage 转移规则，收紧 Gate 条件 → 必须新建 task_family 版本

### 6.5 Stage Graph 子图引用与继承（V2.2 新增）

多个 task_family 可以通过子图引用共享公共阶段结构，避免重复定义：

```
StageGraphDef:
  stage_graph_id:       稳定标识
  stage_graph_version:  版本号
  extends:              parent_stage_graph_id (可选，继承父图后 override)
  shared_subgraphs:     [SubgraphRef]  # 引用可复用子图
  stages:               [StageDef]     # 本 family 独有的阶段定义
  override_stages:      [StageDef]     # 覆盖父图或子图中的阶段定义

SubgraphRef:
  subgraph_id:    被引用的子图标识
  mount_point:    将子图挂载在哪个阶段节点
  override:       [StageDef]  # 局部覆盖
```

**覆盖优先级规则（V2.5 新增）**：当 `extends`（父图）、`shared_subgraphs`（子图）和 `override_stages`（本地覆盖）对同一 Stage 有不同定义时，优先级从高到低为：
1. `override_stages`（本地覆盖优先——最具体的定义胜出）
2. `shared_subgraphs[].override`（子图级覆盖）
3. `stages`（本 family 的直接定义）
4. `shared_subgraphs` 中的原始定义
5. `extends` 父图中的定义
若同一优先级内有冲突（如两个 shared_subgraph 定义了同名 Stage），注册校验报错：`ambiguous_stage_definition`。

形式化验证要求（注册时强制执行）：
- 无不可达 Stage（每个 Stage 至少有一条从初始 Stage 可达的路径）
- 无死锁（无法到达任何终态的 Stage 必须有 Gate 出口）
- 至少一个终态 Stage（completed 或 failed）

### 6.6 CTS 预算模板（V2.2 新增）

预定义四类标准模板，task_family 可继承后覆盖单个字段：

```
CTSBudgetTemplate:
  template_id:                      default | quick_task | deep_analysis | batch_processing
  max_active_branches_per_stage:    2 | 1 | 5 | 3
  max_total_branches_per_run:       10 | 5 | 30 | 15
  max_route_compare_calls_per_cycle: 3 | 1 | 8 | 3
  max_route_compare_token_budget:   4096 | 1024 | 16384 | 4096
  max_exploration_wall_clock_budget: 4h | 30m | 24h | 8h

TaskFamilyConfig 使用方式:
  cts_budget_template: deep_analysis    # 选择模板
  cts_budget_overrides:                 # 只覆盖需要修改的字段
    max_active_branches_per_stage: 3
```

---

## 7. 职责边界

### 7.1 hi-agent 负责

- Task Contract / CTS / Stage Graph / Route Policy
- Task View 语义选择、降级策略
- Memory / Knowledge 语义
- Skill 生命周期（Skill Registry 归属 hi-agent）
- Evaluation Logic / Evolve Logic
- Harness 语义编排
- Capability Registry（集成 agent-core 能力的发现与注册）

### 7.2 agent-kernel 负责

- Run Lifecycle / durable runtime
- wait / resume / callback / recovery
- event log / projection / replay metadata
- LLM Gateway
- Harness 执行治理 / idempotency / arbitration
- policy version 冻结与审计

### 7.3 agent-core 负责

- session / context resources / tool / workflow / sys_operation
- retrieval / service_api / mcp / asset access

明确不归 agent-core：route、task view selection、evolve、runtime truth

---

## 8. 可扩展设计

### 8.1 Capability Registry（V2.1 新增）

hi-agent 维护一个 **Capability Registry**，管理从 agent-core 集成的所有能力模块。

```
CapabilityDescriptor:
  capability_id:       稳定唯一标识
  capability_kind:     tool | workflow | retrieval | service_api | mcp | sys_operation
  version:             能力版本
  min_kernel_version:  依赖的最低 agent-kernel 版本（可选）
  min_core_api_version: 依赖的最低 agent-core API 版本（V2.5 新增，可选）
  max_core_api_version: 兼容的最高 agent-core API 版本（V2.5 新增，可选）
                       # hi-agent 在注册时校验当前 agent-core API 版本是否在 [min, max] 区间内
  effect_class:        read_only | idempotent_write | compensatable_write | irreversible_write
  side_effect_class:   read_only | local_write | external_write | irreversible_submit
  schema_ref:          输入输出 schema 引用
  enabled:             是否启用
  task_families:       适用 task family 列表（空=全部）
  depends_on:          [capability_id]  # 依赖的其他能力，加载时按依赖顺序初始化
  sandbox_class:       none | light | strict
                       # none: 同进程运行
                       # light: 独立线程 + 资源配额（CPU/Memory limit）
                       # strict: 独立子进程 + 网络/文件系统隔离
  hot_update_policy:   restart_required | graceful_reload | immediate
                       # 能力版本升级时是否需要重启 hi-agent
  credential_refs:     [secret_id]  # 所需凭证的 secret_id 引用，不含凭证内容本身
  expected_p99_latency: duration    # 声明的 P99 延迟基准（如 2s），用于 §31.3 timeout 计算
  max_retries:         int          # 最大重试次数（默认 3），防止无限重试循环（§31.2）
  retry_backoff:       exponential(base_ms=500, max_ms=30000) | fixed(ms=N)
                       # 重试退避策略，默认指数退避
```

注册原则：
- 新能力通过注册声明，不通过硬编码引入
- hi-agent 启动时验证所有 `depends_on` 依赖均已注册，且按依赖拓扑顺序初始化
- `hot_update_policy=graceful_reload` 的能力可在不重启 hi-agent 的前提下更新，但需等待当前使用该能力的 Action 完成
- Capability Registry 版本随 hi-agent 部署版本归档

#### Capability 热更新期间 in-flight Branch 的处理（V2.3 新增）

当 `hot_update_policy=graceful_reload` 的能力从 `cap_v1` 升级到 `cap_v2` 时，当前正在执行的 Branch 可能依赖旧版能力语义：

```
升级时序：
  1. 触发 graceful_reload：Capability Registry 标记 cap_v1 为 draining
  2. 不再向新 Branch 分配 cap_v1
  3. 等待所有使用 cap_v1 的 in-flight Action 完成（最长等待 graceful_reload_timeout，默认 120s）
  4. graceful_reload_timeout 超时时的策略（按 side_effect_class）：
     - read_only / local_write：强制切换到 cap_v2，action_semantic_key 保持不变
     - external_write：保持 cap_v1 直到 Action 完成或超时后进入 effect_unknown
     - irreversible_submit：阻止热更新，返回 reload_blocked 错误，运维人员介入
  5. cap_v2 接管，cap_v1 下线

action_semantic_key 稳定性保证：
  - Capability 热更新期间，Route Engine 生成的 action_semantic_key 必须包含 capability schema 版本
  - 格式："{capability_id}_v{schema_major}" （例："search_arxiv_v2"）
  - 旧版 Branch 的 action_id（含 v1 semantic_key）在 agent-kernel 事件流中永久保留，不被 v2 覆盖
```

**能力兼容性约束**：`cap_v1 → cap_v2` 若属于 minor/patch 升级（input/output schema 向后兼容），in-flight Branch 可透明切换；若属于 major 升级（schema 破坏性变更），必须先创建新 capability_id（`cap_v2_new`），旧 capability_id 进入 deprecated 生命周期，不允许直接热更新替换。

#### Capability 熔断器（V2.4 新增）

单个 Capability 连续失败时，应临时停止分配给新 Branch，避免持续消耗 CTS 预算探索必然失败的路径：

```
CapabilityDescriptor 新增字段：
  circuit_breaker_policy:
    enabled:               bool (默认 true)
    failure_threshold:     int  (连续失败次数阈值，默认 5)
    half_open_timeout:     duration (熔断后多久尝试半开，默认 60s)
    success_threshold:     int  (半开状态下连续成功几次恢复 closed，默认 2)

熔断器状态机：
  closed（正常）→ 连续 failure_threshold 次失败 → open（熔断）
  open → half_open_timeout 到期 → half_open（试探）
  half_open → success_threshold 次成功 → closed
  half_open → 任意失败 → open

熔断时的 Route Engine 行为：
  - Route Engine 的 available_capabilities 输入中不包含处于 open 状态的 capability
  - 若 Branch proposal 中 required_capabilities 包含 open 状态 capability：
    该 Branch 标记为 prune_code=capability_unavailable，不创建
  - 熔断状态写入 Capability Registry，暴露于 /health/status 端点

熔断器例外：
  - side_effect_class=irreversible_submit 的 Capability 熔断阈值强制为 3（更激进保护）
  - circuit_breaker_policy.enabled=false 仅允许 read_only capability 关闭熔断器
```

#### agent-core 全量不可用时的系统降级（V2.4 新增）

若 agent-core 整体不可达（非单个 Capability 失败），hi-agent 需要系统级保护：

```
AgentCoreAvailabilityState:
  healthy:    ≥ 1 个 non-read_only Capability 可用
  degraded:   仅 read_only Capability 可用（外部写入能力全部不可用）
  unavailable: 0 个 Capability 可用（包括 read_only）

降级行为：
  degraded 模式：
    - 允许继续的 Run：处于 S1/S2 阶段（仅需 read_only 操作）
    - 阻止推进的 Run：需要 external_write/irreversible_submit 的 Stage 入口
    - /health/status 报告 capability_degraded=true
    - 停止接受需要写入能力的 task_family 新 Run

  unavailable 模式：
    - 所有 Run 暂停推进（停在当前 Stage，不失败）
    - /health/ready → 503
    - 等待 agent-core 恢复后，Run 自动从暂停点继续（不需要人工介入）
    - 若 unavailable 持续超过 cts_budget.max_exploration_wall_clock_budget：
      相关 Run 触发 callback_timeout → 进入恢复面仲裁
```

### 8.2 Task Family 配置模型（V2.1 新增）

每个 `task_family` 拥有独立配置：

```
TaskFamilyConfig:
  task_family:          标识
  stage_graph_version:  使用的 Stage Graph 版本
  cts_budget:           该 family 的 CTS 预算
  enabled_capabilities: 允许使用的 capability_id 列表
  default_policies:     route / skill / evaluation / task_view policy 默认版本
  risk_level_policy:    各 risk_level 对应的 Human Gate 触发策略
  trajectory_optimizer_mode: greedy | mcts | beam_search | todo_dag（V2.7，默认 greedy）
  knowledge_ingest_policy:  always | on_success | on_labeled | disabled（V2.8 新增）
                            # always: 每次 Run 完成后 ingest（适合 deep_analysis）
                            # on_success: 仅 completed Run ingest（默认）
                            # on_labeled: 仅 human_quality_label ≥ acceptable 的 Run ingest
                            # disabled: 不 ingest（适合高频低价值 quick_task 初期）
```

- Task Family 配置变更走正常变更流程（change_record），不影响存量 Run
- 新增 task_family 不需要修改任何现有 family 的配置

### 8.3 Skill Registry（V2.1 新增）

Skill 作为一等公民，Skill Registry 管理其完整生命周期：

```
SkillRecord:
  skill_id:              稳定唯一标识
  skill_version:         版本
  task_family:           主归属 task family
  generalization_scope:  private | shared | universal
                         # private: 仅限 task_family 内部使用
                         # shared: 可被显式引用的 task_family 使用
                         # universal: 对所有 task_family 可见
  shared_with_families:  [task_family]  # generalization_scope=shared 时有效
  stage_affinity:        推荐在哪些 Stage 使用
  status:                draft | candidate | active | deprecated | retired
  source_trace_refs:     产生该 Skill 的优质轨迹引用
  evaluation_ref:        质量认证结果引用
  generalization_basis:  若从其他 family Skill 泛化而来，记录来源 skill_id
  activated_at:          激活时间
  deprecated_at:         废弃时间
```

状态流转：`draft → candidate → active → deprecated → retired`

#### Skill 内容模型（V2.6 新增）

SkillRecord 的 `source_trace_refs` 记录了 Skill 的来源，但 Skill 的**实际内容**——Agent 在运行时如何使用它——需要独立的内容模型：

```
SkillRecord 新增字段：
  content_ref:             str    # 指向 SkillContent 的存储引用
  content_type:            prompt_template | action_pattern | decision_rule | composite

SkillContent（Skill 的实际可执行内容）：
  skill_id:                str
  skill_version:           str
  content_type:            prompt_template | action_pattern | decision_rule | composite
  content_schema_version:  str    # 内容格式的 schema 版本（遵循全局 semver 约定）
  content:                 按 content_type 分型（见下）
```

**四种 content_type 及其结构：**

```
1. prompt_template（最常见——为 LLM 调用提供结构化提示模板）

PromptTemplateContent:
  system_instruction:    str    # 角色设定和行为约束
  task_framing:          str    # 任务框架模板（含 {goal}、{evidence_summary} 等槽位）
  few_shot_examples:     [FewShotExample]
  output_format:         str    # 期望输出格式说明（如 JSON schema 引用）
  guard_rails:           [str]  # 负面约束（"不要做…"列表）
  
  FewShotExample:
    input_summary:   str    # 输入场景描述
    expected_output: str    # 期望输出
    rationale:       str    # 为什么这个输出是好的（可选，帮助 LLM 理解意图）

  适用场景：S3 Build/Analyze 阶段的报告撰写、S4 Synthesize 阶段的整合总结
  Evolve 方式：修改 system_instruction / 增删 few_shot_examples / 调整 output_format

2. action_pattern（动作序列模式——描述在特定 Stage 内的推荐动作编排）

ActionPatternContent:
  trigger_condition:     str    # 何时应用此模式（如 "stage=S2 AND task_family=research"）
  steps:                 [ActionStep]
  branching_rules:       [BranchingRule]    # 条件分支
  early_exit_conditions: [str]              # 提前退出条件（如 "evidence_count >= 10"）
  
  ActionStep:
    step_id:           str
    action_kind:       str              # 对应 Capability 类别（如 "web_search", "document_parse"）
    capability_filter:  { capability_kind, effect_class_max }  # 允许的 Capability 范围
    input_template:    str              # 动作输入的模板（引用 Task View 中的变量）
    postcondition:     str              # 执行后应满足的条件
    on_failure:        skip | retry | abort_pattern
  
  BranchingRule:
    condition:    str                   # 基于当前 evidence 的条件判断
    then_step:    step_id
    else_step:    step_id

  适用场景：S2 Gather 阶段的标准化信息采集流程
  Evolve 方式：增删 steps / 调整 branching_rules / 修改 early_exit_conditions

3. decision_rule（决策规则——为 Route Engine 提供辅助判断）

DecisionRuleContent:
  applies_to:       route_decision | stage_transition | branch_pruning
  rules:            [Rule]
  priority:         int    # 多条 Skill 的 decision_rule 冲突时的优先级
  
  Rule:
    condition:     str    # 结构化条件表达式（如 "evidence.count('contradictory') >= 2"）
    action:        str    # 建议动作（如 "trigger_gate_c" / "prefer_branch_with_more_evidence"）
    confidence_boost: float  # 对 Route Engine confidence 的修正值（-0.3 到 +0.3）
    rationale:     str    # 规则的来源解释

  适用场景：特定 task_family 积累的领域判断规则
  Evolve 方式：增删 rules / 调整 confidence_boost / 修改 condition 阈值

4. composite（组合——将多个 Skill 组合为一个复合 Skill）

CompositeContent:
  sub_skills:     [{ skill_ref, stage_affinity, activation_condition }]
  composition_mode: sequential | parallel | conditional
  
  适用场景：复杂 task_family 需要多个 Skill 协作的场景
  Evolve 方式：调整 sub_skills 组合 / 修改 activation_condition / 变更 composition_mode
```

**Skill 在运行时的使用方式：**
```
Route Engine 的 RouteEngineInput 中，available_capabilities 已包含 Capability 列表。
Skill 的注入方式（不修改 RouteEngineInput 接口）：

1. prompt_template → 注入到 Task View 的 system prompt 区域
   （task_view_policy 控制是否启用、哪个 Skill 的 prompt_template 生效）
   
2. action_pattern → Route Engine 在生成 BranchProposal 时参考
   （如果存在匹配的 action_pattern，优先使用其 steps 作为 action_sequence_hint）
   
3. decision_rule → Route Engine 在计算 confidence 和 prune 决策时参考
   （rules 作为 RoutePolicyContent 的运行时扩展，不修改 policy 版本）
   
4. composite → 展开为子 Skill，按各自类型分别注入
```

跨 family Skill 引用规则：
- `shared` Skill 被其他 family 引用前，需 `evolve_manager` 显式批准
- `universal` Skill 在晋升时需通过覆盖至少 3 个不同 task_family 的评估验证；各 family 必须分别按自身 QualityGate 达标（不允许共用一个 family 的数据集三次算"三个 family"）
- 引用方不得直接修改来源 Skill，只能 fork 后在本 family 作为新 `private` Skill 演进

#### Skill Retirement 安全门（V2.3 新增）

与 Policy retirement 相同，Skill 的 `deprecated → retired` 前必须通过安全门检查：

```
SkillRetirementSafetyCheck:
  1. active_run_references = count_runs_using_skill(skill_id, skill_version,
                               states=[active, waiting, recovering])
  2. pending_evolve_references = count_evolve_sessions_referencing(skill_id,
                                   status=[collecting, evaluating, experimenting])
  3. 若 active_run_references > 0 或 pending_evolve_references > 0：
       拒绝 retire，返回 { active_run_ids, evolve_session_ids }
  4. 若全部为 0 且距 deprecated_at > 最小存活窗口（§全局约定）：
       允许 retire，写入 retired_at 时间戳
```

**Skill breaking change 检测**：Skill 升级到新 `skill_version` 时，若 input/output schema 发生破坏性变更（major bump），引用该 Skill 的所有 task_family 必须在 `Skill Registry` 中显式确认兼容（`compat_confirmed_at`），否则拒绝该 Skill 版本进入 `candidate` 状态。

---

## 9. 可演进设计

### 9.1 Policy Version 生命周期

Run 启动时冻结四个 policy version：

```
PolicyVersionSet:
  route_policy_version:      路由策略版本
  skill_policy_version:      技能策略版本
  evaluation_policy_version: 评估策略版本
  task_view_policy_version:  任务视图策略版本
```

版本生命周期：`draft → active → deprecated → retired`

- `active` 版本可被新 Run 引用
- `deprecated` 版本仍可被存量 Run 使用，但不允许新 Run 引用
- `retired` 版本：**retirement 前必须通过安全门检查**（见下）

### 9.1.1 Policy Retirement 安全门（V2.2 新增）

在将任意 policy version 从 `deprecated` → `retired` 之前，必须验证：

```
RetirementSafetyCheck:
  1. active_run_references = count_runs_referencing(policy_version, states=[active, waiting, recovering])
  2. 若 active_run_references > 0：拒绝 retire，返回 active_run_ids 列表
  3. 若 active_run_references == 0：允许 retire，写入 retired_at 时间戳
```

- 存量 Run 必须通过显式 `change_record` 迁移到新版本后，原版本才可 retire
- `evaluation_policy_version` 的 retire 要求更严格：所有依赖该版本的历史 Evolve ChangeSet 也必须已归档

### 9.1.2 Policy 内容 Schema 框架（V2.2 新增）

每个 policy 类型有对应的内容 schema，版本冻结的是有内容定义的策略对象，而非仅仅是版本号：

```
PolicyContentSpec:
  policy_version:    str          # 版本号
  policy_type:       route | skill | evaluation | task_view
  schema_version:    str          # 本 policy 内容所符合的 schema 版本
  description:       str          # 人类可读的变更说明
  parameters:        dict         # 类型化的参数集合（按 schema_version 约束）

# route_policy 示例参数：
RoutePolicy.parameters:
  max_branch_depth:          int      # 最大 Branch 嵌套深度
  route_compare_model:       model_id # 用于比较路径的模型
  pruning_strategy:          conservative | aggressive | adaptive
  exploration_temperature:   float    # 路径多样性系数（0-1）
  evidence_weight_schema:    str      # evidence 质量加权 schema 引用

# evaluation_policy 示例参数：
EvaluationPolicy.parameters:
  primary_metric:            success_rate | acceptance_rate | efficiency_score
  quality_threshold:         float    # 最低质量分数
  efficiency_weight:         float    # 效率在综合评分中的权重
  min_sample_size:           int      # 统计有效的最小样本量

# skill_policy 参数（V2.6 新增）：
SkillPolicy.parameters:
  skill_injection_mode:      always | on_match | disabled
                             # always: 所有匹配 stage_affinity 的 Skill 均注入 Task View
                             # on_match: 只有 trigger_condition 精确匹配时注入
                             # disabled: 不使用 Skill（纯 LLM 裸跑，用于 A/B 对照组）
  max_active_skills_per_stage: int    # 同一 Stage 最多同时生效的 Skill 数（默认 3，防止 prompt 膨胀）
  prompt_template_token_budget: int   # 注入 prompt_template 类 Skill 的最大 token 数（默认 2048）
  action_pattern_priority:   skill_first | route_first
                             # skill_first: action_pattern 优先于 Route Engine 自主决策
                             # route_first: Route Engine 决策优先，action_pattern 仅为参考
  decision_rule_max_confidence_boost: float  # 单条 decision_rule 对 confidence 的最大修正幅度（默认 0.2）
  skill_staleness_action:    warn | exclude | revalidate
                             # warn: suspect 状态 Skill 仍注入，但在 Task View 中标记警告
                             # exclude: suspect 状态 Skill 不注入
                             # revalidate: 使用前先触发 on_use 重验证

# task_view_policy 参数（V2.6 新增）：
TaskViewPolicy.parameters:
  must_keep_token_overflow_action:  model_upgrade | gate_c | fail
                                   # 当 must_keep 超出窗口时的处理（§18.3）
  should_keep_weight:              float  # should_keep 在剩余空间中的分配比例（默认 0.6）
  nice_to_have_weight:             float  # nice_to_have 分配比例（默认 0.3）
  system_reserved_ratio:           float  # 系统保留比例（默认 0.1）
  evidence_recency_decay:          float  # 时效衰减系数（0-1，越高越偏好新 evidence，默认 0.5）
  memory_relevance_method:         keyword | embedding
                                   # keyword: 关键词匹配（V1 默认，无额外成本）
                                   # embedding: 向量相似度（需要 embedding 模型，精度更高）
  knowledge_confidence_floor:      float  # Knowledge confidence 低于此值不进入 Task View（默认 0.3）
  max_pruned_branch_summaries:     int    # nice_to_have 中最多包含几个已剪枝 Branch 的摘要（默认 3）
  embedding_model_version:         str    # 当 memory_relevance_method=embedding 时使用的模型版本
```

这使得两个 policy version 之间的 diff 可计算，Evolve 评估有明确的对比维度。四种 Policy 的参数空间均已定义，parameter_tuning 类 ChangeSet 的搜索空间完整。

### 9.2 Schema 演进策略（V2.1 新增）

对所有跨层契约对象（TaskContract、TaskViewRecord、HarnessActionEnvelope、TraceRuntimeView），版本变更分类：

| 变更类型 | 规则 | 举例 |
|---|---|---|
| **向后兼容** | 新增可选字段，不改变现有字段语义 | 添加 `priority` 字段 |
| **向前兼容** | 移除可选字段，接收方必须容错 | 移除不再使用的字段 |
| **破坏性变更** | 修改必填字段语义，重命名，改变状态机 | 必须通过 major version bump |

接口版本号格式：`{major}.{minor}.{patch}`（遵循全局约定中的 semver 规范），major 变更时需要联合双方协商迁移计划。

### 9.3 hi-agent ↔ agent-kernel 接口兼容矩阵（V2.1 新增）

`KernelManifest` 在现有能力协商基础上，增加版本兼容声明：

```
KernelManifest:
  trace_protocol_version:    当前支持的 TRACE 协议版本（如 "2.1"）
  min_compatible_version:    最低兼容的 hi-agent 客户端版本
  supported_trace_features:  功能特性列表（见下）
  api_version:               kernel 接口版本
```

hi-agent 启动时读取 KernelManifest，若 `trace_protocol_version < min_required`，应拒绝启动并提示升级。

### 9.4 最小建议特性集

- `policy_version_pinning`
- `task_view_record`
- `task_view_late_bind`
- `branch_protocol`
- `stage_protocol`
- `human_gate_protocol`
- `trace_runtime_view`
- `callback_arbitration`
- `action_state_surface`

---

## 10. 可进化设计（V2.7 重构：Inline + Batch 双轨进化）

V2.6 的 Evolve 是一个独立的批处理 Pipeline。但参考 Karpathy autoresearch 的核心洞察——**进化不是独立于运行的，进化是运行的副产品**——V2.7 将 Evolve 拆为两个轨道：

```
Inline Evolution（per-Run，实时发生）：
  触发：每次 Stage 完成 / 每次 Run 完成
  操作：
    1. 轨迹优化器实时回传质量信号（§6.2.1 TrajectoryNode.quality backpropagation）
    2. 记忆压缩（L0→L1→L2，§25.3）
    3. 知识 ingest（Run 完成后编译进 KnowledgeWiki，§26.2）
    4. Episode 生成与去重（L3_episodic，§25.3）
  成本：0-3 次 LLM 调用/Run（压缩 + ingest）
  延迟：Run 完成后数秒内完成
  不需要 EvolveSession——这是 Run 生命周期的自然延伸
  
  失败处理（V2.8 新增）：
    原则：Inline Evolution 失败不阻塞 Run 终态
    - L1 压缩失败 → fallback 到 L0 临时裁剪（§25.3 压缩时序）
    - L3 episodic 生成失败 → 跳过，下次 Run 补偿（episode_id 幂等，不会重复）
    - KnowledgeWiki ingest 失败 → 跳过，事件日志标记 ingest_pending=true
      后台异步重试（max_retries=3, backoff=exponential）
      所有重试失败 → 告警 knowledge_ingest_failed，等待手动处理
    - Run 标记为 completed 不受以上任何失败影响

Batch Evolution（per-N-Runs，原 Evolve Pipeline，保留）：
  触发：§10.1 的 5 种触发条件
  操作：ChangeSet 生成 → 离线评估 → A/B 实验 → 晋升
  成本：视策略而定（parameter_tuning 低成本，skill_extraction 中等成本）
  延迟：数天到数周
  需要 EvolveSession——这是显式的优化周期
```

**两个轨道的关系：** Inline Evolution 持续积累数据（质量信号、压缩记忆、编译知识、情景模式），Batch Evolution 消费这些数据做结构化优化（调参、提取 Skill、发现知识）。如果只有 Batch 没有 Inline，Batch 缺乏高质量的输入数据；如果只有 Inline 没有 Batch，系统只能积累经验但不会结构化改进。

### 10.1 Batch Evolve 触发条件（原 V2.1，保留）

Batch Evolve 不是每次 Run 后自动触发，而是满足以下任一条件时触发：

| 触发类型 | 条件 |
|---|---|
| **批量触发** | 指定 task_family 累积完成 N 个 Run |
| **质量触发** | 近期成功率低于阈值 X% |
| **效率触发** | 近期平均 token 消耗超过预算 Y |
| **反馈触发** | 累积 M 个 `approved` 的人工评价信号 |
| **手动触发** | 运维人员显式触发 |

触发后，生成一个 `EvolveSession`，由 Evolution Engine 驱动。

### 10.2 Evolve Pipeline

```
Feedback 采集
    ↓
EvolveSession 创建（声明 change_scope、task_family、baseline、knowledge_wiki_snapshot_version）
    ↓
ChangeSet 草案生成（候选 skill / policy / knowledge 变更）
    ↓
离线评估（Evaluation Policy 驱动，与存量 Run 对比，验证 QualityGate）
    ↓
实验（A/B 实验：新旧 policy 并行，对比质量/效率指标）
    ↓
晋升决策（QualityGate 数字门通过后允许晋升）
    ↓
Policy Promotion（新版本进入 active，旧版本 deprecated）
    ↓
存量 Run 升级（可选，需显式 change_record）
```

EvolveSession 状态机：`created → collecting → evaluating → experimenting → promoting → completed / failed / rolled_back`

**KnowledgeWiki 版本冻结（V2.8 新增）**：EvolveSession 创建时快照当前 KnowledgeWiki 的 IndexPage hash 作为 `knowledge_wiki_snapshot_version`。evaluating 和 experimenting 阶段使用该快照版本的知识（不受 Inline Evolution 的实时 ingest 影响），确保评估结论的一致性。promoting 完成后释放快照。

#### ChangeSet 草案生成策略（V2.6 新增）

"ChangeSet 草案生成"是 Evolve Pipeline 的**核心创造性步骤**——系统如何知道该改什么才能变好。定义四种生成策略，EvolveSession 在 `collecting` 阶段选择：

```
EvolveSession 新增字段：
  generation_strategy:  human_guided | parameter_tuning | skill_extraction | knowledge_discovery
```

**策略 1: human_guided（人工引导——V1 首选，最低实现成本）**

```
流程：
  1. evolve_manager 手动创建 EvolveSession，指定 generation_strategy=human_guided
  2. evolve_manager 直接提交 ChangeSet 草案（如：修改 route_policy 的 pruning_strategy 参数）
  3. 系统跳过自动生成，直接进入 evaluating 阶段

适用场景：
  - 运维人员根据 Runbook 诊断发现需要调参（如 §30.5 成本超支 → 调 pruning_strategy）
  - 领域专家基于业务反馈手动创建新 Skill（如写一个 prompt_template）
  - V1 阶段：所有 Evolve 从 human_guided 开始，积累数据后再启用自动策略

实现成本：极低——只需 API 接口接收人工提交的 ChangeSet
```

**策略 2: parameter_tuning（参数自动调优——基于统计信号）**

```
流程：
  1. 从近期 Run 的指标中识别 optimization_signal：
     - success_rate 下降 → 可能需要放宽 pruning_strategy
     - token_cost 上升 → 可能需要收紧 max_active_branches
     - gate_b_trigger_rate 上升 → 可能需要降低 confidence_threshold
  2. 生成候选参数变更（一次只调一个参数，控制变量法）：
     ParameterCandidate:
       target_policy_type:  route | evaluation | skill | task_view
       parameter_name:      str        # 要修改的参数名
       current_value:       any        # 当前值
       candidate_value:     any        # 候选值
       generation_rationale: str       # 为什么生成这个候选（关联到哪个 optimization_signal）
  3. 候选值的搜索方式：
     - 枚举型参数（如 pruning_strategy）：遍历所有可选值中未试过的
     - 连续型参数（如 exploration_temperature）：在当前值 ±20% 范围内取 3 个候选
     - 整数型参数（如 max_active_branches）：当前值 ±1

适用场景：
  - 质量触发或效率触发的 EvolveSession
  - task_family 已有足够 Run 历史（seed_runs_required 已满足）

限制：
  - 一次只调一个参数（避免多变量混淆效果归因）
  - 不创造新 Skill，只优化已有 Policy 参数
  - 搜索空间由 PolicyContentSpec.parameters 定义（§9.1.2）
```

**策略 3: skill_extraction（Skill 结晶——从优质轨迹提取可复用 Skill）**

```
这是"从优质轨迹结晶出可复用过程单元"的具体实现。

Skill 结晶算法：

  Step 1: 优质轨迹筛选
    source_runs = select_runs(
      task_family,
      filter = {
        acceptance_criteria_pass_rate >= 0.9,      # 高通过率
        human_quality_label in [excellent, acceptable],  # 有正面标注
        total_token_used <= family_avg × 0.8       # 效率优于平均
      },
      min_count = 5,         # 至少 5 条优质轨迹
      max_count = 20         # 最多分析 20 条
    )
    
  Step 2: 模式提取（按 content_type 分路）
  
    prompt_template 提取：
      input:  source_runs 中 S3/S4 阶段的 LLM 调用记录（task_view + model_output）
      method: LLM meta-analysis
        - 将 5-20 条成功的 (task_view, model_output) 对发送给 meta-LLM
        - prompt: "以下是同类任务中表现优异的 LLM 交互记录。
                   提取共性的 system_instruction 和 output_format 模式。
                   生成一个 PromptTemplateContent。"
        - 输出：候选 PromptTemplateContent
      quality_check: 候选模板在 source_runs 的 task_view 上重新生成输出，
                     与原始 model_output 比较（语义相似度 > 0.8 为合格）

    action_pattern 提取：
      input:  source_runs 中的 Action 序列（ActionDispatched events 按时序排列）
      method: 序列模式挖掘
        - 对每条 Run 提取 action_kind 序列（如 [web_search, doc_parse, summarize, web_search, synthesize]）
        - 使用频繁子序列挖掘（如 PrefixSpan）提取出现频率 > 60% 的公共子序列
        - 将公共子序列转化为 ActionPatternContent
      quality_check: 提取的 pattern 在 source_runs 上回放，验证 postcondition 满足率 > 80%

    decision_rule 提取：
      input:  source_runs 中 Route Engine 的决策记录（route_rationale + actual_outcome）
      method: 规则归纳
        - 从成功决策中提取 (condition → action) 对
        - 按 condition 聚类，选取高频 + 高成功率的规则
        - 生成 DecisionRuleContent
      quality_check: 规则在 source_runs 的决策点上回放，正确率 > 85%
      
  Step 3: 候选 Skill 封装
    将提取结果封装为 SkillRecord（status=draft）+ SkillContent
    ChangeSet.change_scope = skill_only
    进入 evaluating 阶段（使用 EvalDataset 验证）

触发条件：
  - 反馈触发（累积 M 个 approved 人工评价）最适合触发 skill_extraction
  - 手动触发：evolve_manager 指定 generation_strategy=skill_extraction

实现成本：中等
  - prompt_template 提取需要一次 meta-LLM 调用（成本可控）
  - action_pattern 提取是纯算法（PrefixSpan 等，无 LLM 成本）
  - decision_rule 提取可用规则归纳算法或 LLM 辅助
```

**策略 4: knowledge_discovery（知识发现——从 Run 结果中主动发现新知识）**

```
流程：
  1. 信号识别：扫描近期 Run 中反复出现的模式
     - 多个 Run 在同一类 evidence 上产生矛盾（contradictory_evidence 频率 > N）
     - 多个 Run 在同一 Stage 的同一条件下选择了相同的非默认路径
     - Human Gate C 的 free_form_comment 中反复提到相同的领域概念
  2. 知识候选生成：
     KnowledgeCandidate:
       knowledge_type:   semantic | procedural
       content_summary:  str        # 候选知识的自然语言描述
       evidence_refs:    [str]      # 支持该知识的 Run evidence 引用
       confidence:       float      # 初始置信度（基于支持 evidence 的数量和一致性）
       proposed_by:      auto_discovery | human_annotation
  3. 知识验证：
     - 候选 Knowledge 进入 ChangeSet（change_scope=knowledge_only）
     - 在 evaluating 阶段：验证引入该 Knowledge 后，相关 task_family 的
       acceptance_criteria_pass_rate 不下降超过 3%（§26.4 的质量门）
  4. 晋升后写入 KnowledgeStore（§26.1 的 KnowledgeRecord）

触发条件：
  - 质量触发（成功率下降可能意味着需要新知识）
  - on_signal 触发（外部变化信号，如行业规则更新）

实现成本：较高——需要 LLM 进行 meta-analysis 和知识抽象
```

**策略选择矩阵：**

| 触发类型 | 推荐策略 | 理由 |
|---|---|---|
| 手动触发 | human_guided | 运维人员已知改什么 |
| 质量触发 | parameter_tuning 或 knowledge_discovery | 先调参，调参无效再查知识 |
| 效率触发 | parameter_tuning | 效率问题通常是参数问题 |
| 反馈触发 | skill_extraction | 有足够优质轨迹供结晶 |
| 批量触发 | parameter_tuning → skill_extraction | 先调参，积累后结晶 |

**V1 实现路线：只实现 human_guided + parameter_tuning**。skill_extraction 和 knowledge_discovery 在 V2 实现（需要 meta-LLM 和序列挖掘能力）。

每个步骤失败时，EvolveSession 进入 `failed` 状态并记录 `failed_at_step` 字段：

#### EvolveSession 失败诊断（V2.4 新增）

```
EvolveSessionFailureRecord（failed 状态时写入）：
  failed_at_step:   collecting | evaluating | experimenting | promoting
  failure_reason:   str        # 人类可读的失败原因
  failure_detail_ref: str      # 详细日志引用（如评估报告、实验统计结果）
  resumable:        bool       # 是否可以从该步骤 resume（而非重启整个 session）
  resume_hint:      str        # 若 resumable=true，给出 resume 前需要修复的条件

per-step 常见失败原因与 resumable 判定：
  collecting_failed:
    - EvalDataset 不存在或样本不足（min_evaluation_sample_size）→ resumable=true，补充数据集后 resume
    - 数据采样服务不可达 → resumable=true，等待服务恢复后 resume
  evaluating_failed:
    - QualityGate 未通过（delta 不足） → resumable=false，需重新生成 ChangeSet
    - 离线评估超时 → resumable=true，reset 到 evaluating 步骤重试
  experimenting_failed:
    - 实验组错误率超过 auto_on_degradation 阈值 → resumable=false，触发自动回滚
    - 实验超时未达到 min_experiment_runs → resumable=true，延长 experiment_timeout 后 resume
  promoting_failed:
    - 晋升时 policy_version 冲突（另一个 Evolve 同期晋升了同类型 policy） → resumable=true，重新计算 baseline 后 resume
    - universal Skill 竞争冲突（见下方） → resumable=true，等待竞争 session 完成后 resume

get_evolve_session() 在 failed 状态返回的完整信息：
  { status, failed_at_step, failure_reason, resumable, resume_hint, failure_detail_ref }
```

#### 并发 EvolveSession 对 universal Skill 的竞争检测（V2.4 新增）

```
universal Skill 晋升锁：
  - Skill Registry 对每个 universal skill_id 维护一个晋升锁（promoting_session_id）
  - EvolveSession 进入 promoting 步骤时，对所有将要晋升的 universal skill_id 申请锁
  - 申请失败（锁被其他 session 持有）：
    当前 session 进入 promoting_blocked 子状态，等待锁释放
    等待超时（默认 24h）后 → EvolveSession failed，failed_at_step=promoting，resumable=true
  - 锁持有时间上限：promoting 步骤完成后立即释放，最长持有 4h（防死锁）

per-family Skill（private/shared）不参与锁机制，各 family 的 Evolve 相互独立。
```

#### cross_component ChangeSet 的 promoting 原子性（V2.5 新增）

`cross_component` ChangeSet 可能同时修改 Skill 和 Policy。若 Skill 晋升成功但 Policy 晋升失败，系统处于不一致状态。

```
promoting 步骤的两阶段提交：
  Phase 1（prepare）：
    - 对所有待晋升的 Skill 和 Policy 申请晋升锁（不实际写入）
    - 任一锁申请失败 → abort Phase 1，释放已获得的锁，进入 promoting_blocked
  
  Phase 2（commit）：
    - 所有锁获取成功后，原子写入所有晋升记录
    - 若 commit 过程中部分写入成功部分失败：
      已成功的晋升不回滚（因为已有 Run 可能在使用新版本），
      但 EvolveSession 标记为 promoting_partial_failure
      记录 { promoted: [refs], failed: [refs] }
      需要运维通过 resume_evolve_session() 手动重试 failed 部分

原则：宁可部分晋升（系统可继续工作，只是新旧混用），也不全部回滚（导致实验白做）。
但 promoting_partial_failure 必须触发告警，因为 Skill 和 Policy 版本不匹配可能影响 Run 质量。
```

#### A/B 实验流量分配策略（V2.3 新增）

```
ExperimentConfig:
  experiment_id:         稳定唯一标识
  control_policy:        对照组 policy version（旧版）
  treatment_policy:      实验组 policy version（新版）
  traffic_split:         实验组流量比例（0.0-0.5，上限 50% 防止风险过于集中）
  allocation_unit:       run_id | task_submitter_id
                         # run_id: 每个 Run 独立随机分配（适合无状态 policy 测试）
                         # task_submitter_id: 同一提交者的 Run 始终进入同一组（适合有用户感知的 policy 测试）
  allocation_seed:       int   # 确定性分配种子，保证同 run_id 重放进入同一组
  min_experiment_runs:   int   # 最少 Run 数后才允许统计（防止早期偶然数据）
  experiment_timeout:    duration  # 实验最长持续时间（到期自动评估是否达到统计显著性）

分配算法：
  group = hash(allocation_unit_value, allocation_seed) % 100
  if group < traffic_split * 100: treatment
  else: control
```

**实验隔离约束**：
- 同一 task_family 同时只允许一个活跃 A/B 实验（防止 policy 组合污染）
- `allocation_unit=task_submitter_id` 时，同一提交者不得在实验期间切组
- 实验组和对照组的 Run 均写入各自的 `policy_version` 冻结记录，事后可按组聚合指标
- 实验成本预算：若实验组 `avg_token_per_run` 较对照组增加超过 30%，自动暂停实验并告警（防止 deep_analysis 类实验费用爆炸）

每步骤幂等：EvolveSession 崩溃后可从当前状态节点恢复，不重复执行已完成步骤。

#### 离线评估方法（V2.6 新增）

Pipeline 中的"离线评估"步骤需要一种可操作的方法来回答："候选 ChangeSet 比 baseline 好多少？"。定义三种方法，按成本递增：

```
EvolveSession 新增字段：
  evaluation_method:   route_replay | counterfactual | full_simulation

方法 1: route_replay（最轻量，V1 默认）

  原理：只重放 Route Engine 的决策，不重跑 Action
  
  ���入：
    - EvalDataset 中的 RunSnapshot（含每个决策点的 task_view_id）
    - baseline PolicyVersionSet
    - candidate PolicyVersionSet（或候选 Skill）
  
  流程：
    for each run_snapshot in eval_dataset:
      for each decision_point in run_snapshot.trajectory_summary:
        # 从 payload store 加载历史 Task View
        historical_task_view = load_task_view(decision_point.task_view_id)
        
        # 用 baseline policy 调用 Route Engine
        baseline_output = route_engine(historical_task_view, baseline_policy)
        
        # 用 candidate policy 调用 Route Engine
        candidate_output = route_engine(historical_task_view, candidate_policy)
        
        # 比较：candidate 的决策是否与实际成功路径一致
        score_baseline = alignment(baseline_output, decision_point.actual_outcome)
        score_candidate = alignment(candidate_output, decision_point.actual_outcome)
    
    # 聚合：candidate 的平均 alignment 是否高于 baseline + min_success_rate_delta
  
  alignment 定义：
    - 若 actual_outcome = succeeded：candidate 是否也选择了该路径？→ 1.0
    - 若 actual_outcome = failed：candidate 是否避开了该路径？→ 1.0
    - 部分匹配按比例评分
  
  限制：
    - 只衡量 Route Engine 决策质量，不衡量 Skill prompt_template 的产物质量
    - 假设历史 Task View 仍然有效（若 Knowledge 已变化，结论可能失真）
    - 适合 parameter_tuning 类 ChangeSet

方法 2: counterfactual（中等成本）

  原理：让 LLM 在历史上下文中评估"如果使用新策略/Skill，结果会如何"
  
  流程：
    for each run_snapshot in eval_dataset:
      # 构建 counterfactual prompt
      prompt = """
        以下是一个已完成的任务执行记录：
        任务目标：{task_contract.goal}
        实际执行路径：{trajectory_summary}
        实际结果：{final_outcome}
        
        现在有��个候选变更：{changeset_description}
        
        问题：如果在执行时使用了这个变更，结果会更好还是更差？
        评分（-1 到 +1）：-1=明显更差，0=无变化，+1=明显更好
        理由：...
      """
      counterfactual_score = llm_evaluate(prompt)
    
    # 聚合：平均 counterfactual_score > 0 且通过 QualityGate
  
  限制：
    - LLM 的 counterfactual reasoning 可靠性有限
    - 成本：每个 RunSnapshot 需要一次 LLM 调用
    - 适合 skill_extraction 类 ChangeSet（需要评估 prompt_template 质量）
  
  可靠性保证：
    - counterfactual 评分必须与 §21.2 的 confidence 校准一起验证
    - 若 counterfactual 与后续 A/B 实验结果不一致（预测 +0.3 但实验 -0.1），
      记录 counterfactual_drift，降低后续 counterfactual 方法的可信权重

方法 3: full_simulation（最高成本，仅用于高价值 family）

  原理：在沙箱中完整重跑 Run
  
  流程：
    for each run_snapshot in eval_dataset (sample ≤ 10):
      create_run(
        task_contract = run_snapshot.task_contract_ref,
        replay_mode = dry_run,
        policy_versions = candidate_policy_set,
        llm_mode = fixture_replay       # 使用 §24.2 LLM Fixture
        capability_mode = mock           # 使用 Mock Capability
      )
      # 等待 Run 完成，比较 acceptance_criteria_pass_rate
  
  限制：
    - 需要所有历史 Run 都有录制的 LLM Fixture
    - Mock Capability 可���无法精确模拟真实行为
    - 成本高（每个 RunSnapshot 消耗完整 Run 的 token）
    - 仅推荐用��� cross_component ChangeSet 的最终验证

方法选择矩阵：
  | generation_strategy  | 推荐 evaluation_method |
  |---|---|
  | human_guided         | route_replay（快速验证手动调参效果） |
  | parameter_tuning     | route_replay（参数变更只影响路由决策） |
  | skill_extraction     | counterfactual（需要评估 Skill 对产物质量的影响） |
  | knowledge_discovery  | counterfactual（需要评估新知识对决策的影响） |
  | cross_component      | full_simulation（多组件联动需要端到端验证） |
```

### 10.2.1 冷启动 Bootstrap 策略（V2.2 新增）

新建 task_family 没有历史 Run，Evolve 无法触发。引入 Bootstrap 配置：

```
TaskFamilyBootstrap:
  bootstrap_policy:       manual | inherit_from_family | from_template
  seed_runs_required:     N       # Evolve 触发前需要积累的最少 Run 数
  initial_skill_refs:     [skill_id]   # 启动时预加载的 Skill（可来自其他 family）
  knowledge_inheritance:  task_family_id  # 从哪个 family 继承初始 Knowledge
  initial_stage_graph_template: template_id  # 使用哪个预置 Stage Graph 模板
```

- `inherit_from_family`：新 family 继承指定 family 的当前 active policy set 作为初始版本
- `from_template`：使用系统预置的标准 policy template 启动
- 在 `seed_runs_required` 满足前，Evolve 仅允许手动触发

### 10.3 Evolve ChangeSet 规约

```
EvolveChangeSet:
  change_set_id:          唯一标识
  change_scope:           skill_only | policy_only | knowledge_only | cross_component
  # cross_component: 跨核心面混改，需要额外的 cross_component_approval_ref
  cross_component_approval_ref: str  # change_scope=cross_component 时必填
  task_family:            适用 family
  candidate_refs:         候选版本引用列表
  baseline_ref:           对比基线引用
  evaluation_result_ref:  离线评估结果
  experiment_ref:         A/B 实验记录（选填）
  rollout_scope:          shadow | canary_10pct | canary_50pct | full
  rollback_policy:        auto_on_degradation(threshold_pct=N) | manual_only
  promoted_at:            晋升时间
  rolled_back_at:         回滚时间（若发生）
```

约束：
- `mixed` 已被移除，改为显式 `cross_component`，且必须携带审批引用
- `auto_on_degradation` 的降级阈值必须显式配置（如 `threshold_pct=10` 表示指标下降超过 10% 自动回滚）

### 10.3.1 量化质量门（V2.2 新增）

```
QualityGate:
  min_success_rate_delta:          +0.05   # 成功率至少提升 5 个百分点
  max_token_cost_regression:       +0.10   # 允许 token 消耗增加最多 10%
  min_acceptance_criteria_pass_rate: 0.85  # 验收标准通过率下限
  min_evaluation_sample_size:       50     # 离线评估最少样本量
  canary_evaluation_window:         7d     # canary 阶段观测窗口
  canary_min_run_count:             20     # canary 阶段至少完成的 Run 数
```

- 所有字段均可在 TaskFamilyConfig 中 per-family 覆盖
- `evaluation_policy` 本身的变更需要更高质量门（`min_evaluation_sample_size: 200`），防止评估标准的变化干扰业务指标基线

### 10.3.2 低频 task_family 的轻量进化路径（V2.6 新增）

A/B 实验需要 `canary_min_run_count: 20`。若 task_family 每周只有 5 个 Run，一次完整 A/B 实验需要 4+ 周——在低频场景下 Evolve 周期过长。定义轻量替代路径：

```
低频判定：task_family 的 avg_runs_per_week < canary_min_run_count / 2（默认 < 10）

低频进化路径（跳过 A/B 实验，用强化离线评估替代）：

  Pipeline 变体：
    Feedback 采集 → EvolveSession → ChangeSet 生成 → 
    **强化离线评估**（替代 A/B 实验）→ **人工审批**（替代自动晋升）→ 
    Policy Promotion → 存量 Run 升级

  强化离线评估规则：
    - evaluation_method 必须 ≥ counterfactual（不允许只用 route_replay）
    - min_evaluation_sample_size 提高到标准值的 2 倍（默认 100，因为没有 A/B 实验的在线验证）
    - QualityGate 的 min_success_rate_delta 提高到标准值的 1.5 倍
      （更严格的离线门来补偿缺少在线实验的风险）

  人工审批门（替代自动晋升）：
    - 离线评估通过 QualityGate 后，不自动进入 promoting
    - 触发一个特殊的 Evolve Gate（类似 Gate D）：
      evolve_manager 必须审批 ChangeSet 晋升
    - 审批时展示：evaluation_result 详情、候选 vs baseline 的对比数据、counterfactual 评分分布

  回退到标准路径：
    当 avg_runs_per_week 持续 4 周 ≥ canary_min_run_count / 2：
    自动切换回标准 A/B 实验路径（下次 EvolveSession 生效）
```

### 10.4 Evolve 数据清算规则

来自 Human Gate 的数据不得直接作为自动优化信号：

| Gate 类型 | 清算规则 |
|---|---|
| Gate A (contract correction) | 生成新 contract version，旧 branch 重做兼容检查 |
| Gate B (route direction) | 人工路由选择记录为辅助信号，不等价于模型路由成功证据 |
| Gate C (artifact review) | 人工编辑产物标记 `human_modified=true`，不用于纯模型 Skill 认证 |
| Gate D (final approval) | 只影响最终动作，不反证中间路由质量 |

---

## 11. 功能幂等设计

### 11.1 幂等键构造规则

所有幂等键由 hi-agent 生成，格式：`{run_id}/{action_id}/{attempt_id}`

- 同一动作重试时 `action_id` 不变，`attempt_id` 递增
- 外部系统收到相同幂等键时，必须返回已存在结果，不得重复执行

### 11.1.1 action_id 确定性生成算法（V2.2 新增）

action_id 必须可确定性重建，不依赖进程内随机数：

```python
action_id = deterministic_hash(
    run_id,
    stage_id,
    branch_id,
    action_semantic_key,      # 描述动作意图的稳定字符串，如 "search_arxiv_v1"
    action_sequence_number    # 该 branch 内的动作序号（从 agent-kernel 的 branch event log 中重建）
)
# 推荐算法：SHA-256 前 16 字节，base64url 编码
```

- `action_semantic_key` 由 Route Engine 在路由决策时确定，需保持稳定（不随重试变化）
- **action_semantic_key 必须在首次生成时持久化到 BranchProposal 的事件日志中**（V2.5 新增）：崩溃恢复后从事件日志中读取已持久化的 semantic_key，不得重新调用 Route Engine 生成（LLM-based Route Engine 可能产生不同值）。格式约束：`{capability_id}_v{schema_major}`（见 §8.1），不允许 LLM 自由文本
- `action_sequence_number` 从 agent-kernel 的 branch 事件流中重建，而非进程内计数器
- 幂等键有效期：与 Run 的保留期一致（Run 被 archive 后幂等键不再保证）

**action_sequence_number 重建的边界条件（V2.4 新增）**：

```
重建流程：
  action_sequence_number = count(ActionDispatched events WHERE branch_id = current_branch_id
                                  AND occurred_at < current_action_time)

事件部分丢失的检测与处理：
  情景 A：事件流连续（无 gap）
    → 直接重建，sequence_number = count of prior ActionDispatched events

  情景 B：事件流存在 gap（event_id 序列不连续）
    检测方式：agent-kernel 的 query_trace_runtime() 返回 event_log_integrity: { has_gap: bool, gap_at: event_id }
    处理策略：
      - has_gap=true 且 gap 在当前 action 的时间范围内：
        hi-agent 不得继续重建 action_id，必须调用 request_event_log_repair(branch_id)
        修复完成前 Branch 保持 waiting 状态
      - has_gap=true 但 gap 在更早的历史（不影响当前 action 序号）：
        允许继续，在审计日志中记录 partial_event_log 警告

  情景 C：事件流完全不可用（agent-kernel 故障）
    → 进入 §13.5 的网络分区降级模式，不尝试重建 action_id
```

### 11.1.2 LLM 调用幂等语义（V2.2 新增）

LLM 调用天然非确定，但需要 checkpoint 语义：

```
LLMCallRecord:
  call_id:        deterministic_hash(run_id, task_view_id, call_sequence_number)
  task_view_id:   本次调用使用的 Task View
  model:          实际调用的模型
  called_at:      时间戳
  result_ref:     LLM 输出的存储引用（由 agent-kernel 持久化）
  token_used:     实际消耗 token 数
```

重试语义：
- 若 `call_id` 已有 `result_ref`（之前成功完成），直接返回缓存结果，不重新调用 LLM
- 若之前调用失败（无 result_ref），生成新的 `call_id`（call_sequence_number 递增）重新调用
- **缓存命中不等于幂等**：LLM 调用结果缓存是性能优化，不应被设计为业务逻辑的幂等依赖

### 11.2 状态变更 API 的幂等语义（V2.1 新增）

| API | 幂等语义 |
|---|---|
| `open_stage(stage_id)` | 重复调用时，若 stage 已存在则返回已有结果，不报错 |
| `open_branch(branch_id)` | 同上 |
| `open_human_gate(gate_ref)` | 同上 |
| `mark_stage_state(stage_id, state)` | 若已在目标状态则 no-op；非法转移则返回错误 |
| `record_task_view(task_view_id)` | 重复调用返回已有 task_view_id，不重复创建 |
| `signal_run(signal)` | 同一 signal（含 signal_id）重复投递时幂等消费 |

### 11.3 Replay 与重复启动区分（V2.1 新增）

```
StartRunRequest:
  run_id:      (已有)
  replay_mode: none | replay_from_checkpoint | dry_run
  replay_nonce: 本次 replay 的唯一 nonce（避免幂等键碰撞）
```

- `replay_mode=none`：正常启动，run_id 重复时返回已有 Run
- `replay_mode=replay_from_checkpoint`：从断点重放，产生新的 attempt context
- `replay_mode=dry_run`：不产生外部副作用的演练模式

### 11.3.1 外部系统不支持幂等键时的降级策略（V2.2 新增）

外部系统不总是支持幂等键协议。降级规则：

| side_effect_class | 外部系统无幂等支持时的处理 |
|---|---|
| `read_only` | 直接重试，无风险 |
| `local_write` | 先查询确认是否已执行，再决定是否重试 |
| `external_write` | 强制进入 `effect_unknown`，触发恢复面仲裁 |
| `irreversible_submit` | 拒绝重试，升级为 `unsafe_action_blocked`，进入人工处理 |

### 11.4 副作用治理

| effect_class | 含义 |
|---|---|
| `read_only` | 无写副作用 |
| `idempotent_write` | 幂等写，可安全重试 |
| `compensatable_write` | 可通过补偿操作撤销 |
| `irreversible_write` | 不可撤销，需审批 |

| side_effect_class | 默认重试 | 默认恢复方向 |
|---|---|---|
| `read_only` | 可自动重试 | 重试或换路径 |
| `local_write` | 可重试（需幂等键） | 回滚或覆盖 |
| `external_write` | 谨慎重试（先确认是否已生效） | 查外部状态后仲裁 |
| `irreversible_submit` | 默认不自动重试 | 审计 + 人工处理 |

---

## 12. 可观测设计

### 12.1 三层可观测数据

| 层次 | 数据类型 | 归属 |
|---|---|---|
| **事件日志** | 不可变的结构化事件流，支持回放 | agent-kernel |
| **运行时投影** | 从事件日志派生的当前状态快照 | agent-kernel |
| **业务指标** | 面向质量与效率的聚合度量 | hi-agent |

### 12.1.1 事件 Schema 最小定义（V2.2 新增）

事件日志中每条记录必须符合以下 Envelope：

```
EventEnvelope:
  event_id:             全局唯一（推荐 ULID，按时间排序）
  event_type:           枚举（见下方事件类型目录）
  schema_version:       本事件类型 payload 所符合的 schema 版本
  run_id:               所属 Run
  stage_id:             所属 Stage（可选）
  branch_id:            所属 Branch（可选）
  action_id:            所属 Action（可选）
  occurred_at:          事件发生时间（UTC ISO-8601）
  produced_by:          hi-agent | agent-kernel | agent-core
  trace_context:        TraceContext（用于分布式追踪关联）
  payload_ref:          事件 payload 的引用（不内联大对象）

事件类型目录（最小集合）：
  RunStarted | RunCompleted | RunFailed | RunAborted
  StageActivated | StageCompleted | StageFailed | StageBlocked
  BranchProposed | BranchAccepted | BranchPruned | BranchSucceeded | BranchFailed
  ActionDispatched | ActionAcknowledged | ActionSucceeded | ActionFailed | EffectUnknown
  HumanGateOpened | HumanGateResolved
  TaskViewRecorded | TaskViewBound
  PolicyVersionChanged
  EvolveSessionStarted | EvolveSessionCompleted | ChangeSetPromoted | ChangeSetRolledBack
```

Schema 演进：`schema_version` 变更时旧 schema 版本继续支持回放，不强制迁移历史事件。

**event_id 生成责任与唯一性（V2.5 新增）**：
- `event_id` 推荐 ULID（按时间排序且全局唯一），**由事件的 `produced_by` 方生成**
- hi-agent 产生的事件（如 BranchProposed, TaskViewRecorded）由 hi-agent 生成 event_id
- agent-kernel 产生的事件（如 RunStarted, ActionAcknowledged）由 agent-kernel 生成 event_id
- agent-core 不直接写入事件日志——**Capability 执行结果通过 CapabilityResponse（§31）返回给 hi-agent，由 hi-agent 转写为 ActionSucceeded/ActionFailed 事件**。这保证事件日志只有两个写入者（hi-agent, agent-kernel），简化一致性管理。

**告警通道规范（V2.5 新增）**：

```
NotificationBackend 接口（hi-agent 配置）：
  type:          webhook | slack | pagerduty | email
  endpoint:      str       # webhook URL / Slack channel / PagerDuty service key
  severity_filter: [critical | warning | info]  # 只推送指定严重度的告警

告警严重度映射：
  critical：Gate D 超时未审批、promoting_partial_failure、run_success_rate < SLO - error_budget
  warning：recovering_runs > 5%、budget_utilization > 80%、capability circuit breaker open、
           calibration_error > 0.15、soc_violation
  info：EvolveSession completed、policy_version deprecated、config_version changed

hi-agent 在 /health/status 端点中同时暴露 active_alerts: [{ severity, message, since }]
```

#### 各事件类型 payload 最小 schema（V2.3 新增）

`payload_ref` 指向独立的 payload store（由 agent-kernel 管理，生命周期与 Run 保留期一致）。每类事件的 payload 最小字段如下：

```
RunStarted.payload:
  task_family:          str
  task_contract_ref:    str      # TaskContract 存储引用
  policy_versions:      PolicyVersionSet
  initial_stage_id:     str
  initiated_by:         str      # run_submitter 的身份标识

RunCompleted.payload:
  final_stage_id:       str
  acceptance_result_ref: str     # AcceptanceCriteriaEvaluator 结果引用
  total_token_used:     int
  total_wall_clock_sec: int

RunFailed.payload:
  failure_code:         str      # 见 §17 Failure Taxonomy
  failure_stage_id:     str
  failure_branch_id:    str (可选)
  error_detail_ref:     str      # 详细错误信息引用

StageActivated.payload:
  stage_id:             str
  stage_name:           str
  transition_from:      str (可选)  # 从哪个 Stage 转移来

ActionDispatched.payload:
  action_id:            str
  capability_id:        str
  effect_class:         str
  side_effect_class:    str
  action_semantic_key:  str

ActionSucceeded.payload:
  action_id:            str
  result_ref:           str      # Action 执行结果引用
  token_used:           int (可选，若为 LLM 调用)
  duration_ms:          int

ActionFailed.payload:
  action_id:            str
  failure_code:         str
  retry_allowed:        bool

EffectUnknown.payload:
  action_id:            str
  side_effect_class:    str
  arbitration_required: bool     # 是否进入恢复面仲裁

HumanGateOpened.payload:
  gate_ref:             str
  gate_type:            contract_correction | route_direction | artifact_review | final_approval
  opened_by:            hi-agent | agent-kernel
  context_ref:          str      # 供审批人查阅的上下文引用

HumanGateResolved.payload:
  gate_ref:             str
  resolution:           approved | rejected
  resolved_by:          str      # gate_approver 身份标识
  comment_ref:          str (可选)

EvolveSessionStarted.payload:
  session_id:           str
  task_family:          str
  change_scope:         str
  trigger_type:         str      # 触发类型（batch | quality | efficiency 等）

ChangeSetPromoted.payload:
  change_set_id:        str
  rollout_scope:        str
  promoted_policy_versions: [{ policy_type, old_version, new_version }]
```

**调试模式**：在 hi-agent 的运行时配置中支持 `event_log_debug_mode: true`，该模式下将 payload 内联到 EventEnvelope（`payload_inline` 字段），不写 payload_ref，仅用于开发/测试环境，生产环境禁止开启。

#### payload store 物理规范（V2.4 新增）

```
payload store 设计：
  物理位置：与 event log 分开存储（event log 是追加的结构化流，payload store 是对象存储）
  推荐存储：对象存储（如 S3 / MinIO / GCS），按 {run_id}/{event_id}.payload 路径组织
  访问方式：hi-agent 通过 agent-kernel 提供的 PayloadStore 接口访问（不直接访问底层存储）

PayloadStore 接口（由 agent-kernel 实现）：
  write_payload(event_id: str, payload: bytes) -> payload_ref: str
  read_payload(payload_ref: str) -> bytes
  # payload_ref 格式："{store_bucket}/{run_id}/{event_id}"，不含凭证信息

生命周期：
  - payload 与 Run 的保留期对齐（Run archived 后，payload 随之进入 TTL 清理队列）
  - 清理是异步的（先删 event log 中的引用，再删 payload 对象）
  - 若 payload_ref 指向已清理的对象：read_payload() 返回 PayloadExpired 错误（不是 404）

完整性：
  - write_payload() 写入时计算 SHA-256 checksum，存储在 event log 的 EventEnvelope 中（payload_checksum 字段）
  - read_payload() 返回时验证 checksum，不一致返回 PayloadCorrupted 错误
```

### 12.2 核心指标定义

**任务质量指标：**

| 指标 | 说明 | 建议告警阈值 |
|---|---|---|
| `run_success_rate` | 按 task_family 统计的完成率 | < 80% |
| `acceptance_criteria_pass_rate` | 验收标准通过率 | < 85% |
| `human_gate_intervention_rate` | 各 Gate 类型的触发频率 | Gate A > 20% |
| `branch_pruning_ratio` | 被剪枝的 Branch 比例 | > 70% |

**效率指标：**

| 指标 | 说明 | 建议告警阈值 |
|---|---|---|
| `avg_stage_duration` | 各 Stage 平均耗时 | P99 > 2× 基线 |
| `avg_token_per_run` | 单 Run 平均 token 消耗 | > 120% 预算 |
| `avg_model_calls_per_run` | 单 Run 平均模型调用次数 | > 3× 基线 |
| `llm_gateway_p99_latency` | LLM Gateway 99 分位延迟 | > 10s |
| `callback_wait_duration` | external_callback 等待时长 | P99 > 30min |

**认知质量指标（V2.2 新增）：**

| 指标 | 说明 | 建议告警阈值 |
|---|---|---|
| `context_window_utilization` | Task View 已用 token / 最大 token | > 90% |
| `task_view_truncation_rate` | must-keep evidence 被截断的比例 | > 1% |
| `task_view_build_failure_rate` | Task View 构建失败率 | > 0.1% |
| `task_view_model_downgrade_rate` | 因窗口不足而切换更大模型的比例 | > 5% |

**健康指标：**

| 指标 | 说明 | 建议告警阈值 |
|---|---|---|
| `active_runs_count` | 当前活跃 Run 数 | > 容量上限 × 80% |
| `recovering_runs_count` | 当前恢复中 Run 数 | > active_runs × 5% |
| `watchdog_trigger_rate` | no_progress 触发频率 | > 10 次/小时 |
| `failure_code_distribution` | 各 failure_code 占比 | 任一 code > 20% |

### 12.2.1 SLO 参考值表（V2.2 新增）

以下为跨 task_family 的系统级 SLO 参考，各 family 可在 TaskFamilyConfig 中覆盖：

| SLI | SLO 目标 | 错误预算（30天） |
|---|---|---|
| run_success_rate | ≥ 85% | 允许 15% 失败 |
| task_view_truncation_rate | ≤ 1% | 允许 1% 截断 |
| llm_gateway_p99_latency | ≤ 10s | 允许 1% 超标 |
| recovering_runs / active_runs | ≤ 5% | 允许 5% 时间超标 |
| task_completion_p95_duration | ≤ task_family 基线 × 2 | 允许 5% 超标 |

**Skill 使用追踪指标（V2.3 新增）：**

| 指标 | 说明 | 建议告警阈值 |
|---|---|---|
| `skill_hit_rate` | 路由时 Skill 被应用的比例（按 task_family） | < 30%（说明 Skill 覆盖不足） |
| `skill_success_contribution` | 使用了 Skill 的 Run 相对未使用的 Run 成功率提升 | < 0%（Skill 无正向贡献） |
| `skill_staleness_rate` | 处于 `suspect` 或 `expired` 状态的 Skill 比例 | > 20% |
| `branch_pruning_by_code` | 按 prune_code 分类的剪枝率（见 §21.1） | `budget_exhausted` 剪枝率 > 50% |

注：`branch_pruning_ratio > 70%` 的告警需结合 `branch_pruning_by_code` 判断：若主要剪枝原因是 `insufficient_evidence` 或 `dominated_by_sibling`，属正常 Route Engine 效率；若主要原因是 `budget_exhausted`，则 CTS 预算可能过紧。

**轨迹与记忆与知识指标（V2.8 新增）：**

| 指标 | 说明 | 建议告警阈值 |
|---|---|---|
| `avg_propagated_score_per_family` | 按 task_family 的平均轨迹质量信号 | 连续 3 天下降 > 10% |
| `l1_compression_latency_p99` | L1 Stage 压缩延迟 | > 5s |
| `l1_fallback_rate` | L1 压缩失败使用 fallback 的比例 | > 5% |
| `knowledge_page_staleness_rate` | KnowledgeWiki 中 suspect/expired 页面占比 | > 20% |
| `knowledge_ingest_failure_rate` | Inline ingest 失败率 | > 10% |
| `knowledge_page_count` | KnowledgeWiki 总页面数（per-family） | > 500（IndexPage 可能超 512 tokens） |
| `mcts_simulation_cost_per_cycle` | MCTS 模式下每路由周期的 rollout token 消耗 | > max_mcts_simulation_token_budget |

**指标必须支持的聚合下钻维度（V2.4 新增）**：

以下维度是分析 Evolve 效果的必要条件，指标采集时必须同时记录（不可事后重建）：

| 必须支持的 key | 用途 |
|---|---|
| `task_family` | 所有指标的基础维度 |
| `policy_version`（四类） | 区分哪个版本的 policy 导致失败/成功（A/B 实验分析） |
| `stage_id` | 识别哪个 Stage 是瓶颈（avg_stage_duration 必须按 stage 采集） |
| `model` | 分析模型切换对 token 成本和质量的影响 |
| `prune_code` | branch_pruning_ratio 的语境化分析 |

`policy_version` 维度的采集方式：每个 Run 启动时冻结的 `PolicyVersionSet` 必须作为标签附加到该 Run 产生的所有指标上。

### 12.3 分布式追踪

所有跨层操作必须携带统一 trace context：

```
TraceContext:
  trace_id:       全局追踪 ID（贯穿 hi-agent / agent-kernel / agent-core）
  span_id:        当前操作的 span
  run_id:         所属 Run（业务维度）
  stage_id:       所属 Stage（可选）
  branch_id:      所属 Branch（可选）
  action_id:      所属 Action（可选）
```

- 每次 LLM 调用独立 span，标注 task_view_id、selected_model、token_used
- 每次 Harness 调用独立 span，标注 action_id、effect_class、side_effect_class

### 12.3.1 异步 Callback 的 Trace 关联（V2.2 新增）

Callback 可能在原始 trace 结束数小时后到达，需通过元数据延续追踪链：

```
# 注册 callback 时（在 HarnessActionEnvelope 中）：
callback_ref:
  callback_id:    stable callback identifier
  trace_id:       原始操作的 trace_id（携带到回调元数据中）
  run_id:         所属 Run

# Callback 到达时：
agent-kernel 从 callback_ref 中提取 trace_id
以 trace_id 为父，创建新 span：CallbackReceived
后续处理 span 均挂在此延续链下
```

这确保一个跨 2 小时的 external_callback 等待仍可在追踪系统中完整还原时序。

### 12.4 TraceRuntimeView 时效性与刷新模型（V2.4 更新）

- `TraceRuntimeView` 由 agent-kernel 从 durable state 重建，`projected_at` 表示投影时间
- hi-agent 不应缓存超过 **10 秒**的 TraceRuntimeView 用于决策
- 若 `projected_at` 超过阈值，应重新查询，不应基于陈旧视图做路由决策

**刷新模型选择：主动 polling（而非 push）**

```
选择 polling 而非 push 的原因：
  - push 需要 hi-agent 维护持久订阅状态，在网络分区恢复后可能遗漏事件
  - TraceRuntimeView 是只读查询，polling 的实现更简单、可测试
  - 10s 刷新周期对路由决策足够（Route Engine 耗时通常 > 1s）

polling 实现约束：
  polling_interval:     5s（默认，可在 hi-agent 运行时配置中调整）
  max_polling_interval: 10s（超过则视为陈旧视图，不得用于路由决策）
  burst_protection:     同一 run_id 的查询频率不超过 1 次/s（防止 Route Engine 循环调用导致查询风暴）

  若 query_trace_runtime() 返回 stale=true（kernel 的投影滞后于事件流超过 30s）：
    hi-agent 应在日志中记录警告，但不得直接失败 Run——允许继续使用当前视图，下次 polling 时重试
```

### 12.5 审计日志

以下操作必须写入不可变审计日志（与事件日志分开存储，面向合规）：

- Run 创建 / 终止 / 强制中止
- Human Gate 开启 / 结果写入
- policy version change_record
- Evolve ChangeSet 晋升 / 回滚
- 高风险 Action（`effect_class=irreversible_write`）执行

审计日志完整性保护要求：
- 写入后不可修改（append-only 存储）
- 访问需要 `system_admin` 角色或单独的 `audit_reader` 角色
- 存储层加密，密钥与数据分离管理
- 每日生成 hash 摘要，用于完整性验证

**审计日志与业务事件的时钟同步（V2.4 新增）**：

审计日志和事件日志是独立存储，存在时钟漂移风险（审计日志记录的时间戳可能与事件日志产生因果倒置）。

```
时钟同步方案：混合逻辑时钟（HLC）

每条审计日志记录必须包含：
  wall_clock_time:  UTC ISO-8601（物理时钟）
  logical_clock:    HLC 时间戳（格式：{physical_ms}.{logical_counter}，例如 "1743843600000.42"）
  causal_event_id:  触发本次审计记录的业务事件 event_id（可选，存在时可重建因果关系）

HLC 规则：
  - 写入审计日志前，从 agent-kernel 获取当前 HLC 值（同一个 HLC 时钟覆盖事件日志和审计日志）
  - logical_clock 保证：同一进程内先发生的审计记录 logical_clock < 后发生的记录
  - 跨进程比较时：causal_event_id 链接到事件日志的 event_id，以此重建因果顺序

实现最小要求：
  若不实现完整 HLC，最低要求是 causal_event_id 字段——
  只要审计记录与触发它的业务事件有 event_id 关联，即使时间戳有偏差也可正确重建因果顺序
```

---

## 13. 可运维设计

### 13.1 Run 管理 API

```
# 查询接口
list_runs(filter: RunFilter) -> [RunSummary]
  RunFilter: { task_family, run_state, created_after, created_before, page_size, cursor }

# 控制接口（幂等）
cancel_run(run_id, reason) -> None         # 需要 run_operator 角色
batch_cancel_runs(filter: RunFilter, reason, options?: BatchCancelOptions) -> BatchCancelResult  # 需要 run_operator 角色
  BatchCancelOptions: {
    idempotency_key:  str    # 批次幂等键，重复提交返回已有结果（V2.4 新增）
    fail_fast:        bool   # 任一取消失败是否中止批次（默认 false，尽力取消）
  }
  BatchCancelResult: {       # V2.4 新增，明确部分成功语义
    batch_cancel_id:  str    # 本次批量取消操作的唯一标识
    cancelled:        [run_id]
    skipped:          [{ run_id, reason }]  # 已在终态（completed/failed/aborted）的 Run
    failed:           [{ run_id, error_code }]  # 取消操作本身失败的 Run
    partial_success:  bool   # true 时表示部分成功，可用 idempotency_key 重试以继续
  }
  # batch_cancel_runs 是幂等的：相同 idempotency_key 重复调用返回同一 BatchCancelResult
  # 部分成功场景：用相同 idempotency_key 重试，只对 failed 中的 run_id 重新尝试取消
force_complete_run(run_id, reason, override_token) -> None   # 需要 system_admin 角色

# 批量提交（V2.2 新增）
batch_start_runs(requests: [StartRunRequest], options: BatchOptions) -> BatchStartResult
  BatchOptions: {
    max_concurrent:      int    # 最大并发 Run 数
    fail_fast:           bool   # 任一失败是否中止批次
    deduplication_key:   str    # 批次幂等键，重复提交返回已有批次
  }
  BatchStartResult: {
    batch_id:   str
    started:    [run_id]
    failed:     [{ request_index, error_code, error_message }]
  }
```

### 13.2 Task Family 管理 API

```
register_task_family(config: TaskFamilyConfig) -> task_family_version
update_task_family(task_family, patch) -> task_family_version
get_task_family_config(task_family, version?) -> TaskFamilyConfig
list_task_families() -> [TaskFamilySummary]
validate_task_family_config(config: TaskFamilyConfig) -> ValidationResult  # V2.2 新增，注册前校验
```

Task Family 注册校验规则（V2.2 新增）：
- Stage Graph：无不可达节点、无死锁、至少一个终态节点
- Stage Graph：所有 Gate 触发条件有对应的 ReviewState 处理路径
- Capability refs：所有 `enabled_capabilities` 中的 capability_id 均在 Registry 中已注册且 `enabled=true`
- CTS 预算：所有必填字段 > 0；`max_active_branches ≤ max_total_branches`
- Bootstrap：`seed_runs_required ≥ 10`（防止过快触发 Evolve）

### 13.3 hi-agent 运行时配置热更新（V2.4 新增）

hi-agent 自身的运行时参数（独立于 TaskFamilyConfig）支持不重启热更新：

```
HiAgentRuntimeConfig（可热更新的参数集）：
  traceruntime_polling_interval:  duration  (默认 5s，范围 1s-10s)
  traceruntime_staleness_threshold: duration (默认 10s)
  graceful_shutdown_timeout:      duration  (默认 30s)
  event_log_debug_mode:           bool      (默认 false，生产环境不得为 true)
  capability_circuit_breaker_global_enabled: bool  (全局开关，可临时禁用所有熔断器)
  watchdog_interval:              duration  (no_progress 检测间隔，默认 5min)
  batch_cancel_max_concurrency:   int       (批量取消的最大并发 Run 数，默认 50)

热更新接口：
  PATCH /management/runtime-config
    body: { key: value, ... }   # 只传需要修改的字段
    requires: system_admin 角色
    response: { applied: [key], rejected: [{ key, reason }] }

约束：
  - 不在允许热更新列表中的参数（如 instance_id、kernel_endpoint）只能通过重启修改
  - 热更新成功后写入审计日志（causal_event_id = 本次请求 trace_id）
  - 热更新失败（如值超出范围）：返回 rejected，不部分应用

配置版本化（V2.5 新增）：
  - 每次成功的 PATCH 操作递增 config_version（单调递增整数）
  - response 返回 { applied, rejected, config_version }
  - GET /management/runtime-config 返回当前完整配置 + config_version
  - GET /management/runtime-config/history?last=N 返回最近 N 次变更记录
    每条记录包含 { config_version, changed_keys, changed_by, changed_at, causal_event_id }
  - 回滚：PATCH body 传入历史版本的完整配置即可（等价于"覆盖到指定版本"），
    但 config_version 不回退（只向前递增）
```

### 13.4 健康检查

hi-agent 暴露以下端点：

```
GET /health/live     -> 200 if process alive
GET /health/ready    -> 200 if ready to accept runs (kernel connected, capability registry loaded)
GET /health/status   -> JSON summary including:
  {
    kernel_connected: bool,
    kernel_manifest_version: string,
    capability_registry_loaded: bool,
    active_runs: int,
    recovering_runs: int,
    evolve_session_active: bool,
    instance_id: str,           # V2.2 新增
    run_ownership_count: int    # V2.2 新增：本实例持有的 Run 数
  }
```

### 13.4.1 容量规划估算模型（V2.5 新增）

```
单实例并发 Run 容量估算：
  max_concurrent_runs ≈ available_memory / per_run_memory_footprint

per_run_memory_footprint =
    working_memory_avg_size         # 典型值：2-10 MB（取决于 evidence 数量）
  + trace_runtime_view_cache_size   # 典型值：0.5-2 MB
  + in_flight_action_buffers        # 典型值：0.1-1 MB
  + overhead                        # 进程级开销分摊，约 50 MB / instance

示例：8 GB 可用内存，quick_task family（per_run ≈ 5 MB）：
  max_concurrent_runs ≈ (8192 - 50) / 5 ≈ 1600

示例：8 GB 可用内存，deep_analysis family（per_run ≈ 50 MB）：
  max_concurrent_runs ≈ (8192 - 50) / 50 ≈ 160

建议在 §24.7 的 concurrent_run_capacity 性能测试中校准实际值。
/health/status 中的 active_runs_count > max_concurrent_runs × 0.8 时触发扩容告警。
```

### 13.5 优雅停机

hi-agent 收到停机信号后：

1. 停止接受新的 Run 创建请求（`/health/ready` 返回 503）
2. 向 agent-kernel 注销实例心跳（触发 Run 孤儿检测，让其他实例接管）
3. 等待当前正在执行的模型调用和 Harness 调用完成（最长等待 `graceful_shutdown_timeout`，V2.5 更新：默认 30s，但自适应延长为 `max(30s, max_in_flight_capability_expected_p99_latency × 2)`，确保 deep_analysis 的长 LLM 调用有足够时间完成）
4. 将 active Runs 的最新状态 flush 到 agent-kernel
5. 退出

Run 在 agent-kernel 中保持 durable 状态，新实例启动后通过孤儿 Run 接管协议自动恢复。

### 13.6 多实例协调协议（V2.2 新增）

```
# 实例注册
on_startup:
  register_instance(instance_id, hostname, version) -> instance_registration
  start_heartbeat(interval=30s)

# Run 所有权绑定
on start_run():
  agent-kernel 将 run_id 绑定到 instance_id
  hi-agent 在本地维护 run → instance 映射

# 心跳失效检测
agent-kernel 维护实例心跳：
  3 次未收到心跳 → 标记实例为 suspect
  5 次未收到心跳 → 标记实例为 dead，所属 Run 标记为 orphan

# 孤儿 Run 接管
任何 healthy 实例可通过以下流程接管孤儿 Run：
  adopt_orphan_run(run_id, instance_id) -> AdoptResult
  # 接管后：从 agent-kernel 重建 Run 的 TraceRuntimeView，恢复 in-progress 状态
  # 接管是幂等的：若多个实例竞争接管同一 Run，agent-kernel 仲裁，只有一个实例成功
  # 仲裁机制：agent-kernel 对 adopt_orphan_run 使用乐观锁（CAS on run.owner_instance_id）
  # 失败一方收到 AdoptResult { success: false, owner: instance_id }，不得继续执行该 Run
```

#### agent-kernel 网络分区降级行为（V2.3 新增）

当 hi-agent 无法连接 agent-kernel 时（与实例故障不同），必须进入**受控降级模式**：

```
KernelConnectivityState:
  connected      → 正常模式，所有操作通过 agent-kernel
  degraded       → 心跳连续失败 2 次（60s），进入降级模式
  partitioned    → 心跳连续失败 5 次（150s），进入分区模式

降级模式（degraded）行为：
  - 停止接受新 Run（/health/ready → 503）
  - 已在执行的 Run：
    * read_only / local_write Action：允许继续执行（不依赖 kernel 确认）
    * external_write Action：暂停，等待连接恢复后再分发
    * irreversible_submit Action：立即阻止，记录本地 pending_submit 队列
  - 每 30s 尝试重新连接，连接恢复后重放 pending_submit 队列

分区模式（partitioned）行为：
  - 所有 in-progress Run 标记为本地暂停状态（不写入 kernel，kernel 将检测为孤儿）
  - hi-agent 进入 safe mode：拒绝所有新的模型调用和 Harness 调用
  - 连接恢复后：
    1. 查询 agent-kernel 当前对这些 Run 的持久化状态
    2. 若 kernel 已将 Run 分配给其他实例：放弃本地状态，不干扰新 owner
    3. 若 kernel 仍记录本实例为 owner：重建 TraceRuntimeView，从最后持久化点继续

防脑裂保证：
  - hi-agent 在分区模式下不得执行任何 irreversible_write 或 irreversible_submit Action
  - 连接恢复后必须先通过 kernel 仲裁（verify_run_ownership）再恢复执行
```

### 13.7 EvolveSession 管理 API（V2.2 新增）

```
list_evolve_sessions(filter) -> [EvolveSessionSummary]
  filter: { task_family, status, created_after }

get_evolve_session(session_id) -> EvolveSessionDetail
  返回：当前 status、当前所处 Pipeline 步骤、评估进度、实验结果摘要

pause_evolve_session(session_id) -> None
  # 在当前 Pipeline 步骤完成后暂停，等待 resume

resume_evolve_session(session_id) -> None

abort_evolve_session(session_id, reason) -> None
  # 不回滚已完成的步骤，但停止继续推进
```

### 13.8 Secret 管理（V2.2 新增）

Capability 所需凭证通过 Secret Backend 管理，不在 CapabilityDescriptor 中存储内容：

```
SecretBackend 接口（由部署环境提供）：
  supported: vault | k8s_secrets | aws_secrets_manager | env_var（仅开发环境）

凭证注入流程：
  1. CapabilityDescriptor.credential_refs = [secret_id, ...]
  2. hi-agent 启动时从 SecretBackend 加载所有引用凭证
  3. 凭证以不可序列化的内存对象形式注入 Capability（不写入日志、不存入事件流）
  4. 凭证轮换：hot_update_policy=graceful_reload 的 Capability 支持无重启凭证刷新
     触发方式：SecretRotationSignal（通过 signal_run 或运维接口）
```

### 13.9 LLM Gateway 治理

由 agent-kernel 实现，hi-agent 通过 Run Start Envelope 传递配置意图：

```
LLMGatewayPolicy（在 Run Start Envelope 中声明）:
  model_preference:    首选模型
  fallback_models:     降级模型列表（按优先级排序）
  rate_limit_group:    限流分组（按 task_family 或 tenant）
  max_tokens_per_run:  单 Run 最大 token 预算
  cost_center:         成本归因标识
```

### 13.10 成本归因

每次 LLM 调用和 Harness 调用记录成本归因，并提供实时预算消耗视图：

```
CostRecord:
  run_id, task_family, stage_id, branch_id
  cost_center:          从 TaskContract 或 task_family 继承
  token_input:          输入 token 数
  token_output:         输出 token 数
  model:                实际使用模型
  capability_id:        Harness 调用时的能力 ID（可选）
  timestamp:            时间戳
  cumulative_run_cost:  本 Run 截至此刻的累计成本（V2.2 新增）
  budget_utilization:   cumulative_cost / max_tokens_per_run（V2.2 新增）
```

当 `budget_utilization > 0.8` 时，agent-kernel 应向 hi-agent 发送 budget_warning 信号，触发提前的路由决策（是否继续探索还是直接收敛）。

---

## 14. 运行时状态机

### 14.1 RunState

| 状态 | 语义 |
|---|---|
| `created` | 已建立，未进入执行 |
| `active` | 存在可执行 Stage 或 Branch |
| `waiting` | 因外部回调、人审或定时恢复而暂停 |
| `recovering` | 处理不确定结果或补偿策略 |
| `completed` | 任务达成终态且通过完成判定 |
| `failed` | 进入不可继续的失败终态 |
| `aborted` | 被显式终止 |

### 14.2 合法状态转移

| 当前 | 事件 | 下一状态 |
|---|---|---|
| `created` | `run_started` | `active` |
| `active` | `run_wait_requested` | `waiting` |
| `waiting` | `wakeup_received` | `active` |
| `active` | `recovery_required` | `recovering` |
| `recovering` | `recovery_resolved_continue` | `active` |
| `active` | `run_completed` | `completed` |
| `active` | `run_failed` | `failed` |
| `active` / `waiting` | `run_aborted` | `aborted` |
| `recovering` | `run_failed` | `failed` |

### 14.3 StageState

`pending → active ↔ blocked → completed / failed`

### 14.4 BranchState

`proposed → active → waiting → active → pruned / succeeded / failed`

> **V2.8 澄清**：BranchState 是 TrajectoryNode DAG 的路径视图（§6.2.1），不是独立状态机。Branch 的状态由路径上节点的 `TrajectoryNode.state` 聚合派生。`open_branch()` / `mark_branch_state()` API 保留向后兼容，内部映射为 TrajectoryNode 操作。

### 14.5 ActionState

`prepared → dispatched → acknowledged → succeeded / effect_unknown / failed`

关键区分：
- `acknowledged`：外部系统已受理
- `succeeded`：结果可确认，可采集 evidence
- `effect_unknown`：副作用不可确定，进入恢复面

### 14.6 WaitState / ReviewState

WaitState：`none | external_callback | human_review | scheduled_resume`

ReviewState：`not_required | requested | in_review | approved | rejected`

### 14.7 死路检测与快速失败（V2.5 新增）

当一个 Stage 内所有 Branch 均进入终态（pruned / failed）且 Route Engine 无法提议新 Branch 时，Run 陷入"死路"——没有可执行路径，但 RunState 仍为 `active`。

```
死路检测规则（每次 Branch 状态变更后触发）：
  if all branches in current_stage are terminal (pruned | succeeded | failed)
     AND no branch is succeeded:
    # 所有路径都失败/被剪枝，无一成功
    trigger: dead_end_detected

dead_end_detected 处理（按优先级）：
  1. 若 stage_revisit_count < max_revisit（§6.2 回退规则）：
     回退到前序 Stage，尝试不同的 evidence 采集路径
  2. 若已达 max_revisit：
     触发 Gate B（route_direction），请求人工指引
  3. 若 Gate B 超时（§32.3）且 confidence 全部 < 0.3：
     Run → failed，failure_code = no_viable_path
     
dead_end_detected 比 no_progress watchdog 更快：
  - watchdog 需要等待 watchdog_interval（默认 5min）才触发
  - dead_end_detected 在 Branch 状态变更后立即检查，通常 < 1s
```

---

## 15. 仲裁规范

### 15.1 callback vs timeout

1. callback 携带有效 `action_id/callback_id` 时优先
2. timeout 不得覆盖已确认 callback 结果
3. timeout 先发生进入 `effect_unknown` 后，callback 到达时由恢复面仲裁

### 15.2 human review vs scheduled resume

- `human_review` 高于 `scheduled_resume`
- `ReviewState != approved` 前，不得自动推进高风险动作

### 15.3 policy version changed while waiting

- 等待中 Run 恢复时默认继续使用冻结版本
- 中途切换必须产生 `change_record`，且在 replay 元数据中可见

### 15.4 acknowledged but no final result

1. 保持 `ActionState = acknowledged`，`WaitState = external_callback`
2. 到 watchdog 阈值后进入恢复评估，不直接重发
3. 是否允许重发取决于 `side_effect_class`

### 15.5 task contract revised while branches exist

1. 生成新 contract version
2. 所有存量 Branch 必须重新做兼容性检查
3. 兼容 Branch：保留并重新标注 contract version
4. 不兼容 Branch：标记为 `pruned_by_contract_change`

---

## 16. Human Gate 规范

| Gate 类型 | 触发条件 | 语义 |
|---|---|---|
| **Gate A** `contract_correction` | task 理解偏差、目标变更 | 修改 task contract |
| **Gate B** `route_direction` | 多条路径难以自动裁决 | 指导路径选择 |
| **Gate C** `artifact_review` | 中间产物有歧义或矛盾证据 | 审核/编辑产物 |
| **Gate D** `final_approval` | 高风险最终动作（`irreversible_submit`） | 批准最终提交 |

约束：
- Gate 打开必须 durable 记录
- Gate 结果必须显式写入运行时真相，不得隐式视为批准
- Gate D 打开时，`ReviewState` 必须为 `approved` 才允许执行最终动作

---

## 17. Failure Taxonomy

| failure_code | 主要用途 |
|---|---|
| `missing_evidence` | Task View 重建后检视、route 降级 |
| `invalid_context` | 上下文装配缺陷、模型调用前阻断 |
| `harness_denied` | 权限或安全策略阻断 |
| `model_output_invalid` | 模型输出不可执行，触发重试或降级 |
| `model_refusal` | 模型拒绝执行，触发替代模型或人工介入 |
| `callback_timeout` | 外部任务长期未完成，进入恢复面 |
| `no_progress` | watchdog 触发（需配置检测间隔） |
| `contradictory_evidence` | 触发 Human Gate C |
| `unsafe_action_blocked` | 安全阻断，进入审批流 |
| `budget_exhausted` | 触发 Gate B 或 CTS 终止 |

---

## 18. Task View 规范

### 18.1 责任边界

- **hi-agent**：语义选择、证据优先级、降级策略
- **agent-kernel**：引用记录、provider 封装、回放元数据
- **agent-core**：资源供给

### 18.2 生命周期

1. hi-agent 选择 Task View 引用（含 evidence_refs / memory_refs / knowledge_refs）
2. agent-kernel 执行 `record_task_view()`（只存引用，不存内容本体）
3. 模型调用发生
4. 产生 `decision_ref`
5. agent-kernel 执行 `bind_task_view_to_decision()`

### 18.3 完整性规则

- 若 must-keep evidence 无法放入窗口，**不得静默裁剪后继续运行**
- 必须触发降级（切换更大窗口模型）或人工介入
- Task View 选择策略通过 `task_view_policy_version` 版本化管理

### 18.4 Task View 优先级算法（V2.3 新增，**V2.8 声明：被 §25.3 分层构建流程取代**）

> **V2.8 说明**：以下 must_keep/should_keep/nice_to_have 裁剪算法是 V2.3-V2.6 的设计。V2.7 引入分层压缩记忆后，Task View 不再从 flat evidence 列表裁剪，而是从 L2→L1→L3→Knowledge 逐层加载。**权威的 Task View 构建流程见 §25.3。** 本节保留作为历史参考和"为什么 V2.7 要改"的 context。

Task View 构建时，hi-agent 按以下**规则驱动**的优先级对 evidence/memory/knowledge 进行排序和裁剪（不使用 LLM 评分，以保证确定性和 policy 可版本化）：

```
TaskViewPriorityAlgorithm:

1. 分类每个 evidence/memory/knowledge 为以下等级：
   must_keep:    本次模型调用的决策依据必须包含的内容
                 判定规则：
                   - acceptance_criteria 直接引用的 evidence
                   - 当前 Stage 的进入条件尚未满足的证明
                   - 当前 Branch 的 rationale 引用的 evidence
   should_keep:  对决策有较高相关性的内容
                 判定规则：
                   - 同 Stage 内本 Branch 已执行 Action 的结果
                   - 当前 task_family 的 active Skill 中引用的 Knowledge
   nice_to_have: 历史参考信息
                 判定规则：
                   - 其他 Branch 的结果（pruned_branch_summaries）
                   - Episodic Memory 中与当前 goal 语义相关的历史 episode
   exclude:      本次调用明确不需要的内容
                 判定规则：
                   - 已完成且 outcome 已被记录的 Stage 的详细 evidence
                   - confidence 处于 expired/archived 状态的 Knowledge

2. token 分配策略（按 task_view_policy 中的权重参数）：
   must_keep:    必须全部放入，超出时触发模型降级（§18.3）
   should_keep:  按时效性降序排列，填满剩余空间的 60%
   nice_to_have: 填满剩余空间的 30%
   系统保留:     10%（用于模型 system prompt 和格式化）

3. 相同优先级内的排序：
   - evidence：按 recorded_at 降序（最新优先）
   - memory：按 relevance_score（基于 task_goal 的关键词匹配，规则计算）降序
   - knowledge：按 confidence 降序
```

**排除 LLM 评分的理由**：Task View 构建是高频操作（每次模型调用前都执行），引入 LLM 评分会产生递归调用风险和延迟，且 LLM 评分难以版本化和确定性重放。所有判定规则均为结构化条件，可在 `task_view_policy` 中精确配置。

---

## 19. 身份规约

### 19.1 最小身份集合

`task_id / run_id / stage_id / branch_id / action_id / attempt_id / task_view_id / callback_id / gate_ref / change_set_id`

### 19.2 唯一性要求

- `run_id`：全局唯一
- `stage_id / branch_id / action_id`：同一 run 内唯一
- `attempt_id`：同一 action 内唯一
- `task_view_id`：全局唯一

### 19.3 生成责任

- hi-agent 生成：`task_id / stage_id / branch_id / action_id / task_view_id`
- agent-kernel 生成：commit / event / replay 相关内部身份

### 19.4 task_view_id 生成策略（V2.3 新增）

`task_view_id` 采用**确定性生成**，基于 Task View 的组成快照哈希：

```python
task_view_id = deterministic_hash(
    run_id,
    stage_id,
    branch_id,
    call_sequence_number,    # 本 branch 内的模型调用序号（从事件流重建）
    evidence_refs_hash,      # sorted(evidence_refs) 的哈希（排序保证幂等）
    policy_versions_hash     # PolicyVersionSet 的哈希
)
# 推荐算法：SHA-256 前 16 字节，base64url 编码，加前缀 "tv_"
# 示例：tv_aB3xQ7mNp2kRsT9w
```

**设计原则**：
- `task_view_id` 不得使用随机 UUID，必须可从 Run 的事件流确定性重建
- 相同 `evidence_refs` + 相同 `policy_versions` + 相同 `call_sequence_number` 必然产生相同 `task_view_id`（支持幂等重建）
- 若 evidence_refs 完全相同但 `policy_version` 不同（合法变更），产生不同 `task_view_id`，防止缓存跨 policy 版本污染
- `record_task_view()` 收到已存在的 `task_view_id` 时返回已有记录（幂等语义，§11.2）

---

## 20. 当前实现状态

### 20.1 已具备（基于 agent-kernel 当前状态）

- `StartRunRequest` 已支持 TRACE 元数据
- `policy_versions / initial_stage_id / task_contract_ref` 已进入启动链路
- `run.policy_versions_pinned` 已落账
- `TaskViewRecord` 持久化与 late-bind 已可用
- `open_stage / mark_stage_state / open_branch / mark_branch_state / open_human_gate` 已存在
- callback / timeout / recovery 基础仲裁已可用

### 20.2 V2.7 待实现项（优先级排序）

**阶段 0（Spike，2-3 天）**：见 Appendix B。验证 TaskView 延迟、状态机流转、幂等键闭环、死路检测。扩展 Spike 2 验证 Evolve inline 轨迹。

**阶段 1 MVP（第一个 Run 可跑通）：**

| 优先级 | 项目 | 维度 |
|---|---|---|
| **P0** | `query_run()` + `query_trace_runtime()` 稳定实现 | 可观测 |
| **P0** | action_id + task_view_id 确定性生成（§11.1.1, §19.4） | 功能幂等 |
| **P0** | action_sequence_number 事件 gap 检测（§11.1.1 边界条件） | 功能幂等 |
| **P1** | Capability Registry（含沙箱、热更新边界、熔断器§8.1） | 可扩展/可靠性 |
| **P1** | Capability 调用契约实现（§31）：gRPC 接口 + 幂等 + 超时 | 契约完整性 |
| **P1** | Route Engine 最小接口定义（§21） | 认知正确性 |
| **P1** | Task Family 配置管理 + 注册校验 | 可扩展/可运维 |
| **P1** | Event Schema + payload store（§12.1.1, §12.1.1 payload store 规范） | 可观测 |
| **P1** | 健康检��� / 优雅停机（自适应 timeout §13.5） / 多实例协调 + 网络分区降级（§13.6） | 可���维 |
| **P1** | 死路检测（§14.7） | 故障模型 |
| **P1** | MockKernel strict_mode 状态机验证（§24.1） | 可测试性 |
| **P1** | TrajectoryNode DAG 数据结构 + greedy 优化器（§6.2.1-6.2.2） | 轨迹优化 |
| **P1** | L1 Stage 压缩 + L2 Run Index 生成（§25.3） | 分层记忆 |
| **P1** | Task View 从分层记忆读取（§25.3 重写后的构建流程） | 分层记忆 |

**阶段 2 生产就绪���**

| 优先级 | 项目 | 维度 |
|---|---|---|
| **P0** | 认证与 RBAC 执行层（§28）：mTLS + JWT | 安全 |
| **P1** | Skill Registry 基础实现（含 retirement 安全门§8.3） | 可进化 |
| **P1** | 三层系统通信安全（§29） | 安全 |
| **P1** | Human Gate 审批者界面契约实现（§32） | 契约完整性 |
| **P1** | hi-agent 运行时配置热更新（§13.3） | 可运维 |
| **P2** | 核心指标埋点（含 policy_version 下钻维度§12.2） | 可观测 |
| **P2** | 分布式追踪 + callback 关联 + 审计日志（含 HLC §12.5） | 可观测/合规 |
| **P2** | Secret 管理集成 + LLM 输出安全过滤（§29.3） | 安全/可运维 |
| **P2** | TraceRuntimeView polling 模型��现（§12.4） | 可观测 |
| **P2** | confidence 校准验证（§21.2）+ calibration_error 指标 | 认知正确性 |
| **P2** | 告警通道 NotificationBackend 实现（§12.1.1） | 可观测 |
| **P2** | SoC defense-in-depth runtime 校验 + JWT aud 验证（§28） | 安全 |
| **P2** | input_refs 内容预扫描（§23.4） | 安全 |
| **P2** | 混沌测试框架基础实现（§24.6 最小 5 场景） | 可测试性 |
| **P2** | KnowledgeWiki 基础实现：ingest + query + IndexPage（§26 V2.7） | 知识编译 |
| **P2** | Inline Evolution 实现：L3 episodic 生成 + KnowledgeWiki ingest（§10 V2.7） | 进化 |
| **P2** | L3 Episodic 去重与再压缩（§25.3） | 分层记忆 |

**阶段 3 完整功能：**

| 优先级 | 项目 | 维度 |
|---|---|---|
| **P2** | Evolve Pipeline: human_guided + parameter_tuning 策略实现（§10.2 V2.6） | 可进化 |
| **P2** | Evolve Pipeline: route_replay 离线评估方法实现（§10.2 V2.6） | 可进化 |
| **P2** | Evolve Pipeline: QualityGate + A/B 实验 + 低频轻量路径（§10.3.1-10.3.2） | 可进化 |
| **P2** | EvolveSession 失败诊断 + 并发 Session 冲突检测 + promoting 两阶段提交 | 可进化 |
| **P2** | Skill 内容模型实现：prompt_template + action_pattern 两种 content_type（§8.3） | 可进化 |
| **P2** | Task View 优先级算法（§18.4） | 认知正确性 |
| **P2** | MemoryStore 一致性补偿机制（§25.3） | 数据一致性 |
| **P2** | 认知进展检测（§22） | 认知正确性 |
| **P2** | Knowledge TTL + revalidation（§26） | 可进化 |
| **P2** | EvalDataset 标注流程（§24.4.1）：Gate 审批副产品 + 独立标注 API | 可进化 |
| **P2** | Policy/Skill retirement 安全门 | 可演进/可进化 |
| **P2** | Task Family Bootstrap 配置 | 可进化 |
| **P3** | Run 管理 API 完整实现（含 BatchCancelResult §13.1） | 可运维 |
| **P3** | EvolveSession 管理 API | 可运维 |
| **P3** | 成本归因 + 预算预警 | 可运维 |
| **P3** | Stage Graph 子图引用 + 预算模板 | 可扩展 |
| **P3** | 可测试性基础设施（§24） | 可测试性 |
| **P3** | agent-core 全量不可用降级（§8.1） | 运行时可靠性 |
| **P3** | cross_component promoting 两阶段提交（§10.2） | 故障模型 |
| **P3** | 性能基线测试（§24.7）+ 容量规划校准（§13.4.1） | 可运维 |
| **P3** | 多租户数据分区预埋（§33.2 前向兼容设计） | 多租户 |
| **P3** | Evolve 进阶: skill_extraction 策略（含 meta-LLM + PrefixSpan 序列挖掘）（§10.2） | 可进化 |
| **P3** | Evolve 进阶: knowledge_discovery 策略（§10.2） | 可进化 |
| **P3** | Evolve 进阶: counterfactual + full_simulation 离线评估方法（§10.2） | 可进化 |
| **P3** | Skill 内容模型进阶: decision_rule + composite 两种 content_type（§8.3） | 可进化 |
| **P3** | TrajectoryOptimizer 进阶: MCTS + beam_search + todo_dag 三种模式（§6.2.2） | 轨迹优化 |
| **P3** | TaskPlan 基础：DAG+Linear 拆解、Coordinator 调度、Worker 自闭环（§34 Phase 1-2） | 任务拆解 |
| **P3** | TaskPlan 进阶：级联回退、计划修订、Tree+MCTS、PlanFeedback Evolve 集成（§34 Phase 3-4） | 任务拆解 |
| **P3** | KnowledgeWiki lint 操作（§26.2）+ lint 驱动的 knowledge_discovery 触发 | 知识编译 |

---

## 21. Route Engine 最小接口规范

Route Engine 是 hi-agent 的核心认知组件，负责"在 CTS 中生成、比较、选择路径"。其接口必须明确，以保证可替换性和可测试性。

### 21.1 接口定义

```
RouteEngineInput:
  task_view:               TaskViewRecord      # 当前 Task View（含 evidence、memory、goal）
  current_stage:           Stage               # 当前所处 Stage
  trajectory_tree:         TrajectoryTree      # 当前 Run 的已探索分支历史
  cts_budget_remaining:    CTSBudget           # 剩余 CTS 预算
  available_capabilities:  [CapabilityDescriptor]  # 当前可用的能力列表
  policy:                  RoutePolicyContent  # 当前 route_policy 内容

RouteEngineOutput:
  proposed_branches:       [BranchProposal]    # 提议新建的 Branch
  prune_branches:          [BranchPruneRecord] # 建议剪枝的已有 Branch
  route_rationale:         str                 # 路由决策的可审计理由
  route_decision_ref:      str                 # 与 task_view 绑定的决策引用
  confidence:              float               # 路由置信度（0-1），低于阈值触发 Gate B

BranchProposal:
  branch_id:              str                 # hi-agent 生成
  rationale:              str                 # 为何提议此路径
  required_capabilities:  [capability_id]
  estimated_complexity:   low | medium | high
  action_sequence_hint:   [action_kind]       # 预期执行的动作序列（供 Harness 预估资源）
  priority:               int                 # 多 Branch 并发时的优先级

BranchPruneRecord:
  branch_id:    str
  reason:       str
  prune_code:   insufficient_evidence | budget_exhausted | dominated_by_sibling | contradictory_evidence
```

### 21.2 实现约束

- Route Engine **必须**以 `RouteEngineInput` 为完整输入，不得直接访问全局状态
- 当 `confidence < route_policy.confidence_threshold`（默认 0.6）时，输出必须包含 `route_direction_gate_required=true`，触发 Gate B
- Route Engine 的实现可以是：LLM-based（调用模型比较路径）、规则引擎、混合策略——均通过同一接口封装

**confidence 校准要求（V2.5 新增）**：

Route Engine 的 confidence 输出必须经过校准验证，否则 Gate B 的触发阈值无法信任：

```
校准标准：
  当 Route Engine 声称 confidence = X 时，基于历史 Run 的实际成功率应 ≥ X - 0.1
  即：confidence=0.8 的决策，历史实际成功率应 ≥ 0.7

校准方式：
  - 规则引擎：confidence 由规则直接计算（如满足 N 个条件中 M 个 → confidence=M/N），天然校准
  - LLM-based：LLM 自评 confidence 通常 overconfident，需通过 EvalDataset 离线校准：
    1. 在 EvalDataset 上运行 Route Engine，收集 (confidence, actual_outcome) 对
    2. 计算 calibration_error = mean(|confidence - actual_success_rate|) per bucket
    3. 若 calibration_error > 0.15：Route Engine 版本不得进入 active，需重新训练/调参

校准频率：
  每次 route_policy_version 变更时重新校准
  定期（与 EvalDataset 更新同步）验证校准漂移

监控指标：
  confidence_calibration_error：按 route_policy_version 统计，纳入 §12.2 指标体系
  告警阈值：calibration_error > 0.15
```

### 21.3 验收标准评估接口

Task 完成时，hi-agent 必须执行 acceptance_criteria 验证：

```
AcceptanceCriteriaEvaluator:
  evaluate(task_contract: TaskContract, run_result: RunResult) -> EvaluationResult
  
EvaluationResult:
  passed:         bool
  criteria_scores: { criterion_id: score }  # 每条验收标准的评分
  evaluation_mode: automated | requires_human_review
  # 当 evaluation_mode=requires_human_review 时，触发 Gate C

AcceptanceCriteriaEvaluator 设计约束（V2.5 新增）：
  - 与 Route Engine 不同，AcceptanceCriteriaEvaluator 不要求纯函数
    （某些 acceptance_criteria 可能需要调用外部系统验证，如"代码编译通过"）
  - 但外部调用必须通过 Capability 调用契约（§31），不得绕过 Harness
  - 评估结果必须与 task_view_id 绑定（通过 bind_task_view_to_decision），支持 Evolve 回放
  - 若评估依赖的 Capability 不可用（熔断/降级）：evaluation_mode 自动切换为 requires_human_review
```

---

## 22. 认知进展检测

`no_progress` watchdog 仅检测 action 层面的活跃度，无法发现认知层面的循环（如反复收集相同证据）。引入双层进展检测机制。

### 22.1 双层检测架构

```
Layer 1（现有）：Action 活跃度检测
  触发：连续 watchdog_interval 内无 Action 执行
  结果：failure_code = no_progress (action_level)

Layer 2（V2.2 新增）：认知进展检测
  触发条件（满足任一）：
    A. evidence_overlap_ratio > 0.85：
       近 K 次 Action 采集的 evidence 与已有 evidence 的语义相似度超过阈值
    B. branch_trajectory_similarity > 0.80：
       新提议的 Branch 与已失败的 Branch 的语义相似度超过阈值
    C. stage_revisit_count > N：
       同一 Stage 在本 Run 内被回退激活超过 N 次（默认 N=3）
  结果：failure_code = no_progress (cognitive_level)，触发 Gate B
```

### 22.2 相似度计算职责

- 相似度计算由 Route Engine 执行，基于 evidence embedding 比较
- embedding 模型版本由 `task_view_policy` 管理（保证版本一致性）
- 阈值参数在 `route_policy` 中配置，支持 per-family 调整

**embedding 模型版本与 Evolve 的耦合约束（V2.5 新增）**：
- embedding 模型变更（如从 text-embedding-3-small → text-embedding-3-large）属于 `task_view_policy` 的 major 变更
- 变更后，所有基于旧 embedding 计算的 `evidence_overlap_ratio` 和 `branch_trajectory_similarity` 阈值均失效
- 因此 embedding 模型变更必须作为 `cross_component` EvolveChangeSet：
  1. 切换 embedding 模型版本
  2. 同步重新校准 route_policy 中的相似度阈值（通过 EvalDataset 离线评估）
  3. 两个变更在同一个 ChangeSet 中原子晋升，不允许单独升级 embedding 而不调阈值

---

## 23. 权限与授权模型

企业级 agent 执行的动作可能不可逆，必须有明确的授权边界。

### 23.1 角色定义

| 角色 | 描述 |
|---|---|
| `run_submitter` | 可提交新 Run |
| `run_operator` | 可查询、取消、信号 Run |
| `gate_approver` | 可批准 Human Gate（需按 Gate 类型进一步细分） |
| `evolve_manager` | 可触发 Evolve、审批 ChangeSet 晋升 |
| `system_admin` | 可执行所有操作，含 force_complete、retire policy、注册 task_family |
| `audit_reader` | 只读访问审计日志 |

### 23.2 操作 → 最低所需角色

| 操作 | 最低角色 |
|---|---|
| `start_run()` | run_submitter |
| `batch_start_runs()` | run_submitter |
| `cancel_run()` | run_operator |
| `batch_cancel_runs()` | run_operator |
| `force_complete_run()` | system_admin |
| `signal_run(resume / callback)` | run_operator |
| `signal_run(approval)` | gate_approver（且必须绑定到特定 gate_ref） |
| `signal_run(cancel)` | run_operator |
| `register_task_family()` | system_admin |
| `update_task_family()` | system_admin |
| `retire_policy_version()` | evolve_manager |
| 触发 EvolveSession | evolve_manager |
| 审批 ChangeSet 晋升 | evolve_manager |
| `cross_component` ChangeSet 额外审批 | system_admin |
| 读取审计日志 | audit_reader |

### 23.3 Gate 审批权限细化

| Gate 类型 | 审批人约束 |
|---|---|
| Gate A (contract_correction) | gate_approver + 需是 task 的原始提交人或指定授权人 |
| Gate B (route_direction) | gate_approver |
| Gate C (artifact_review) | gate_approver（可委托给领域专家账号） |
| Gate D (final_approval) | gate_approver + 需要双人确认（two-person rule）当 risk_level=critical |

### 23.4 Task Contract 输入安全

Task Contract 的 `goal`、`constraints`、`acceptance_criteria` 字段是自由文本，存在内容注入风险：

```
TaskContractValidator:
  validate(contract: TaskContract) -> ValidationResult
  
检查项：
  1. goal 中不得包含系统级指令模式（如 "ignore previous instructions"）
  2. constraints 中不得包含绕过 Human Gate 的指令
  3. acceptance_criteria 不得要求跳过 effect_class 检查
  4. input_refs 不得引用超出当前用户权限范围的资源
  5. （V2.5 新增）input_refs 引用的外部内容在加载到 Task View 前必须经过内容预扫描：
     - 扫描规则与 §29.3 HarnessOutputSecurityFilter 相同（系统指令模式、凭证格式、注入特征）
     - 扫描时机：Task View 构建阶段（§18.4），对 evidence_refs 中来自 input_refs 的内容执行
     - 若匹配：该 evidence 标记为 tainted，降级为 nice_to_have（不进入 must_keep），并在审计日志记录
     - 已知局限：此扫描为模式匹配，无法防御所有间接注入。§29.3 的 Harness 输出过滤仍是最后防线
  
违规时：返回 invalid_context，Run 不得启动
```

---

## 24. 可测试性规范

### 24.1 Mock Kernel 接口

单元测试 hi-agent 时，通过 Mock Kernel 隔离 agent-kernel：

```
MockKernelAdapter（实现与 RuntimeAdapter 相同接口）：
  # 所有状态存储在内存，不依赖 durable store
  start_run(req) -> StartRunResponse  # 返回固定的成功响应
  open_stage(stage_id) -> None        # 记录调用，不写持久化
  mark_stage_state(stage_id, state) -> None
  open_branch(branch_id) -> None
  mark_branch_state(branch_id, state) -> None
  record_task_view(record) -> task_view_id
  bind_task_view_to_decision(task_view_id, decision_ref) -> None
  
  # 测试辅助方法
  assert_stage_opened(stage_id)
  assert_branch_state(branch_id, expected_state)
  get_all_recorded_actions() -> [ActionRecord]
  inject_callback(action_id, result)  # 模拟外部回调

  # V2.5 新增：状态机验证模式
  strict_mode:  bool (默认 true)
  # strict_mode=true 时，MockKernelAdapter 内置 §14 的全部状态机：
  #   - mark_stage_state() 校验合法转移（§14.3），非法转移抛出 IllegalStateTransition
  #   - mark_branch_state() 校验合法转移（§14.4）
  #   - signal_run() 校验 RunState 转移（§14.2）
  # strict_mode=false 时，退化为纯记录模式（向后兼容旧测试）
  #
  # 校验逻辑从 §14 的状态机表自动生成（state_machine_rules.json），
  # 确保 Mock 和生产 kernel 使用同一份规则源
```

### 24.2 LLM Response Fixture

集成测试中，LLM 调用必须可确定性重放：

```
LLMResponseFixture：
  模式：record | replay | passthrough

  record 模式：
    拦截所有 LLM 调用，将 (call_id, request_hash) → response 写入 fixture 文件
  
  replay 模式：
    拦截所有 LLM 调用，根据 request_hash 查询 fixture，返回已记录的响应
    若未命中：测试失败，提示需要重新录制
  
  passthrough 模式：
    直接调用真实 LLM（端到端测试场景）

fixture 文件格式：JSON Lines，每行一个 { call_id, request_hash, response, recorded_at }

request_hash 计算规范（V2.5 新增）：
  # hash 基于结构化输入（非原始 prompt 文本），防止 prompt 格式微调导致 fixture 失效
  request_hash = SHA-256(
    task_view_id,          # 唯一标识 Task View 的组成
    model,                 # 调用的模型标识
    route_policy_version,  # 当前路由策略版本
    capability_ids_sorted  # 本次调用涉及的 capability id 排序列表
  )
  # 不包含：prompt 原始文本、timestamp、random seed
  # 效果：相同的 Task View + 相同模型 + 相同 policy 总是命中同一 fixture
```

### 24.3 Stage Graph 形式化验证

`validate_task_family_config()` 必须在注册前执行以下图分析：

```
图分析算法：
  1. 可达性检查：从 initial_stage 出发，BFS 遍历所有可达 Stage
     → 存在不可达 Stage：返回 unreachable_stages 错误

  2. 终态可达检查：从每个非终态 Stage，能否通过有限步骤到达某个终态
     → 存在无终止路径（纯循环）且无 Gate 出口：返回 deadlock_risk 错误

  3. Gate 完整性检查：每个 Gate 触发条件对应的 ReviewState 处理路径存在
     → Gate D 触发后，approved 和 rejected 两条路径都必须有定义

  4. 预算合法性检查：max_active_branches ≤ max_total_branches
```

### 24.4 Evolve 离线评估测试数据管理

```
EvalDataset：
  dataset_id:      稳定标识
  task_family:     所属 task_family
  version:         数据集版本
  runs:            [RunSnapshot]   # 从生产 Run 中采样的快照（已脱敏）
  labels:          [EvalLabel]     # 人工标注的质量标签
  created_at:      时间戳
  sampling_policy: random | stratified | failure_focused

RunSnapshot：
  run_id, task_contract_ref, trajectory_summary
  final_outcome:   completed | failed | aborted
  human_quality_label:  excellent | acceptable | poor (可选，人工标注)

维护原则：
  - EvalDataset 版本化管理，每次 Evolve 使用固定 dataset_version
  - 新 Runs 定期采样加入数据集（不超过数据集总量的 20%/月，防止数据漂移）
  - 敏感内容在加入数据集前必须脱敏
  - （V2.5 新增）adversarial_ratio ≥ 10%：每个 dataset_version 至少 10% 的 RunSnapshot
    必须来自人工构造的边界测试（非生产采样），覆盖当前策略难以处理的场景
    来源：安全团队注入的对抗性 TaskContract、人工标注的 edge-case 场景、历史 failure Run 的变体
    目的：防止 EvalDataset 收敛到当前策略的舒适区，保持 Evolve 评估的覆盖广度

### 24.4.1 标注流程与成本模型（V2.6 新增）

EvalDataset 的 `human_quality_label` 和 `adversarial_ratio` 都依赖人工投入。以下是使其可执行的具体规范：

**标注职责分配：**
| 标注类型 | 负责人 | 频率 | 预期耗时/条 |
|---|---|---|---|
| human_quality_label（对生产 Run 评分） | gate_approver 或指定领域专家 | 每周或每 N 个 Run | 5-15 分钟（需查阅 trajectory_summary） |
| adversarial RunSnapshot（构造边界测试） | evolve_manager + 领域专家 | 每次 dataset_version 更新 | 30-60 分钟（需设计异常场景） |
| EvalLabel（标注评估标签） | 与 human_quality_label 合并执行 | 同上 | 同上 |

**标注一致性保证：**
```
inter_annotator_agreement 要求：
  - 每个 RunSnapshot 至少由 2 人独立标注
  - 若 2 人标注不一致（如一人 excellent 一人 poor）：
    第 3 人仲裁，仲裁结果为最终标签
  - 目标 Cohen's κ ≥ 0.7（substantial agreement）
  
标注集成到 Human Gate 流程（降低额外成本）：
  - Gate C (artifact_review) 解决后，顺便要求 gate_approver 为本 Run 打 quality_label
  - Gate D (final_approval) 解决后，同上
  - 这样大部分标注是 Gate 审批的"副产品"，不需要独立的标注流程
  
标注界面：
  - 复用 §32 Human Gate 审批 API，在 GateContext 中增加 optional 的 quality_label_request 字段
  - 非 Gate 场景的独立标注：通过 POST /management/runs/{run_id}/label 提交
```

**无标注数据时的降级策略：**
```
若 task_family 的标注数据不足（labeled_runs < min_evaluation_sample_size）：
  - QualityGate 退化为仅使用自动指标（success_rate, token_cost），不使用 acceptance_criteria_pass_rate
  - 告警：quality_gate_degraded = true，提醒 evolve_manager 补充标注
  - EvolveSession 仍可继续，但在 evaluation_result_ref 中标记 low_label_coverage
```
```

### 24.5 测试金字塔（V2.5 新增）

```
推荐测试层次与覆盖范围：

L1 单元测试（MockKernel strict_mode + LLM Fixture replay）：
  覆盖：Route Engine 路由决策、Task View 优先级算法、Stage 退出条件判断、
        action_id/task_view_id 生成算法、熔断器状态机、Policy 版本管理逻辑
  运行速度：< 10ms/case，CI 每次提交运行
  占比目标：≥ 70% of total test count

L2 集成测试（真实 agent-kernel + LLM Fixture replay）：
  覆盖：Run 完整生命周期（S1→S5）、状态机转移合法性、幂等键跨层验证、
        事件日志 + payload store 写入/读取、多实例孤儿接管
  运行速度：< 30s/case，CI 每日运行
  占比目标：≥ 20%

L3 端到端测试（真实 agent-kernel + LLM passthrough + 真实 Capability）：
  覆盖：quick_task family 完整 Run、Human Gate 审批流、
        Evolve Pipeline 单次完整晋升
  运行速度：数分钟/case，Release 前运行
  占比目标：≤ 10%，但必须覆盖 MVP 阶段 1 验收场景
```

### 24.6 混沌测试框架（V2.5 新增）

以下关键路径必须通过故障注入验证：

```
ChaosTestScenario 最小集合：

1. kernel_disconnect（验证 §13.6 网络分区降级）：
   注入：在 Run active 期间断开 hi-agent → agent-kernel 连接
   预期：60s 后进入 degraded，150s 后进入 partitioned
          read_only Action 继续，irreversible_submit 阻止
          恢复后 verify_run_ownership 成功
   
2. capability_cascade_failure（验证 §8.1 熔断器）：
   注入：使某 Capability 连续返回 FAILED + retryable=true
   预期：达到 failure_threshold 后熔断器 open
          Route Engine 不再提议依赖该 Capability 的 Branch
          half_open_timeout 后自动探测恢复

3. orphan_adoption_race（验证 §13.6 CAS 仲裁）：
   注入：同时启动两个实例竞争接管同一孤儿 Run
   预期：仅一个实例 adopt 成功，另一个收到 success=false
          无重复 Action 执行

4. evolve_concurrent_promote（验证 §10.2 universal Skill 晋升锁）：
   注入：两个 EvolveSession 同时进入 promoting，都要晋升同一 universal Skill
   预期：一个获锁成功，另一个进入 promoting_blocked

5. memory_write_failure（验证 §25.3 补偿机制）：
   注入：在 ActionSucceeded 事件写入后使 MemoryStore 不可用
   预期：episodic_memory_pending=true 标记在事件中
          恢复后自动补偿写入

实现建议：使用 fault injection proxy（如 Toxiproxy）在 L2 集成测试环境中注入故障
```

### 24.7 性能基线测试（V2.5 新增）

```
PerformanceBenchmark 最小集合：

1. task_view_build_latency：
   条件：100 个 evidence_refs + 20 个 memory_refs + 10 个 knowledge_refs
   目标：P99 < 50ms（不含 agent-kernel query_trace_runtime() 延迟）
   
2. route_engine_decision_latency（规则引擎实现）：
   条件：5 个 active Branch + 10 个 available capabilities
   目标：P99 < 100ms

3. trace_runtime_polling_throughput：
   条件：100 个并发 active Run，每个 5s polling
   目标：agent-kernel 查询延迟 P99 < 500ms，无查询风暴

4. event_log_write_throughput：
   条件：50 个并发 Run，每个 Run 平均 10 events/min
   目标：event log 写入延迟 P99 < 100ms

5. concurrent_run_capacity：
   条件：递增 active Run 数直到 OOM 或 P99 > SLO
   输出：单实例最大并发 Run 数（用于容量规划 §13.10）
```

---

## 25. 边界执行机制

边界定义如果只是文档约定，将随工程迭代逐渐腐化。以下机制提供技术层面的边界执行能力。

### 25.1 导入边界检查

通过静态分析工具（如 import-linter、dependency-cruiser）在 CI 中强制执行：

```
hi-agent 模块允许的导入规则：
  hi_agent.trace_runtime → 允许导入 hi_agent.capability_registry
  hi_agent.trace_runtime → 允许导入 hi_agent.runtime_adapter
  hi_agent.trace_runtime → 禁止 直接导入 agent_kernel.internal.*
  hi_agent.capability_modules → 允许导入 agent_core.capabilities.*
  hi_agent.capability_modules → 禁止 导入 hi_agent.trace_runtime.route_engine
  hi_agent.runtime_adapter → 允许导入 agent_kernel.facade.*
  hi_agent.runtime_adapter → 禁止 导入 agent_kernel.workflow.internals.*
```

### 25.2 Harness 所有权决策框架

新增 Harness 相关功能时，使用以下判断树确定归属：

```
Q1: 这个功能是"如何表达要做什么"（语义）还是"如何安全执行"（治理）？
  语义 → hi-agent (Harness Orchestrator)
  治理 → agent-kernel

Q2: 这个功能是"提供什么能力"（内容）？
  能力内容 → agent-core

Q3: 如果不确定：该功能需要访问 TaskContract / CTS / Route 信息吗？
  是 → hi-agent
  否 → agent-kernel 或 agent-core

示例：
  "动作结果缓存"：属于执行治理 → agent-kernel
  "相似动作去重"：需要访问 Route 语义 → hi-agent
  "PDF 解析能力"：内容能力 → agent-core
```

### 25.3 分层压缩记忆架构（V2.7 重写）

V2.6 的 Working/Episodic Memory 是扁平的——evidence 随 Run 线性增长，Task View 在读取时做裁剪。参考 Karpathy LLM Wiki 的"写入时编译"模式，V2.7 将记忆重建为 **4 层压缩层次**，每层有固定 token budget，使 Task View 构建的成本可预测：

```
L0_raw（原始证据层——当前 Working Memory 的超集）：
  内容：每次 Action 的完整输入/输出、每次 LLM 调用的完整 response
  存储：agent-kernel event log + payload store（已有设计不变）
  大小：无上限，按 Run 保留期 TTL 清理
  访问频率：极低——仅在需要追溯细节时按 ref 加载

L1_compressed（Stage 压缩层——每个 Stage 完成时生成）：
  触发：Stage 进入 completed / failed 状态时，或 stage_revisit 时
  算法：
    stage_evidence = collect_all_L0_evidence(stage_id)
    L1_summary = llm_compress(stage_evidence, budget=2048_tokens)
    # compress prompt: "以下是 Stage {name} 的全部执行记录。
    #   提取：关键发现（findings）、做出的决策（decisions）、
    #   未解决的问题（open_questions）、失败原因（if failed）。
    #   总结限制在 2048 tokens 以内。"
  
  输出结构：
    StageSummary:
      stage_id:        str
      stage_name:      str
      findings:        [str]     # 关键发现（每条 ≤ 200 tokens）
      decisions:       [str]     # 做出的决策及理由
      open_questions:  [str]     # 进入下一 Stage 前未解决的问题
      outcome:         succeeded | failed | revisited
      token_count:     int       # 实际 token 数（≤ 2048）
  
  大小：固定上限 2048 tokens/Stage，一个 5-Stage Run ≤ 10K tokens
  这是 Task View 的 PRIMARY 数据源

  压缩时序（V2.8 澄清）：
    模式：异步压缩 + 同步 fallback
    流程：
      1. Stage 标记为 completed 后，立即启动异步 llm_compress() 任务
      2. Stage 转移不等待压缩完成——Run 可以继续推进到下一 Stage
      3. 下一 Stage 的 Task View 构建时：
         - 若 L1 已生成 → 使用 L1（正常路径）
         - 若 L1 尚未生成（压缩仍在进行）→ fallback：从 L0_raw 取最近 N 条 evidence 做临时裁剪（N = 20，≤ 2048 tokens）
         - fallback 裁剪不写入 L1（避免低质量摘要污染），待异步压缩完成后替换
      4. 若 llm_compress() 失败（LLM 超时/不可达）：
         - 重试 1 次
         - 仍失败：使用 fallback 裁剪结果作为本 Stage 的 L1（标记 compression_quality=fallback）
         - 写入审计日志 l1_compression_failed
         - 不阻塞 Run——数据不完美比任务停滞好

  must_keep 保护：L1 压缩的 findings 字段必须包含所有 contradictory evidence 的引用（即使摘要省略细节），
  确保矛盾信息不被压缩丢弃。compress prompt 中显式要求："列出所有矛盾证据的 evidence_ref。"

L2_index（Run 导航层——每次 Stage 转移时更新）：
  触发：Stage 状态变更时自动更新
  内容：类似 LLM Wiki 的 index.md——当前 Run 的压缩全景
  
  输出结构：
    RunIndex:
      run_id:              str
      task_goal_summary:   str (≤ 100 tokens)  # TaskContract.goal 的压缩版
      stages_status:       [{ stage_id, stage_name, state, one_line_summary }]
      current_stage:       stage_id
      key_decisions_so_far: [str] (每条 ≤ 50 tokens，最多 10 条)
      critical_open_questions: [str] (最多 5 条)
      trajectory_quality:  float  # 从 TrajectoryNode.propagated_score 汇总
  
  大小：固定上限 512 tokens
  用途：Route Engine 读取的第一份数据——快速了解"Run 现在在哪、做了什么"
  这是 RouteEngineInput 的轻量上下文注入

L3_episodic（跨 Run 情景记忆——Run 完成时生成）：
  触发：Run 进入终态（completed / failed / aborted）时
  算法：
    all_L1_summaries = [L1 of each stage in this Run]
    episode = llm_compress(all_L1_summaries, budget=512_tokens)
    # compress prompt: "以下 Run 完成了任务 {goal}。
    #   提取：核心模式（pattern）、成败原因（outcome_reason）、可复用教训（lesson）。
    #   限制 512 tokens。"
    
    # 去重：与已有 episodes 的 pattern 比较（embedding 相似度 > 0.85 → 合并而非新增）
    if similar_episode_exists:
      merge_episodes(existing, new)  # 更新 lesson，增加 evidence_count
    else:
      create_new_episode(episode)
  
  输出结构：
    Episode:
      episode_id:      str
      task_family:     str
      pattern:         str (≤ 200 tokens)  # 核心模式描述
      outcome:         succeeded | failed
      lesson:          str (≤ 200 tokens)  # 可复用教训
      evidence_count:  int                 # 支持该 episode 的 Run 数
      source_run_refs: [run_id]
      created_at:      datetime
      merged_count:    int                 # 合并了多少条相似 episode
  
  大小：per-episode 固定 ≤ 512 tokens
  容量控制：当 task_family 的 episode 数 > 100，触发再压缩——
    将最旧的 50 条 episodes 用 LLM 合并为 10 条更抽象的 meta-episodes
  
  用途：Task View 的 nice_to_have 层——历史教训
```

**Task View 构建流程（V2.7 重写 §18.4）：**

```
替代 V2.6 的 must_keep/should_keep/nice_to_have 裁剪算法：

Step 1: 加载 L2_index（≤ 512 tokens，瞬时）
  → Route Engine 和 Task View 都以此为起点

Step 2: 加载当前 Stage 的 L1_compressed（≤ 2048 tokens）
  → 当前阶段的完整压缩上下文

Step 3: 如有余量，加载上一 Stage 的 L1_compressed（≤ 2048 tokens）
  → 前序阶段的关键信息（含 open_questions 传递）

Step 4: 如有余量，加载相关 L3_episodic entries（按 pattern 相关性排序，每条 ≤ 512 tokens）
  → 历史教训

Step 5: 如有余量，加载 KnowledgeWiki 查询结果（§26 V2.7）
  → 领域知识

Step 6: 仅在需要追溯细节时，按 ref 加载特定 L0_raw evidence
  → 不再遍历全量 evidence

token 预算分配（确定性，不依赖 LLM 评分）：
  L2_index:                固定 512 tokens（必加载）
  L1_current_stage:        固定 2048 tokens（必加载）
  L1_previous_stage:       最多 2048 tokens
  L3_episodic:             最多 1024 tokens（2-3 条 episode）
  Knowledge:               最多 1024 tokens
  System prompt + Skill:   最多 2048 tokens（§8.3 SkillContent 注入）
  系统保留:                512 tokens
  总计：≤ 9728 tokens 的 "框架"，剩余空间留给 model 输出

优势：
  - token 成本可预测（不再依赖 evidence 数量）
  - 不需要在读取时做裁剪决策——压缩在写入时已完成
  - L2_index 使 Route Engine 不需要加载完整上下文即可做路由决策
```

### 25.3.1 原始存储规范（保留，V2.6 设计不变）

```
Memory/Knowledge 存储在独立的 durable store（非 agent-kernel event log）：

L0_raw 层（原 Working Memory）：
  backend: agent-kernel durable store（随 Run 状态共同持久化）
  清理：Run 完成后 TTL 清除（默认 7 天）

L1/L2 层（新增）：
  backend: hi-agent 本地存储（内存 + 磁盘缓存）
  持久化：通过 agent-kernel 的 event log 记录 StageSummary / RunIndex
  重建：Run 恢复时从 event log 重建 L1/L2（不需要重新压缩）

L3_episodic 层（原 Episodic Memory，存储方式不变）：
  backend: 独立 MemoryStore（向量数据库 + KV store）
  作用域：task_family 全局
  
Semantic/Procedural Knowledge：
  存储：KnowledgeWiki（§26 V2.7 重写）
  访问：hi-agent 内部读写，agent-kernel 不可见
```

**MemoryStore 与事件流的一致性保证（V2.4 新增）**：

Working Memory 存储在 agent-kernel，Episodic Memory 在独立 MemoryStore。两者的写入不是原子的，需要一致性策略：

```
写入顺序与补偿规则：

场景：ActionSucceeded 事件写入成功，随后 write_episodic_memory() 失败
  处理：
    1. ActionSucceeded 事件中的 episodic_memory_pending=true 标记（记录"待写入"意图）
    2. hi-agent 重启后（或 Run 从 recovering 恢复时），扫描 episodic_memory_pending=true 的事件
    3. 对每个 pending 事件：重新执行 write_episodic_memory()（幂等，同 episode_id）
    4. 写入成功后：将 agent-kernel 事件中的 episodic_memory_pending 更新为 false
  
  这是一个"at-least-once"写入保证，episode 的写入是幂等的（同 episode_id 重复写入不产生重复记录）

场景：write_episodic_memory() 成功，但 ActionSucceeded 事件未写入（agent-kernel 故障）
  处理：
    Run 会从事件流重建，该 Action 会被视为未完成，重新执行
    重新执行时 episode_id（由 action_id 确定性生成）相同，write_episodic_memory() 幂等处理
    不产生重复 episode

EvalDataset 快照一致性：
  RunSnapshot 必须包含 knowledge_snapshot_ref（记录生成该 Run 时 Knowledge 的版本集合）
  离线 Evolve 评估时加载 knowledge_snapshot_ref 中的 Knowledge 版本（不使用当前生产版本）
  这保证评估结论是对特定 Knowledge 状态的公平测量
```

### 25.4 Context OS 与 ContextEngine 分割线

hi-agent 的 Context OS 是语义层，agent-core 的 ContextEngine 是资源层：

```
允许 Context OS 调用的 ContextEngine 方法：
  - get_context_slice(refs, max_tokens) -> ContextSlice  # 按引用获取内容
  - estimate_tokens(refs) -> int                          # 估算 token 用量
  - get_session_resource(session_id, resource_type)       # 获取 session 资源

禁止 Context OS 直接调用：
  - ContextEngine.internal_cache.*   # 缓存内部状态
  - ContextEngine.session_manager.*  # session 生命周期管理
  - 任何涉及 route / evolve 语义的方法
```

---

## 26. KnowledgeWiki：编译式知识管理（V2.7 重写）

V2.6 的 KnowledgeRecord 是扁平列表——知识条目之间没有关联。参考 Karpathy LLM Wiki gist 的核心洞察：**知识不是存储，是编译。概念之间的关联和概念本身同样有价值。** V2.7 将知识重建为**互相链接的页面网络**。

### 26.1 KnowledgeWiki 结构

```
KnowledgeWiki（替代原 KnowledgeStore）：
  wiki_id:          per-task_family 唯一标识（universal knowledge 有一个全局 wiki）
  
KnowledgePage（wiki 的基本单元，替代原 KnowledgeRecord）：
  page_id:          str
  page_type:        concept | procedure | entity | lesson | index
  title:            str (≤ 50 tokens)
  content:          str (markdown, ≤ 1024 tokens)
  links:            [{ target_page_id, relationship }]
                    # relationship: related_to | prerequisite_of | contradicts | supersedes | part_of
  
  # 来源与时效（保留 V2.6 核心字段）
  source_refs:      [run_id | episode_id]    # 贡献了内容的来源
  confidence:       float (0-1)
  status:           active | suspect | expired | archived
  valid_until:      datetime (可选)
  revalidation_policy: on_use | on_schedule | on_signal | never
  last_validated_at:   datetime
  last_compiled_at:    datetime              # 上次被 ingest 操作更新的时间
  
  # 使用统计（供 Evolve 分析）
  reference_count:  int    # 被 Task View 引用的次数
  usefulness_score: float  # 引用了此 page 的 Run 的平均成功率

IndexPage（每个 wiki 有且只有一个）：
  page_type:  index
  content:    按领域概念组织的目录，每条 ≤ 30 tokens
  结构：
    ## {domain_category_1}
    - [{concept_title}](page_id) — one-line summary
    - [{entity_title}](page_id) — one-line summary
    ## {domain_category_2}
    ...
  大小：固定上限 512 tokens
  更新：每次 ingest 后自动重建
```

**五种 page_type：**
| 类型 | 内容 | 来源 | 示例 |
|---|---|---|---|
| `concept` | 领域概念的定义和解释 | 多次 Run 中反复出现的概念 | "LLM 幻觉检测方法" |
| `procedure` | 执行某类操作的步骤和最佳实践 | 从 Skill（action_pattern）泛化 | "学术论文检索标准流程" |
| `entity` | 具体实体（人、组织、工具、API） | Run 中频繁引用的实体 | "arxiv API 使用指南" |
| `lesson` | 从失败或成功中提炼的教训 | L3_episodic 中的高频 pattern | "深度分析任务中不要在 S2 阶段过早剪枝" |
| `index` | 目录导航页 | 自动生成 | per-wiki 唯一 |

### 26.2 三种操作：ingest / query / lint

**ingest（摄入——Run 完成后编译新知识进 wiki）**

```
触发时机：Run 进入终态时（与 L3_episodic 生成同步）
输入：本 Run 的所有 L1_compressed stage summaries + L3 episode

流程：
  1. 概念提取：
     extracted = llm_extract(L1_summaries + episode,
       prompt="从以下执行记录中提取：
         - 新发现的领域概念（concept）
         - 可复用的操作步骤（procedure）
         - 重要的实体信息（entity）
         - 值得记住的教训（lesson）
         每项 ≤ 200 tokens。")
  
  2. 页面匹配与更新：
     for each extracted_item:
       existing = wiki.search(extracted_item.title, similarity_threshold=0.85)
       if existing:
         # 更新已有页面：合并新信息，增加 source_refs，更新 confidence
         existing.content = llm_merge(existing.content, extracted_item.content,
           prompt="合并以下两段知识，保留两者的信息，去除重复，保持 �� 1024 tokens")
         existing.source_refs.append(run_id)
         existing.confidence = min(1.0, existing.confidence + 0.05)  # 每次确认提升置信度
         existing.last_compiled_at = now()
       else:
         # 创建新页面
         new_page = KnowledgePage(
           page_type = extracted_item.type,
           title = extracted_item.title,
           content = extracted_item.content,
           confidence = 0.5,  # 新页面初始置信度 0.5（需更多 Run 确认）
           source_refs = [run_id]
         )
         wiki.add(new_page)
  
  3. 链接发现：
     for each new_or_updated_page:
       related = wiki.search(page.content, top_k=5, exclude=page.page_id)
       for each related_page:
         relationship = llm_classify_relationship(page, related_page)
         # relationship: related_to | prerequisite_of | contradicts | supersedes | part_of
         if relationship == contradicts:
           trigger gate_c(contradictory_evidence)  # 矛盾知识需人工仲裁
         page.links.append({ target: related_page.page_id, relationship })
  
  4. 索引重建：
     wiki.index_page.content = llm_rebuild_index(wiki.all_pages())
     # 按领域分类组织，每条一行，总计 ≤ 512 tokens

成本：每次 ingest 约 2-3 次 LLM 调用（概念提取 + 页面合并 + 链接发现）
      对于 quick_task（简单任务），ingest 可能无新知识提取 → 0 次调用
```

**query（查询——Task View 构建时检索相关知识）**

```
调用时机：Task View 构建 Step 5（§25.3）
输入：当前 task_goal + stage_context
输出：≤ 1024 tokens 的相关知识

流程：
  1. 加载 IndexPage（≤ 512 tokens）
  2. 从 IndexPage 中匹配与 task_goal 相关的 page_ids
  3. 加载 top-K 个 KnowledgePage（按 relevance × confidence 排序）
  4. 沿 links 加载 1 层相关页面（prerequisite_of / part_of 优先）
  5. 截断到 1024 tokens budget

与 V2.6 的 flat KnowledgeRecord 查询区别：
  - V2.6：直接按 confidence 排序的平面列表
  - V2.7：先读索引（导航），再按链接展开（结构化检索）
  效果：即使有 500 个 KnowledgePage，IndexPage 保证首次查询只读 512 tokens
```

**lint（审计——定期检查知识一致性，参考 Karpathy LLM Wiki）**

```
触发时机：
  - 定期（每 7 天 / on_schedule）
  - Evolve 触发（作为 knowledge_discovery 策略的前置步骤）
  - 手动触发

检查项：
  1. 矛盾检测：links 中 relationship=contradicts 的页面对 → 升级为 Gate C
  2. 孤立页面：reference_count=0 且 links 为空 → 标记为 suspect
  3. 过期页面：last_compiled_at > revalidation_interval × 2 → 触发 revalidation
  4. 低置信页面堆积：confidence < 0.3 的页面占比 > 20% → 告警
  5. 索引覆盖率：有多少 active 页面未被 IndexPage 引用 → 自动重建索引

输出：LintReport { issues: [{ issue_type, page_ids, suggested_action }] }
```

### 26.3 时效性状态流转（保留 V2.6 设计，适用于 KnowledgePage）

```
active → suspect：
  条件：confidence < 0.3，或 valid_until 过期，或 revalidation 超过 2× interval 未执行
  新增条件（V2.7）：reference_count=0 且 created_at > 90 天（从未被使用的知识）

suspect → active：
  条件：re-validation 通过（被新 Run 的 ingest 确认），confidence 恢复到阈值以上

suspect → expired：
  条件：suspect 状态持续超过 30 天，或被 contradicts 关系的新页面显式 supersedes

expired → archived：
  条件：手动触发，或保留超过 180 天
  
active + contradicts link → 触发 Gate C (contradictory_evidence)
```

### 26.4 Knowledge 与 Evolve 的交互（更新）

- **ingest 是 inline evolution 的一部分**（§10 V2.7）：每次 Run 完成后自动执行，不等 batch Evolve
- **lint 是 batch evolution 的触发源**：lint 发现大量 suspect/contradicts → 自动触发 knowledge_discovery 类 EvolveSession
- Knowledge 更新作为 `knowledge_only` ChangeSet 的质量门保持不变：`acceptance_criteria_pass_rate` 不得下降超过 3%
- **usefulness_score 反馈给 Task View**：高 usefulness_score 的页面在 query 时排序更高（形成正反馈环）

---

## 27. 架构总结

`TRACE V2.8 在 V2.7 结构性重构（轨迹优化/分层记忆/知识编译/双轨进化）基础上，修复了快速迭代产生的内部矛盾和规范债务：（1）统一 TrajectoryNode 与 Branch——声明 TrajectoryNode DAG 为权威运行时模型，Branch 退化为路径视图，§14.4 BranchState 保留 API 兼容但内部映射为 TrajectoryNode 操作，消除两套状态定义的歧义；（2）声明 §25.3 分层构建为 Task View 的权威流程，§18.4 的 must_keep/should_keep 裁剪标记为历史参考（superseded）；（3）定义 L1 压缩为异步执行+同步 fallback——Stage 转移不等待压缩，Task View 在压缩完成前使用 L0 临时裁剪，compress prompt 强制保留矛盾证据引用；（4）定义 Inline Evolution 失败不阻塞 Run 终态——L1/L3/ingest 任一失败跳过并异步重试，Run 标记 completed 不受影响；（5）CTS 预算新增 MCTS 专用字段（max_mcts_simulations_per_cycle / max_mcts_simulation_token_budget），防止 rollout 成本爆炸；（6）TaskFamilyConfig 新增 knowledge_ingest_policy（always/on_success/on_labeled/disabled），控制不同 family 的 ingest 成本；（7）Batch Evolve 创建时冻结 KnowledgeWiki 版本（knowledge_wiki_snapshot_version），确保评估一致性不受 Inline ingest 干扰；（8）§12.2 新增 7 个轨迹/记忆/知识指标（propagated_score 趋势、L1 压缩延迟和 fallback 率、知识过期率和 ingest 失败率、MCTS simulation 成本）；（9）todo_dag 增加 Phase 1.5 分解质量检查点（覆盖率/无环/无孤立，失败触发 Gate B）；（10）greedy 模式下 TrajectoryNode 轻量实现说明（visit_count 恒等于 1，DAG 退化为链表，但数据结构完整保存）；（11）文档拆分建议（6 个子规范 × 500-800 行，本文退化为概览+索引），为从"单文档"到"规范体系"的工程转型铺路。`

---

## 28. 认证与 RBAC 执行模型（V2.3 新增）

§23 定义了角色和权限映射，本节补充**运行时 enforce 机制**。

### 28.1 身份认证方案

hi-agent 的所有调用入口（Management API、Human Gate 回调、EvolveSession 控制）均要求调用方提供可验证身份：

```
认证方案（按调用来源）：

服务间调用（hi-agent ↔ agent-kernel ↔ agent-core）：
  方案：mTLS（双向 TLS）
  - 每个服务持有独立的 x.509 证书（由统一 CA 签发）
  - 服务启动时验证对方证书，拒绝未认证连接
  - 证书 CN 格式："{service_name}.{environment}.trace.internal"

人工操作调用（运维人员 / gate_approver / evolve_manager）：
  方案：Bearer JWT
  - JWT 由外部 IdP（Identity Provider）签发，hi-agent 验证签名
  - JWT payload 必须包含：{ sub, roles: [RoleName], exp, iat, aud }
  - `aud` 必须包含 "hi-agent"（防止其他服务的 JWT 被复用）
  - hi-agent 不存储密码或 session，每次请求独立验证 JWT（签名 + exp + aud）
  - JWT 有效期：操作型 token ≤ 1h，审计查询 token ≤ 24h

run_submitter 调用（提交 Run 的外部系统）：
  方案：API Key（HMAC-SHA256 签名请求）或 JWT
  - API Key 通过 SecretBackend 管理（不硬编码）
  - 每个 API Key 绑定到固定 task_family 列表（最小权限原则）
```

### 28.2 RBAC 执行主体与流程

```
执行主体分工：
  hi-agent Management API 层：验证调用方身份 + 检查所需角色（§23.2）
  agent-kernel：验证来自 hi-agent 的 mTLS 证书，不单独做业务 RBAC
  agent-core：验证来自 hi-agent 的 mTLS 证书

执行流程（以 cancel_run() 为例）：
  1. 调用方携带 JWT 调用 hi-agent /management/runs/{run_id}/cancel
  2. hi-agent auth middleware 验证 JWT 签名 + exp
  3. 提取 roles，检查是否包含 run_operator
  4. 通过：继续执行，并将 caller_identity 记录到审计日志
  5. 拒绝：返回 403，审计日志记录拒绝事件（含 caller_identity 和 attempted_operation）

Gate 审批的额外约束（§23.3，V2.5 增加 defense-in-depth）：
  所有 Gate：verify(resolver_sub != RunStarted.payload.initiated_by)
    # hi-agent 层硬校验"提交者不能审批自己的 Run"，不依赖 IdP 配置
    # 违反时返回 403 + 审计日志记录 soc_violation
  Gate A：verify(caller == task_contract.submitted_by OR caller in gate_a_authorized_list)
  Gate D（risk_level=critical）：
    1. 收到第一个 approved 信号后，进入 pending_second_approval 状态
    2. 等待第二个不同身份的 gate_approver 发送 approved
    3. 两个审批人不得是同一个 sub（JWT subject）
    4. 超时（24h 未收到第二审批）→ 自动转为 rejected，写入审计日志
```

### 28.3 Separation of Concerns 约束

| 约束 | 规则 |
|---|---|
| 提交者不能审批 | `run_submitter` 角色不能同时拥有 `gate_approver` 角色（系统级约束，IdP 配置层面强制） |
| Evolve 自审 | `evolve_manager` 不能审批自己发起的 EvolveSession 的 ChangeSet 晋升（需另一位 `evolve_manager`） |
| 强制日志 | 任何角色校验失败事件必须写入审计日志，不得仅返回错误而不记录 |

---

## 29. 三层系统通信安全模型（V2.3 新增）

### 29.1 通信矩阵

| 发起方 | 目标方 | 协议 | 认证 | 加密 |
|---|---|---|---|---|
| hi-agent | agent-kernel | gRPC over TLS 1.3 | mTLS | 强制 |
| hi-agent | agent-core capabilities | gRPC / HTTP over TLS 1.3 | mTLS | 强制 |
| agent-kernel | hi-agent（callback） | gRPC over TLS 1.3 | mTLS | 强制 |
| 外部系统 | hi-agent Management API | HTTPS（TLS 1.3） | JWT / API Key | 强制 |
| 外部系统 | hi-agent Callback Endpoint | HTTPS | HMAC 签名验证 | 强制 |

禁止任何非加密（明文 HTTP/gRPC）的生产通信；开发/测试环境可配置 `tls_mode: disabled`，但必须显式声明（默认不禁用）。

### 29.2 Capability 沙箱网络控制

`sandbox_class=strict` 的 Capability 运行在独立子进程，必须配置以下网络策略：

```
StrictSandboxNetworkPolicy:
  allowed_egress:    [endpoint_allowlist]  # 显式白名单，不得使用 "allow all"
  blocked_ports:     [22, 3306, 5432, 6379, ...]  # 禁止访问内部基础设施端口
  dns_resolution:    external_only         # 不能解析 .internal 域名
  max_connection_rate: 100 req/min         # 防止子进程作为跳板发起扫描
```

`sandbox_class=light`（独立线程）：通过 CapabilityDescriptor 中的 `credential_refs` 控制其可访问的外部服务，由 hi-agent 在注入凭证时强制过滤。

### 29.3 LLM 输出安全过滤

LLM 可能在 Action 建议或生成产物中意外输出敏感内容（凭证、内部服务地址、恶意命令），需在 Harness 分发前执行输出安全扫描：

```
HarnessOutputSecurityFilter（在 Harness Orchestrator 中）：
  检查项：
    1. 正则匹配已知凭证格式（AWS Key、私钥头、connection string 模式）
    2. 检查是否包含内部服务地址模式（*.internal, 10.x.x.x, 192.168.x.x）
    3. 检查 shell 命令注入特征（rm -rf, DROP TABLE, curl | bash 等高危模式）
  
  处理：
    - 匹配：阻止 Action 执行，记录 failure_code=unsafe_action_blocked，触发审计
    - 未匹配：允许继续
    - 过滤器本身的误报率应通过测试集（EvalDataset 中的对抗性样本）校准
```

---

## 30. 运维 Runbook（V2.3 新增）

常见故障场景的标准处理流程，供值班运维参考。

### 30.1 大量 Run 进入 recovering 状态

**触发告警**：`recovering_runs / active_runs > 5%`

```
诊断步骤：
  1. query_run(filter={state: recovering}) 获取 recovering Run 列表
  2. 按 failure_code 聚合：
     - 主要是 callback_timeout：检查外部依赖的可用性
     - 主要是 effect_unknown：检查 agent-kernel 的网络连通性
     - 主要是 model_output_invalid：检查 LLM Gateway 的模型版本是否变更
  3. 若是系统性问题（>50% 相同 failure_code）：暂停新 Run 提交（/health/ready → 503）

处理：
  - 外部依赖故障：等待恢复，recovering Runs 在 callback 到达后自动恢复
  - agent-kernel 网络问题：按 §13.5 网络分区降级流程处理
  - 模型变更引起：在 LLMGatewayPolicy 中切换 fallback_models，触发手动 Evolve
  - 无法自动恢复：batch_cancel_runs(filter={state: recovering}, reason="incident_XXXX")
```

### 30.2 EvolveSession 卡在 evaluating 阶段超过 24h

**诊断**：
```
  get_evolve_session(session_id) 查看当前 pipeline 步骤
  若 status=evaluating 且 stuck > 24h：
    - 检查 EvalDataset 的 dataset_version 是否存在（可能被意外删除）
    - 检查离线评估任务是否有足够的 sample（min_evaluation_sample_size）
    - 检查是否有并发 EvolveSession 持有同一 task_family 的锁
  
处理：
  - abort_evolve_session(session_id, reason) 中止（已完成步骤不回滚）
  - 修复根因后重新触发 EvolveSession
```

### 30.3 hi-agent 实例 OOM 崩溃后 Run 孤儿接管失败

**场景**：实例崩溃，agent-kernel 标记 Run 为 orphan，但无其他 healthy 实例存活。

```
处理：
  1. 启动新实例（自动重连 agent-kernel）
  2. 新实例启动后调用 list_runs(filter={state: [active, waiting, recovering]})
  3. agent-kernel 会自动向 healthy 实例广播孤儿 Run（adopt_orphan_run）
  4. 若孤儿 Run 过多（> graceful_reload 并发限制），按 CTS 预算优先级排序接管
  
注意：若崩溃发生在 LLM 调用期间，重建 TraceRuntimeView 后可通过 LLMCallRecord
      的 call_id 确认该调用是否已完成（有 result_ref），避免重复 LLM 调用
```

### 30.4 Policy Retirement 被阻塞

**场景**：运维试图 retire 旧 policy，但 RetirementSafetyCheck 返回有活跃 Run 引用。

```
处理：
  1. 使用返回的 active_run_ids 列表，评估这些 Run 是否可以迁移
  2. 若 Run 状态允许迁移：signal_run(run_id, {type: migrate_policy, new_version: ...})
     （需要 agent-kernel 支持 in-flight policy 迁移，需 change_record）
  3. 若 Run 不可迁移（long-running deep_analysis）：等待 Run 自然完成
  4. 可在 TaskFamilyConfig 中更新 default_policies，使后续新 Run 不再使用旧版本
  5. 设置 30 天后重试 retirement（关联全局约定中的最小存活窗口）
```

### 30.5 成本预算超支告警

**触发**：`budget_utilization > 0.8` 的 `budget_warning` 信号，或 `avg_token_per_run > 120%`。

```
诊断：
  1. 按 task_family + stage_id + branch_id 下钻 CostRecord
  2. 识别高消耗的 Stage（通常是 S3 Build/Analyze 的多 Branch 并发）
  3. 检查 branch_pruning_by_code：budget_exhausted 剪枝率高 = 预算已过紧
  4. 检查是否有 A/B 实验正在运行（实验组可能双倍消耗）

处理（短期）：
  - 降低 max_active_branches_per_stage（通过 update_task_family）
  - 暂停非关键 task_family 的 Evolve 实验
  - 将 model_preference 切换到更经济的模型

处理（长期）：
  - 触发 efficiency 维度的 EvolveSession（优化 route_policy 的 pruning_strategy）
```

---

## 31. Capability 调用契约规范（V2.4 新增）

§8.1 定义了 Capability 的注册声明，本节定义 hi-agent 如何**实际调用**已注册的 Capability。

### 31.1 调用协议

```
调用协议：gRPC over TLS（mTLS，见 §29.1）
  服务定义：每个 Capability 实现 CapabilityService gRPC 接口
  
CapabilityService（gRPC 接口）：
  rpc Invoke(CapabilityRequest) returns (CapabilityResponse)
  rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse)

CapabilityRequest：
  capability_id:    str       # 必须与 CapabilityDescriptor.capability_id 一致
  capability_version: str     # 期望的 schema major 版本（如 "2"）
  action_id:        str       # 幂等键（hi-agent 生成，§11.1）
  attempt_id:       str       # 重试序号
  trace_context:    TraceContext  # 分布式追踪（§12.3）
  input:            bytes     # 按 CapabilityDescriptor.schema_ref 定义的 input schema 序列化
  timeout_ms:       int       # 本次调用超时（hi-agent 根据 CTS 剩余预算设定）
  caller_identity:  str       # hi-agent 实例 ID（用于 capability 侧的审计）

CapabilityResponse：
  action_id:        str       # 回显请求的 action_id（幂等验证）
  status:           SUCCESS | IDEMPOTENT_DUPLICATE | FAILED | CAPABILITY_UNAVAILABLE
  output:           bytes     # 按 schema_ref 定义的 output schema 序列化（status=SUCCESS 时）
  error:            CapabilityError  # status=FAILED 时
  effect_confirmed: bool      # 副作用是否已确认生效（external_write 时重要）

CapabilityError：
  error_code:       INVALID_INPUT | EXTERNAL_DEPENDENCY_FAILED | TIMEOUT | PERMISSION_DENIED | INTERNAL_ERROR
  message:          str
  retryable:        bool      # hi-agent 是否可自动重试
  retry_after_ms:   int       # 若 retryable=true，建议等待时间
```

### 31.2 幂等语义与 status 映射

| status | 含义 | hi-agent 处理 |
|---|---|---|
| `SUCCESS` | 执行成功，effect_confirmed=true | 采集 evidence，推进 Branch |
| `IDEMPOTENT_DUPLICATE` | 相同 action_id 已执行成功，返回缓存结果 | 直接采集 output，不重新执行 |
| `FAILED` + `retryable=true` | 可重试失败（如临时网络抖动） | 递增 attempt_id，按 CapabilityDescriptor.retry_backoff 退避后重试，attempt_id > max_retries 时视为 retryable=false |
| `FAILED` + `retryable=false` | 不可重试失败（如权限拒绝）或已达 max_retries | 记录 failure_code=harness_denied，进入路径选择 |
| `CAPABILITY_UNAVAILABLE` | capability 当前不可用（熔断/降级） | 触发熔断器状态更新（§8.1），重新路由 |

### 31.3 调用超时与 effect_unknown 语义

```
timeout_ms 由 hi-agent 根据以下逻辑设定：
  capability_timeout = min(
    CapabilityDescriptor.expected_p99_latency × 3,  # capability 声明的延迟基准
    remaining_cts_wall_clock_budget × 0.2            # 不超过剩余预算的 20%
  )

超时发生时：
  - 若 effect_confirmed=false（未知是否生效）：ActionState → effect_unknown，进入恢复面仲裁（§11.3.1）
  - 若 effect_confirmed=true（已确认生效但响应超时）：ActionState → succeeded，output 标记为 partial
```

### 31.4 Capability 健康检查

熔断器（§8.1）需要知道 Capability 的当前状态：

```
HealthCheckRequest:  {}
HealthCheckResponse:
  status:      SERVING | NOT_SERVING | UNKNOWN
  version:     当前运行的 capability 版本
  load_factor: float (0-1)  # 当前负载（可选，供 Route Engine 参考）
  
hi-agent 的熔断器使用 HealthCheck（每 30s 调用一次）作为 half-open 状态的探针：
  half_open 状态下先 HealthCheck，SERVING 后才发送真实 Invoke
```

---

## 32. Human Gate 审批者界面契约（V2.4 新增）

§16 定义了 Human Gate 的触发语义，本节定义**审批者侧的集成接口**：审批者看到什么内容、如何提交决定、超时如何处理。

### 32.1 审批者上下文格式

Human Gate 打开时，`HumanGateOpened.payload.context_ref` 指向以下结构：

```
GateContext（gate_approver 读取的审批上下文）：
  gate_ref:           str         # Gate 唯一标识
  gate_type:          str         # contract_correction | route_direction | artifact_review | final_approval
  run_id:             str
  task_family:        str
  opened_at:          datetime
  expires_at:         datetime    # 超时时间（见 §32.3）
  
  task_summary:       str         # 任务目标的人类可读摘要（hi-agent 生成）
  current_stage:      str         # 当前所处 Stage
  
  gate_question:      str         # 需要审批者回答的具体问题（hi-agent 生成）
  options:            [GateOption]  # 预设选项（Gate B/C 常用）
  free_form_allowed:  bool        # 是否允许自由文本回复（Gate A/C 常用）
  
  evidence_refs:      [str]       # 支持审批决策的 evidence 引用列表（可按需加载）
  artifact_ref:       str         # 待审核的产物引用（Gate C 专用）
  risk_summary:       str         # 高风险操作摘要（Gate D 专用）

GateOption：
  option_id:    str
  label:        str    # 人类可读标签（如 "继续当前路径"）
  consequence:  str    # 选择此选项的后果描述
```

### 32.2 审批提交 API

```
# 审批者提交审批决定
POST /management/gates/{gate_ref}/resolve
  requires: gate_approver 角色（§28.2 的 Gate 权限细化规则）
  body: GateResolution
  
GateResolution：
  resolution:     approved | rejected | redirect
  selected_option_id: str     # 选择了哪个预设选项（optional）
  free_form_comment:  str     # 自由文本说明（optional，但 rejected 时必填）
  artifact_edit_ref:  str     # 若对产物进行了编辑，提交编辑后版本的引用（Gate C 专用）
  redirect_target:    str     # resolution=redirect 时，将 Gate 转发给其他 gate_approver（可选）

response:
  200 OK: { gate_ref, resolved_at, resolver_identity }
  409 Conflict: Gate 已被其他审批者解决（返回已有的 GateResolution）
  423 Locked: Gate D 等待第二审批人（返回 { pending_second_approval: true }）

# 查询 Gate 状态（审批者 polling 用）
GET /management/gates/{gate_ref}
  response: GateContext + { review_state, resolved_by?, resolved_at? }
```

### 32.3 Gate 超时自动处理

```
GateTimeoutPolicy（在 TaskFamilyConfig.risk_level_policy 中配置）：
  gate_a_timeout:     duration  (默认 24h)
  gate_b_timeout:     duration  (默认 4h)
  gate_c_timeout:     duration  (默认 48h)
  gate_d_timeout:     duration  (默认 72h)

超时行为（按 gate_type）：
  Gate A（contract_correction）：
    超时 → 以当前 TaskContract 继续（不修改），记录 gate_timeout_warning 事件
  
  Gate B（route_direction）：
    超时 → Route Engine 使用 confidence 最高的 Branch 自动继续（不触发人工介入）
    若 confidence 全部 < 0.3：Run 转为 failed，failure_code=callback_timeout
  
  Gate C（artifact_review）：
    超时 → 将产物标记为 human_review_skipped=true，继续推进（不修改产物）
    若 acceptance_criteria 要求 human_reviewed=true：Run 转为 failed
  
  Gate D（final_approval）：
    超时 → 永远不自动批准（安全原则：irreversible_submit 不得无人审批执行）
    超时后 Run 转为 waiting，等待运维人员显式 signal_run(resume 或 abort)

超时前 hi-agent 发送提醒：
  距超时 1h 时：向 gate_approver 发送提醒通知（通过 hi-agent 配置的 notification_backend）
```

---

## 33. 多租户扩展路径（V2.5 新增）

V1 面向单一组织内部使用，暂不实现多租户。但以下设计要点确保 V1 的架构决策不阻塞 V2 的多租户扩展。

### 33.1 从 task_family 到 tenant 的映射

```
V1 现状：
  task_family 是最高隔离单元——配置、policy、Skill、CTS 预算均按 family 管理
  不同 family 之间无资源隔离（共享 LLM Gateway、event log、MemoryStore）

V2 扩展路径：
  引入 tenant_id 作为 task_family 之上的隔离层：
  
  Tenant:
    tenant_id:            str
    owned_task_families:  [task_family]  # 一个 tenant 可拥有多个 family
    resource_quota:       TenantQuota
    data_partition_key:   str            # 数据隔离标识

  TenantQuota:
    max_concurrent_runs:       int       # 本 tenant 的最大并发 Run 数
    max_token_budget_per_day:  int       # 每日 LLM token 预算
    max_evolve_sessions:       int       # 同时活跃的 EvolveSession 数
    max_storage_gb:            int       # event log + payload + memory 总存储配额
```

### 33.2 V1 中的前向兼容设计

为确保 V2 多租户扩展不需要重写 V1 代码，V1 实现时应遵循以下约定：

```
1. 所有数据存储路径中包含 task_family 作为分区键（而非全局扁平存储）
   好的：event_log/{task_family}/{run_id}/...
   坏的：event_log/{run_id}/...（V2 扩展时无法按 tenant 拆分）

2. API Key 已绑定 task_family 列表（§28.1），V2 只需加一层 API Key → tenant 映射

3. LLMGatewayPolicy 的 rate_limit_group 已存在（§13.9），V2 只需将其与 tenant_id 绑定

4. MemoryStore 和 KnowledgeStore 按 task_family 隔离（§25.3 已如此设计），
   V2 只需加 tenant → [task_family] 的访问控制层

5. V1 中避免创建任何跨 task_family 的全局索引或共享状态
   （除非该状态本身就是系统级的，如 KernelManifest）
```

### 33.3 V2 需要新增的能力

| 能力 | V1 没有 | V2 需要 |
|---|---|---|
| tenant CRUD API | 无 | 需要 |
| 资源配额 enforce | 无（单租户不需要） | agent-kernel 层面限流 |
| 数据物理隔离 | 逻辑分区 | 可选物理分区（按 tenant 分库/分表） |
| 跨 tenant Skill/Knowledge 共享 | 不存在 | 需要"系统级 universal"与"tenant 级 universal"区分 |
| tenant 级计费 | cost_center 存在但无 enforce | 按 tenant 聚合 + 配额预警 |

---

## 34. 任务拆解与并行执行（V2.9 新增）

### 34.1 问题陈述

V2.8 的 `todo_dag` 模式（§6.2.2 模式 4）已支持将任务目标分解为 TodoNode DAG，但所有 TodoNode 仍在**同一个 Run 内作为 Branch 执行**。这意味着：

- 所有子目标共享同一个上下文窗口，复杂任务容易 token 爆炸
- 无法将子目标分派给独立 Worker 做真正的并行执行
- 没有子 Run 级别的独立失败恢复和自闭环能力
- 没有子图/子树的整体分派机制

本节补充从 `todo_dag` 到**跨 Run 任务拆解**的完整设计。

**与 todo_dag 的关系**：
- `todo_dag` 是**轻量分解**——单 Run 内，子目标作为 Branch，适合中等复杂度
- `TaskPlan` 是**重量级分解**——跨 Run，子任务由独立 Worker 执行，适合高复杂度
- 两者由 `DecompositionPolicy` 自动判断选择（§34.5.1）

### 34.2 TaskPlan：第 11 个一等概念

TaskPlan 表达"一个任务如何被拆解为子任务，以及子任务之间的结构关系"。

**设计原则：**

1. **拆解是可选的**：简单任务直接走 CTS，只有 DecompositionPolicy 判断复杂度超过单 Run 能力时才触发
2. **子任务是完整的 Task**：每个子任务拥有独立的 TaskContract、独立的 Run、独立的 CTS
3. **拆解结构是多态的**：DAG / Tree / Linear 三种形式
4. **Worker 自闭环**：被分派的 Worker 独立执行完整 TRACE 循环，不逐步回调 Coordinator

### 34.3 核心数据结构

#### 34.3.1 TaskPlan

```
TaskPlan:
  plan_id:           str                    # 全局唯一
  parent_task_id:    str                    # 被拆解的原始任务
  parent_run_id:     str                    # 拆解发生在哪个 Run 内
  structure_type:    dag | tree | linear    # 拆解结构类型
  root_nodes:        [node_id]             # 入口节点 ID 列表
  nodes:             {node_id: SubTaskNode} # 所有子任务节点
  edges:             [SubTaskEdge]          # 依赖边
  plan_state:        PlanState             # 整体状态
  created_at:        datetime
  version:           int                    # 支持计划修订，从 1 开始递增

PlanState:
  draft         # 拆解完成，等待确认
  confirmed     # 确认可执行
  executing     # 执行中
  paused        # 暂停（等待人工介入或回退中）
  completed     # 所有子任务完成且聚合成功
  failed        # 不可恢复失败
  revised       # 计划被修订，旧版本归档
```

#### 34.3.2 SubTaskNode

```
SubTaskNode:
  node_id:           str                    # plan 内唯一
  task_contract:     TaskContract           # 完整的子任务契约
  node_state:        SubTaskState
  assigned_worker:   str | null             # 被分派到哪个 Worker
  run_id:            str | null             # 子任务的 Run ID（执行后才有）
  
  # 结构信息
  depth:             int                    # 在 DAG/Tree 中的深度
  is_leaf:           bool                   # 是否叶子节点
  is_critical_path:  bool                   # 是否在关键路径上
  
  # 执行控制
  max_retries:       int (默认 2)
  retry_count:       int (默认 0)
  timeout:           duration | null
  
  # 结果
  result:            SubTaskResult | null
  failure_code:      str | null             # 使用 §17 Failure Taxonomy + §34.10 扩展码

SubTaskState:
  pending           # 等待依赖完成
  ready             # 依赖已满足，可调度
  dispatched        # 已分派给 Worker
  running           # Worker 正在执行
  waiting_human     # Worker 触发了 Human Gate
  succeeded         # 执行成功
  failed            # 执行失败
  retrying          # 重试中
  rolled_back       # 已回退
  skipped           # 被跳过（依赖失败且非关键路径）

SubTaskResult:
  artifacts:         [str]                  # 产出物引用
  summary:           str                    # 结果摘要（供聚合使用）
  evidence_refs:     [str]                  # 证据引用
  quality_score:     float | null           # 质量评分（由 Evolve 评估）
  duration:          duration | null
```

#### 34.3.3 SubTaskEdge

```
SubTaskEdge:
  source_id:         str                    # 前置节点
  target_id:         str                    # 后继节点
  edge_type:         EdgeType
  data_contract:     str | null             # 上游需要传递给下游的数据契约描述

EdgeType:
  depends_on        # 硬依赖：上游完成才能开始
  soft_depends      # 软依赖：上游完成可提升质量，但不阻塞
  parent_child      # Tree 结构的父子关系
  rollback_to       # 回退边：失败时回退到此节点重新执行
```

### 34.4 三种拆解结构

#### 34.4.1 DAG（有向无环图）

最通用的拆解形式。适用于子任务间有明确的数据/逻辑依赖。

```
示例：研究任务拆解

    [文献调研] ──→ [实验设计] ──→ [实验执行] ──→ [结果分析] ──→ [论文撰写]
         │                                              ↑
         └──→ [数据集准备] ────────────────────────────┘

其中 [文献调研] 和 [数据集准备] 可并行
[实验执行] 依赖 [实验设计] 和 [数据集准备] 都完成
```

**DAG 调度规则：**

```
1. 入度为 0 的节点立即进入 READY 状态
2. 节点完成后，更新所有后继节点的依赖计数
3. 所有硬依赖（depends_on）满足的节点进入 READY 状态
4. READY 节点按优先级分派（关键路径优先）
5. 软依赖（soft_depends）不阻塞：上游未完成时下游也可开始，
   但下游 WorkerContext 中标注上游状态为 incomplete
```

#### 34.4.2 Tree（探索树）

适用于需要搜索最优解的场景。支持蒙特卡洛树搜索模式。

```
示例：方案选型任务

                     [目标分析]
                    /     |     \
          [方案A调研] [方案B调研] [方案C调研]     ← 同层并行探索
              |           |           |
          [方案A验证] [方案B验证] [方案C验证]     ← 同层并行验证
              |           |           |
           0.7分        0.9分       0.4分         ← 评分剪枝
                          |
                     [方案B深化]                  ← 选最优继续
                          |
                     [最终交付]
```

**Tree 调度规则：**

```
1. 同一层级的兄弟节点可并行执行
2. 父节点完成后，子节点才能开始
3. 剪枝：当某层所有兄弟完成后，Coordinator 评估 quality_score，剪掉低分支
4. 回溯：当所有叶子都失败时，回溯到最近分支点，生成新探索方向
5. 蒙特卡洛模式（可选）：不等所有兄弟完成，基于早期信号动态决定展开哪些子节点
```

**与 §6.2.2 MCTS 模式的关系**：§6 的 MCTS 是单 Run 内的轨迹搜索；此处的 Tree 是跨 Run 的任务分解搜索。两者可嵌套——Worker 内部仍可使用 §6 的 MCTS 模式。

#### 34.4.3 Linear（线性序列）

退化的 DAG，等价于 TODO List。适用于简单顺序任务。

```
示例：部署任务

    [代码审查] → [构建] → [测试] → [部署] → [验证]
```

**Linear 调度规则：**

```
1. 严格顺序执行，前一个完成才启动下一个
2. 失败时可选：重试当前 / 回退到上一个 / 终止整个计划
```

**与 todo_dag 的区分**：Linear TaskPlan 与 todo_dag 的区别在于子任务是否独立 Run。如果所有子目标可在单 Run 上下文窗口内完成，应优先使用 todo_dag（§6.2.2）；只有当子任务需要独立上下文、独立失败恢复、或真正并行执行时，才升级为 Linear TaskPlan。

#### 34.4.4 模式选择矩阵

| 任务特征 | 推荐结构 | 理由 |
|---|---|---|
| 子目标间有明确依赖、需并行加速 | DAG | 拓扑排序 + 并发调度 |
| 需对比多个方案后选最优 | Tree | 并行探索 + 剪枝 |
| 简单顺序步骤但需独立上下文 | Linear | 最低调度开销 |
| 子目标简单、单 Run 可容纳 | todo_dag（§6.2.2） | 不需要跨 Run 开销 |

### 34.5 拆解流程

#### 34.5.1 DecompositionPolicy

```
DecompositionPolicy:
  should_decompose(contract: TaskContract, context: TaskView) -> bool
    判断条件（至少满足其一）：
    - goal 包含多个独立子目标且预估总 token 超出单 Run 窗口
    - 预估执行步骤超过 CTS 预算（max_total_branches_per_run）
    - task_family 配置中 decomposition_mode = mandatory
    - 用户在 constraints 中显式指定拆解策略
    
    如果满足条件但复杂度中等（预估子目标 ≤ 5 且无并行需求）→ 推荐 todo_dag（§6.2.2）
    如果复杂度高或需要并行 → 返回 True，进入 TaskPlan 模式

  select_structure(contract: TaskContract, context: TaskView) -> PlanStructure
    - 子目标间有明确依赖 → DAG
    - 需要对比多个方案 → TREE
    - 简单顺序步骤 → LINEAR

  decompose(contract: TaskContract, context: TaskView) -> TaskPlan
    执行拆解，产出 TaskPlan。
    此方法通常需要 LLM 调用来理解任务结构。
    拆解结果必须经过验证（§34.5.2）。
```

#### 34.5.2 拆解验证

TaskPlan 创建后必须通过以下验证（与 §6.2.2 Phase 1.5 的 todo_dag 验证一致并扩展）：

| 验证项 | DAG | Tree | Linear | 说明 |
|---|---|---|---|---|
| 无环检测 | 必须 | N/A | N/A | 拓扑排序可完成 |
| 可达性 | 必须 | 必须 | 必须 | 所有节点从 root_nodes 可达 |
| 终止性 | 必须 | 必须 | 必须 | 存在叶子节点 |
| 子任务契约完整性 | 必须 | 必须 | 必须 | 每个 node.task_contract 有 goal + acceptance_criteria |
| acceptance_criteria 覆盖 | 必须 | 必须 | 必须 | 父任务每条 criterion 被至少一个子任务覆盖 |
| 数据契约一致性 | 应该 | 应该 | 应该 | edge.data_contract 描述的上游输出匹配下游输入 |
| 预估总 budget 不超限 | 必须 | 必须 | 必须 | 所有子任务 budget 之和 ≤ 父任务 budget × subtask_budget_fraction |

任一 "必须" 项验证失败 → 触发 **Gate B（route_direction）**，请人工修正拆解。

#### 34.5.3 拆解时机

拆解发生在 TRACE 的 S1 Understand 阶段：

```
S1 Understand:
  1. 构建 TaskContract
  2. DecompositionPolicy.should_decompose()
  3. 如果 False → 正常进入 S2（或走 todo_dag 模式）
  4. 如果 True：
     a. select_structure() → PlanStructure
     b. decompose() → TaskPlan（可能需要 LLM 调用）
     c. validate()（§34.5.2）
     d. 如果 risk_level >= high → Gate B 确认
     e. plan_state = confirmed

S2/S3（进入 Coordinator 模式）:
  Coordinator.schedule(plan)
  → 分派 Worker，等待完成，处理失败/回退
  → Coordinator.aggregate()

S4 Synthesize（使用聚合结果继续正常推进）
S5 Review / Finalize（正常推进）
```

### 34.6 执行模型

#### 34.6.1 角色定义

```
┌──────────────────────────────────────────────────┐
│                   Coordinator                     │
│  - 持有完整 TaskPlan                              │
│  - 调度子任务到 Worker                             │
│  - 监控执行状态                                    │
│  - 处理失败和回退                                  │
│  - 聚合结果                                        │
│  - 运行在原始 Run 的 S2/S3 阶段内                  │
└──────────┬───────────┬───────────┬───────────────┘
           │           │           │
           v           v           v
    ┌───────────┐ ┌───────────┐ ┌───────────┐
    │  Worker 1 │ │  Worker 2 │ │  Worker 3 │
    │  (子Run)  │ │  (子Run)  │ │  (子Run)  │
    │  独立CTS  │ │  独立CTS  │ │  独立CTS  │
    │  自闭环   │ │  自闭环   │ │  自闭环   │
    └───────────┘ └───────────┘ └───────────┘
```

#### 34.6.2 Coordinator 职责

Coordinator 是原始 Run 内的调度中枢，不是独立系统。

```
Coordinator 接口：

  schedule(plan: TaskPlan) -> None
    调度循环：
    1. 找出所有 READY 状态的节点
    2. 按优先级排序（关键路径优先）
    3. 分派给可用 Worker（受 max_concurrent_workers 限制）
    4. 等待任意 Worker 完成（event-driven，通过 RuntimeAdapter.stream_run_events 监听子 Run）
    5. 更新依赖图状态
    6. 重复直到所有节点完成或不可恢复失败

  dispatch(node: SubTaskNode) -> str
    分派子任务：
    1. 构造 WorkerContext（§34.6.3）
    2. 附加上游已完成节点的 result.artifacts 和 result.summary
    3. 如果是子图/子树分派（§34.6.4），打包相关节点为嵌套 TaskPlan
    4. 调用 RuntimeAdapter.start_child_run()
    5. 更新 node_state = dispatched

  on_worker_complete(node_id: str, result: SubTaskResult) -> None
    1. 记录 result 到 node.result，更新 node_state = succeeded
    2. 更新所有后继节点的依赖计数
    3. 如果是 Tree 结构，执行剪枝评估
    4. 触发下一轮 schedule()

  on_worker_failed(node_id: str, failure_code: str) -> None
    1. 判断是否可重试（retry_count < max_retries）
    2. 如果可重试 → 更新 node_state = retrying，重新 dispatch
    3. 如果不可重试 → 交给 RollbackPolicy（§34.7）

  aggregate(plan: TaskPlan) -> AggregatedResult
    1. 收集所有完成节点的 result.artifacts 和 result.summary
    2. 按 edge.data_contract 组装（有依赖关系的按拓扑顺序合并）
    3. 生成聚合摘要
    4. 写入原始 Run 的 Capture 层
```

#### 34.6.3 Worker 自闭环

每个 Worker 是一个完整的 TRACE 执行体，拥有独立的 Run 生命周期。

```
WorkerContext:
  worker_id:          str
  task_contract:      TaskContract           # 子任务契约（含 parent_task_id、parent_plan_id）
  parent_run_id:      str                    # 父 Run 引用
  parent_plan_id:     str                    # 所属 TaskPlan
  node_id:            str                    # 在 Plan 中的节点 ID
  
  # 上游产出
  upstream_artifacts: [str]                  # 上游节点的产出物引用
  upstream_summaries: [str]                  # 上游节点的结果摘要
  
  # 子图/子树分派时使用
  sub_plan:           TaskPlan | null        # 被分派的子图/子树（§34.6.4）
  
  # 执行约束
  budget:             Budget                 # 时间/token/cost 预算（从父任务按比例分配）
  stage_graph:        StageGraphDef | null   # 可选覆盖，null 则使用 task_family 默认
```

**Worker 自闭环保证（5 条不变量）：**

```
INV-W1  独立 CTS：Worker 有自己的 Stage Graph 和 Trajectory Tree
INV-W2  独立 Memory：Worker 的 L0/L1/L2 独立于父 Run（L3 Episodic 和 Knowledge 可共享读取）
INV-W3  独立 Human Gate：Worker 可独立触发 Gate C（artifact_review）和 Gate D（final_approval）
INV-W4  独立失败恢复：Worker 内部的 Branch 失败不直接上报 Coordinator，Worker 先按自身 CTS 策略恢复
INV-W5  结果上报：Worker 完成后，将 SubTaskResult 通过 Run 完成事件上报给 Coordinator
```

**关键约束**：Worker 不得修改 TaskPlan 结构。只有 Coordinator 有权修改计划。

#### 34.6.4 子图/子树分派

当 TaskPlan 中存在可独立执行的连通子图/子树时，Coordinator 可以将整个子结构分派给单个 Worker，而非逐节点分派。

```
extract_dispatchable_subgraph(plan: TaskPlan, entry_node_id: str) -> TaskPlan

  提取条件：
  - 子图内所有节点的外部依赖（指向子图外节点的 depends_on 边）已满足
  - 子图内部的依赖关系完整（无悬挂引用）
  - 子图有明确的入口节点（entry_node_id）和出口节点（叶子节点或无子图内后继的节点）

  返回：
  - 一个新的 TaskPlan（structure_type 继承原结构或降级为 linear）
  - 原 plan 中对应节点标记为 dispatched
```

被分派子图的 Worker 内部运行一个嵌套的 Coordinator，递归执行同样的调度逻辑。

**深度限制**：嵌套层数不得超过 `max_decomposition_depth`（§34.9，默认 3 层）。超出时 Worker 必须在单 Run 内完成（可降级为 todo_dag 模式）。

### 34.7 回退机制

#### 34.7.1 节点级回退

```
RollbackPolicy:
  on_failure(node: SubTaskNode, plan: TaskPlan) -> RollbackAction

  决策优先级：
  1. retry_count < max_retries                    → RETRY（重新执行当前节点）
  2. 存在 rollback_to 类型的出边                    → ROLLBACK（回退到指定节点）
  3. node.is_critical_path == true                 → FAIL_PLAN（整体失败）
  4. 非关键路径                                     → SKIP（跳过，标记 skipped）
  5. 反复失败且有新证据表明拆解有误                  → REVISE_PLAN（触发计划修订）

RollbackAction:
  retry          # 重新执行当前节点
  rollback       # 回退到 rollback_to 边指定的节点重新执行
  skip           # 跳过当前节点，后继节点检查是否仍可执行
  fail_plan      # 整体失败，终止所有 Worker
  revise_plan    # 触发计划修订（§34.7.3）
```

#### 34.7.2 级联回退

当某节点需要回退时，其所有已执行的下游节点可能需要失效：

```
cascade_rollback(plan: TaskPlan, rollback_to_node_id: str) -> [affected_node_id]

  1. 从 rollback_to_node_id 出发 BFS 遍历所有后继节点
  2. 已完成（succeeded）的后继 → 标记为 pending（等待重新执行）
  3. 正在执行（running/dispatched）的后继 → 通过 RuntimeAdapter.cancel_child_run() 取消
  4. 返回受影响的节点 ID 列表
  5. rollback_to_node_id 本身重置为 ready，等待重新调度
```

#### 34.7.3 计划修订

当回退不足以解决问题时（如拆解方案本身有缺陷），Coordinator 可触发计划修订：

```
计划修订流程：
  1. Coordinator 收集当前所有已完成节点的 result 和失败节点的 failure_code
  2. 重新调用 DecompositionPolicy.decompose()，附加失败上下文
  3. 生成新版本 TaskPlan（version += 1）
  4. 保留已成功且不受影响的节点结果（避免重复执行）
  5. 新计划必须经过 Gate B（route_direction）确认
  6. 旧版本归档（plan_state = revised）
  7. 新版本开始执行（plan_state = confirmed → executing）

约束：
  - 修订次数不得超过 max_plan_revisions（§34.9，默认 3）
  - 超限后 → plan_state = failed，failure_code = max_revisions_exceeded
```

### 34.8 反馈与优化

#### 34.8.1 执行时信号

Worker 执行过程中可向 Coordinator 发送的信号（通过 RuntimeAdapter.signal_run 传递）：

| 信号 | 触发条件 | Coordinator 处理 |
|---|---|---|
| `progress_update` | Worker 完成某个 Stage | 更新进度视图，不干预 |
| `budget_warning` | Worker budget 消耗超过 80% | 评估是否需要扩展 budget 或提前终止 |
| `quality_signal` | Worker 在 S5 Review 的自评分 | 如果低于阈值，考虑补充执行或换策略 |
| `dependency_request` | Worker 发现需要额外上游数据 | 评估是否修订计划增加依赖 |
| `early_termination` | Worker 发现子任务已无意义 | 决定是否剪枝或跳过 |

#### 34.8.2 PlanFeedback

所有子任务完成后的评估，进入 Evolve Engine（§10）：

```
PlanFeedback:
  decomposition_quality:     float [0, 1]    # 拆解质量：子任务划分是否合理
  dependency_accuracy:        float [0, 1]    # 依赖准确性：是否有遗漏/冗余依赖
  parallelism_efficiency:     float [0, 1]    # 并行效率 = critical_path_duration / total_wall_clock
  rollback_count:             int             # 回退次数
  revision_count:             int             # 计划修订次数
  quality_variance:           float           # 子任务 quality_score 的方差
  total_duration:             duration        # 总墙钟时间
  critical_path_duration:     duration        # 关键路径执行时间
  lessons:                    [str]           # 可沉淀的经验教训
```

#### 34.8.3 Evolve 集成

PlanFeedback 通过 §10 的 Inline Evolve 和 Batch Evolve 双轨优化：

```
Inline Evolve（每次 Run 结束后立即）：
  - 如果 rollback_count > 0：记录失败模式，下次类似任务调整拆解粒度
  - 如果 parallelism_efficiency < 0.5：记录依赖关系优化建议
  - 如果 quality_variance > 阈值：记录子任务粒度不均匀

Batch Evolve（定期离线）：
  - 跨多个 TaskPlan 统计拆解模式：哪些 task_family 适合 DAG/Tree/Linear
  - 优化 DecompositionPolicy 的判断阈值
  - 如果某个拆解模式反复出现且效果好 → 结晶为 CompositeSkill（§8.3 composite 类型）
```

### 34.9 CTS 预算扩展

在 §6.3 CTS 预算基础上新增以下参数：

| 参数 | 说明 | 默认值 |
|---|---|---|
| `max_decomposition_depth` | 最大嵌套拆解层数 | 3 |
| `max_subtasks_per_plan` | 单个 TaskPlan 最大子任务节点数 | 20 |
| `max_concurrent_workers` | 最大并发 Worker 数 | 5 |
| `max_plan_revisions` | 最大计划修订次数 | 3 |
| `subtask_budget_fraction` | 所有子任务可使用的父 budget 总比例 | 0.8 |

这些参数在 `TaskFamilyConfig`（§8.2）中按 task_family 配置，随 `PolicyVersionSet`（§9.1）冻结到 Run。

### 34.10 失败码扩展

在 §17 Failure Taxonomy 基础上新增：

| 失败码 | 含义 |
|---|---|
| `decomposition_failed` | 任务拆解失败（LLM 无法生成有效 plan） |
| `plan_validation_failed` | TaskPlan 验证失败（有环、不可达、criteria 未覆盖等） |
| `worker_timeout` | Worker 执行超时 |
| `aggregation_failed` | 子任务结果聚合失败 |
| `max_revisions_exceeded` | 计划修订次数超限 |
| `critical_path_broken` | 关键路径上的节点不可恢复失败 |
| `depth_limit_exceeded` | 嵌套拆解深度超限 |

### 34.11 TaskContract 扩展

在 §6.2 TaskContract 基础上新增可选字段（向后兼容）：

```
TaskContract 扩展字段（V2.9）：
  parent_task_id:       str | null         # 如果是子任务，指向父任务
  parent_plan_id:       str | null         # 如果是子任务，指向所属 TaskPlan
  decomposition_hint:   str | null         # 用户可选的拆解提示（如"按章节拆分"）
```

当 `parent_task_id != null` 时，该 Task 被视为子任务，其 Run 是子 Run。

### 34.12 RuntimeAdapter 扩展

在现有 RuntimeAdapter 接口（§7.1）基础上新增：

```
RuntimeAdapter 新增方法（V2.9）：

  update_plan_node_state(plan_id: str, node_id: str, state: str, result: dict | null) -> None
    更新 TaskPlan 中某个节点的执行状态。
    写入 event log 作为 plan_node_state_changed 事件。

  start_child_run(parent_run_id: str, plan_id: str, node_id: str, task_contract: dict) -> str
    启动子 Run。
    kernel 需记录 parent_run_id → child_run_id 关系。
    返回 child_run_id。

  query_child_runs(parent_run_id: str) -> [dict]
    查询某个 Run 的所有子 Run 状态。
    返回子 Run 列表（run_id, run_state, node_id）。

  cancel_child_run(child_run_id: str, reason: str) -> None
    取消子 Run。用于级联回退时终止正在执行的 Worker。
```

### 34.13 agent-kernel 影响评估

| 能力 | 说明 | kernel 改动复杂度 |
|---|---|---|
| 父子 Run 关系 | Run 表增加 `parent_run_id` 可选字段 | 低 |
| 子 Run 查询 | 按 parent_run_id 查询所有子 Run | 低 |
| TaskPlan 事件持久化 | event log 新增 plan_* 事件类型 | 中 |
| 子 Run 取消传播 | 父 Run 取消时级联取消所有子 Run | 中 |
| 并发子 Run 限制 | 治理同时活跃的子 Run 数量上限 | 中 |

**不需要 kernel 改动的部分**（全部在 hi-agent 内实现）：

- DecompositionPolicy（拆解逻辑）
- Coordinator（调度、聚合、回退）
- RollbackPolicy（回退策略）
- PlanFeedback（评估和 Evolve 集成）
- Worker 的 CTS 执行（复用现有 RunExecutor）

### 34.14 身份规约扩展

在 §19 身份规约基础上新增：

| 身份 | 唯一性要求 | 生成责任 |
|---|---|---|
| `plan_id` | 全局唯一 | hi-agent |
| `node_id` | plan 内唯一 | hi-agent |
| `worker_id` | plan 内唯一（= 子 run_id） | agent-kernel |

### 34.15 与 Memory 系统的集成

```
L0（Raw）：TaskPlan 创建、修订、节点状态变更均作为事件写入 event log
L1（Compressed）：每个 Worker 的 L1 独立；Coordinator 的 L1 包含调度决策和聚合摘要
L2（Index）：原始 Run 的 L2 包含 TaskPlan 执行概要
  - 拆解结构类型
  - 子任务数量和完成状态
  - 关键路径和实际执行时间
  - 聚合结果摘要
L3（Episodic）：成功的 TaskPlan 模式可沉淀为 Episode，供后续类似任务参考
Knowledge：Worker 共享读取全局 Knowledge（INV-W2），但不直接写入——写入由 Evolve 统一管理
```

### 34.16 兼容性分析

| V2.8 概念 | V2.9 变化 | 兼容性 |
|---|---|---|
| Task | 增加可选的 parent_task_id / parent_plan_id | 完全兼容（null 时行为不变） |
| Run | 增加可选的 parent_run_id | 完全兼容（null 时行为不变） |
| Stage | 无变化 | 完全兼容 |
| Branch | 无变化（Branch 仍是 Run 内探索分支，不是子任务） | 完全兼容 |
| Task View | Worker 的 Task View 独立 | 完全兼容 |
| Action | 无变化 | 完全兼容 |
| Memory | Worker Memory 独立，Coordinator 可聚合 | 完全兼容 |
| Knowledge | 共享读取 | 完全兼容 |
| Skill | CompositeSkill 可引用 TaskPlan 模式 | 向前扩展 |
| Feedback | 增加 PlanFeedback 类型 | 向前扩展 |
| todo_dag | 作为轻量级替代继续存在 | 完全兼容 |

**零开销保证**：不需要拆解的任务（`should_decompose = false`）的执行路径与 V2.8 完全一致。

### 34.17 设计决策记录

**ADR-11：TaskPlan 是独立一等概念，不是 Branch 的扩展**

Branch 在 §5 中明确定义为"轨迹树中的逻辑分支（语义对象，不等于 child run）"。将 Branch 扩展为子任务会违反这个核心约束。因此引入 TaskPlan 作为正交概念：Branch 管单 Run 内的探索，TaskPlan 管跨 Run 的分解。

**ADR-12：Worker 必须自闭环**

如果 Worker 每步都回调 Coordinator：Coordinator 成为串行瓶颈，Worker 数量增加时 Coordinator 上下文窗口爆炸，无法实现真正并行。自闭环 Worker 只在完成/失败时上报，Coordinator 只关心调度和聚合。

**ADR-13：支持三种拆解结构而非统一为 DAG**

DAG 可以表达 Linear（退化的链式 DAG），但不能优雅表达 Tree 的"展开-评估-剪枝"模式。Tree 的调度语义（同层并行、评分剪枝、回溯）与 DAG 的拓扑排序语义本质不同。保留三种类型使调度逻辑更清晰，实现时 Linear 可复用 DAG 调度器。

**ADR-14：拆解可选，不强制**

强制拆解会导致简单任务增加不必要的调度开销，破坏 V2.8 已验证的单 Run 执行路径。`DecompositionPolicy.should_decompose()` 是入口守卫，默认返回 False。

**ADR-15：TaskPlan 与 todo_dag 共存而非替代**

todo_dag（§6.2.2）是已验证的轻量级模式，适合中等复杂度任务。TaskPlan 适合高复杂度、需要独立上下文和真正并行的任务。两者的选择由 DecompositionPolicy 自动判断，无需用户干预。

---

## Appendix A：数据结构索引（V2.5 新增）

以下索引列出所有架构规范中定义的核心数据结构及其定义位置，便于快速查找。

| 数据结构 | 定义位置 | 用途 |
|---|---|---|
| `TaskContract` | §6.2, §23.4 | 任务契约（goal, constraints, acceptance_criteria） |
| `TaskFamilyConfig` | §8.2 | task_family 配置（Stage Graph, CTS, capabilities, policies） |
| `TaskFamilyBootstrap` | §10.2.1 | 新 family 冷启动配置 |
| `CapabilityDescriptor` | §8.1 | 能力模块注册声明 |
| `CapabilityRequest / Response` | §31.1 | Capability gRPC 调用契约 |
| `SkillRecord` | §8.3 | Skill 生命周期管理 |
| `PolicyVersionSet` | §9.1 | Run 启动时冻结的四版本集合 |
| `PolicyContentSpec` | §9.1.2 | Policy 内容 schema 框架 |
| `KernelManifest` | §9.3 | agent-kernel 版本兼容声明 |
| `StageGraphDef / SubgraphRef` | §6.5 | Stage Graph 子图引用与继承 |
| `CTSBudgetTemplate` | §6.6 | CTS 预算模板 |
| `RouteEngineInput / Output` | §21.1 | Route Engine 接口 |
| `BranchProposal / BranchPruneRecord` | §21.1 | Branch 提议与剪枝记录 |
| `AcceptanceCriteriaEvaluator` | §21.3 | 验收标准评估接口 |
| `EvolveChangeSet` | §10.3 | Evolve 变更集 |
| `EvolveSessionFailureRecord` | §10.2 | EvolveSession 失败诊断 |
| `QualityGate` | §10.3.1 | 量化质量门 |
| `ExperimentConfig` | §10.2 | A/B 实验配置 |
| `EventEnvelope` | §12.1.1 | 事件日志通用 envelope |
| `TraceContext` | §12.3 | 分布式追踪上下文 |
| `CostRecord` | §13.10 | 成本归因记录 |
| `LLMGatewayPolicy` | §13.9 | LLM Gateway 配置 |
| `LLMCallRecord` | §11.1.2 | LLM 调用 checkpoint |
| `StartRunRequest` | §11.3 | Run 启动请求（含 replay_mode） |
| `HiAgentRuntimeConfig` | §13.3 | hi-agent 可热更新运行时配置 |
| `GateContext / GateResolution` | §32.1, §32.2 | Human Gate 审批界面契约 |
| `GateTimeoutPolicy` | §32.3 | Gate 超时自动处理策略 |
| `KnowledgeRecord` | §26.1 | Knowledge 生命周期管理 |
| `EvalDataset / RunSnapshot` | §24.4 | Evolve 离线评估数据集 |
| `NotificationBackend` | §12.1.1 | 告警通道配置 |
| `SkillContent` | §8.3 | Skill 实际可执行内容（V2.6） |
| `PromptTemplateContent` | §8.3 | prompt_template 类 Skill 内容 |
| `ActionPatternContent / ActionStep` | §8.3 | action_pattern 类 Skill 内容 |
| `DecisionRuleContent / Rule` | §8.3 | decision_rule 类 Skill 内容 |
| `ParameterCandidate` | §10.2 | parameter_tuning 候选参数变更 |
| `KnowledgeCandidate` | §10.2 | knowledge_discovery 候选知识 |
| `SkillPolicy.parameters` | §9.1.2 | Skill 注入策略参数空间（V2.6） |
| `TaskViewPolicy.parameters` | §9.1.2 | Task View 构建策略参数空间（V2.6） |
| `TrajectoryNode` | §6.2.1 | 轨迹 DAG 节点（含 quality signal 回传）（V2.7） |
| `StageSummary (L1)` | §25.3 | Stage 压缩摘要（≤2048 tokens）（V2.7） |
| `RunIndex (L2)` | §25.3 | Run 导航层（≤512 tokens）（V2.7） |
| `Episode (L3)` | §25.3 | 跨 Run 情景记忆（≤512 tokens/条）（V2.7） |
| `KnowledgePage` | §26.1 | KnowledgeWiki 页面节点（V2.7） |
| `IndexPage` | §26.1 | KnowledgeWiki 索引导航页（V2.7） |
| `BatchCancelOptions / Result` | §13.1 | 批量取消选项和结果 |
| `TaskPlan` | §34.3.1 | 任务拆解方案（DAG/Tree/Linear 结构）（V2.9） |
| `SubTaskNode` | §34.3.2 | 子任务节点（含独立 TaskContract 和执行状态）（V2.9） |
| `SubTaskEdge` | §34.3.3 | 子任务依赖边（depends_on/soft_depends/parent_child/rollback_to）（V2.9） |
| `SubTaskResult` | §34.3.2 | 子任务执行结果（artifacts + summary + quality_score）（V2.9） |
| `WorkerContext` | §34.6.3 | Worker 启动上下文（含上游产出和子图）（V2.9） |
| `PlanFeedback` | §34.8.2 | TaskPlan 执行质量评估（供 Evolve 使用）（V2.9） |
| `DecompositionPolicy` | §34.5.1 | 拆解决策接口（should_decompose + decompose）（V2.9） |
| `RollbackPolicy` | §34.7.1 | 节点失败回退策略（V2.9） |

---

## Appendix B：Spike 建议（V2.5 新增）

在 MVP 阶段 1 正式开发前，建议用 **2-3 天**完成以下端到端 spike，验证关键假设：

```
Spike 范围：
  - 1 个 quick_task family（使用 default CTS budget template）
  - 1 个 read_only Capability（如 mock_search，返回固定结果）
  - Route Engine：规则引擎实现（不用 LLM）
  - MockKernel strict_mode=true
  - 事件日志：内存实现（不接真实 agent-kernel）

验证目标：
  1. Task View 构建延迟：100 evidence_refs 场景下 P99 < 50ms？
  2. 状态机流转完整性：S1→S2→S3→S4→S5 全程无非法转移？
  3. action_id / task_view_id 确定性：同一 Run 重放两次，所有 ID 一致？
  4. 幂等键闭环：相同 action_id 重复 Invoke 返回 IDEMPOTENT_DUPLICATE？
  5. 死路检测：所有 Branch 被 prune 后立即触发 dead_end_detected？

产出物：
  - 一个可运行的 main() 函数（< 500 行）
  - 延迟数据（验证 §24.7 性能基线是否合理）
  - 发现的规范歧义列表（反馈到 ARCHITECTURE.md 修正）
```

### Spike 2：Evolve Pipeline 端到端验证（V2.6 新增）

在 Spike 1 跑通 Run 骨架后，建议再用 **2-3 天**验证 Evolve 最小闭环：

```
Spike 范围：
  - 基于 Spike 1 的 quick_task family（已有若干成功 Run）
  - EvolveSession：human_guided 策略
  - ChangeSet：手动修改 route_policy.pruning_strategy 从 conservative → adaptive
  - 离线评估：route_replay 方法（基于 Spike 1 产生的 Run 历史）
  - 跳过 A/B 实验（使用低频轻量路径 §10.3.2）
  - 手动审批晋升

验证目标：
  1. EvolveSession 状态机：created → collecting → evaluating → promoting → completed 全程？
  2. route_replay 能正确加载历史 TaskView 并用新 policy 重跑 Route Engine？
  3. QualityGate 数字门正确判定通过/不通过？
  4. Policy Promotion 后新 Run 使用新版本 policy？旧 Run 不受影响？
  5. parameter_tuning 策略能根据 optimization_signal 自动生成候选参数变更？

验证 Skill 结晶（可选，需 LLM）：
  6. 手动创建一个 prompt_template 类 Skill（status=draft）
  7. Skill 注入到 Task View 后 Run 成功完成
  8. Skill 从 draft → candidate → active 全生命周期走通

产出物：
  - Evolve Pipeline 骨架代码（< 300 行核心逻辑）
  - route_replay 的实际运行时间和准确度数据
  - V1 Evolve 实现路线的可行性确认或修正建议
```

### V1 Evolve 最小可用组合总结（V2.6 新增）

```
以下 4 个组件的组合是 Evolve 从"停在嘴上"变为"可以跑起来"的最小集：

  1. human_guided + parameter_tuning（§10.2 策略 1+2）
     → 运维人员可以手动调参并验证效果
     → 系统可以基于统计信号自动建议参数调整

  2. route_replay（§10.2 离线评估方法 1）
     → 用历史 TaskView 重放 Route Engine 决策
     → 不需要 LLM 调用，成本为零

  3. prompt_template + action_pattern（§8.3 SkillContent 类型 1+2）
     → 最常用的两种 Skill 类型，覆盖 80% 场景
     → prompt_template 由人工编写或 meta-LLM 提取
     → action_pattern 由频繁子序列挖掘自动提取

  4. 低频轻量路径（§10.3.2）
     → 低流量时跳过 A/B 实验
     → 强化离线评估 + 人工审批替代在线验证

这 4 个组件的实现成本：约 2-3 周工程量（不含 agent-kernel 依赖项）。
实现后效果：每个 task_family 可以通过手动或半自动方式持续优化策略，
有数据驱动的质量门控制，有安全的灰度发布和回滚能力。
```

