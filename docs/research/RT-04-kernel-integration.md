# RT-04: agent-kernel 与 hi-agent 真实对接

> 优先级：P0
> 预计时间：3-5 天
> 前置依赖：无
> 负责人：待分配
> 状态：TODO

## 1. 核心问题

hi-agent 目前通过 MockKernel 开发。真实对接 agent-kernel 时，两套系统的概念模型、状态机、事件 schema 可能存在不匹配。这些不匹配如果在实施后期才发现，修复成本极高。

**必须回答的问题：**
- Q1: hi-agent 的 RuntimeAdapter protocol 与 agent-kernel 的实际 API 有多少 gap？
- Q2: 两套状态机（hi-agent §14 vs agent-kernel contracts.py）能否一一映射？
- Q3: hi-agent 的 EventEnvelope 与 agent-kernel 的 RuntimeEvent 的 schema 差异是什么？
- Q4: agent-kernel 的 Temporal substrate 如何承载 TRACE 的 Run/Stage/Branch 概念？

## 2. 背景

### agent-kernel 已有能力（基于源码扫描）
```
核心契约（kernel/contracts.py）：
  - RunLifecycleState: created | ready | dispatching | waiting_result | waiting_external | recovering | completed | aborted
  - EffectClass: read_only | idempotent_write | compensatable_write | irreversible_write
  - SideEffectClass: read_only | local_write | external_write | irreversible_submit
  - RuntimeEvent: { run_id, event_id, commit_offset, event_type, payload_ref, payload_json, idempotency_key, ... }

运行时（kernel/）：
  - turn_engine.py: Turn FSM（canonical 7-state path）
  - reasoning_loop.py: context_port + llm_gateway + output_parser 协调
  - minimal_runtime.py: 最小运行时
  - task_manager/: TaskDescriptor, TaskAttempt, TaskWatchdog, RestartPolicy

持久化（kernel/persistence/）：
  - ports.py: EventLogStore / DedupeStore / CircuitBreakerStore / RecoveryOutcomeStore protocols
  - sqlite_event_log.py / pg_event_log.py: 双后端实现
  - sqlite_dedupe_store.py / pg_dedupe_store.py: 幂等键存储

恢复（kernel/recovery/）：
  - PlannedRecoveryGateService, CompensationRegistry, ReflectionPolicy

Substrate:
  - substrate/temporal/: Temporal Workflow adaptor
  - substrate/local/: 本地 FSM adaptor（测试用）
```

### hi-agent 的期望接口（§13 + RuntimeAdapter protocol）
```
RuntimeAdapter protocol（hi-agent 定义）：
  start_run(req: StartRunRequest) -> StartRunResponse
  open_stage(stage_id) -> None
  mark_stage_state(stage_id, state) -> None
  open_branch(branch_id) -> None
  mark_branch_state(branch_id, state) -> None
  record_task_view(record) -> task_view_id
  bind_task_view_to_decision(task_view_id, decision_ref) -> None
  signal_run(signal) -> None
  query_run(run_id) -> RunInfo
  query_trace_runtime(run_id) -> TraceRuntimeView
```

## 3. 研究内容

### 3.1: 接口映射表

逐一对照 hi-agent RuntimeAdapter 的每个方法与 agent-kernel 的实际 API：

```
| hi-agent 方法 | agent-kernel 对应 | 映射方式 | Gap |
|---|---|---|---|
| start_run() | minimal_runtime.start_run()? | ? | ? |
| open_stage() | ? | ? | kernel 没有显式 Stage 概念？ |
| mark_stage_state() | ? | ? | kernel 的 RunLifecycleState 没有 StageState？ |
| open_branch() | ? | ? | kernel 有 branch_monitor.py，但 Branch 是什么？ |
| record_task_view() | persistence/sqlite_task_view_log.py | ? | schema 对齐？ |
| query_trace_runtime() | ? | ? | kernel 是否提供这个查询？ |
```

**工作方式：**
1. 读取 hi-agent/runtime_adapter/protocol.py 的完整定义
2. 读取 agent-kernel 的所有公开 API（从 minimal_runtime.py + turn_engine.py + persistence/ports.py 提取）
3. 逐一填写映射表
4. 标记所有 Gap（hi-agent 期望但 kernel 没有 / kernel 提供但 hi-agent 不需要 / 语义不匹配）

### 3.2: 状态机映射

两套状态机的详细对比：

```
hi-agent RunState（§14.1）:
  created → active → waiting → recovering → completed / failed / aborted

agent-kernel RunLifecycleState（contracts.py）:
  created → ready → dispatching → waiting_result → waiting_external → recovering → completed / aborted

映射问题：
  - hi-agent 的 "active" 对应 kernel 的 "ready" + "dispatching"？
  - hi-agent 的 "waiting" 对应 kernel 的 "waiting_result" + "waiting_external"？
  - hi-agent 有 "failed"，kernel 只有 "aborted"——failed 和 aborted 在 kernel 侧如何区分？

hi-agent StageState（§14.3）:
  pending → active → blocked → completed / failed

agent-kernel 有对应概念吗？turn_engine.py 的 Turn FSM 是 Stage 的等价物吗？

hi-agent BranchState（§14.4，V2.8 声明为 TrajectoryNode 视图）:
  proposed → active → waiting → pruned / succeeded / failed

agent-kernel 的 branch_monitor.py 跟踪的是什么状态？
```

**产出：** 一份完整的状态映射表 + 不可映射状态的处理建议（adapter 转换 / 需要 kernel 扩展 / 在 hi-agent 侧模拟）

### 3.3: Event Schema 对齐

```
hi-agent EventEnvelope（§12.1.1）:
  event_id (ULID), event_type, schema_version, run_id, stage_id, branch_id,
  action_id, occurred_at, produced_by, trace_context, payload_ref

agent-kernel RuntimeEvent（contracts.py）:
  run_id, event_id, commit_offset, event_type, event_class, event_authority,
  ordering_key, wake_policy, created_at, idempotency_key, payload_ref, payload_json

差异分析：
  - hi-agent 有 stage_id / branch_id / action_id / trace_context → kernel 没有？
  - kernel 有 commit_offset / ordering_key / wake_policy / event_authority → hi-agent 没有？
  - payload_ref 的格式/存储位置是否一致？
```

**产出：** Event schema 适配层设计（hi-agent EventEnvelope ↔ agent-kernel RuntimeEvent 的双向转换）

### 3.4: Temporal 集成路径

```
问题：
  1. hi-agent 的 Run 主循环如何映射为 Temporal Workflow？
     - 整个 Run = 一个 Workflow？
     - 每个 Stage = 一个 Activity？
     - Branch 并行 = Temporal Workflow 并行 Activity？

  2. Stage 转移是什么 Temporal 原语？
     - Temporal Activity？
     - Temporal Signal？
     - Temporal Child Workflow？

  3. Human Gate 等待审批如何映射？
     - Temporal Signal wait？
     - Temporal Timer + Signal？

  4. 崩溃恢复：
     - Temporal 自动重放 Workflow → hi-agent 的 Run 从哪里恢复？
     - Run 内部状态（TrajectoryNode DAG, L1/L2 缓存）如何在重放后重建？

研究方式：
  - 读 agent-kernel/substrate/temporal/ 的源码，理解现有的 Temporal 集成方式
  - 设计一个 minimal Temporal Workflow 原型：单 Stage、单 Branch、无 Gate
  - 验证 Workflow 崩溃后自动恢复时，hi-agent 状态是否一致
```

## 4. 产出物清单

| 产出 | 格式 | 位置 |
|------|------|------|
| 接口映射表 | Markdown 表格 | `docs/research/data/rt-04-api-mapping.md` |
| 状态机映射表 | Markdown 表格 + 状态转换图 | `docs/research/data/rt-04-state-mapping.md` |
| Event schema adapter 设计 | Markdown + Python prototype | `docs/research/data/rt-04-event-adapter.md` |
| Temporal 集成方案 | Markdown + 原型代码 | `docs/research/data/rt-04-temporal.md` |
| kernel_adapter.py 原型 | Python | `hi_agent/runtime_adapter/kernel_adapter.py`（更新） |

## 5. 对架构的反馈（实验完成后填写）

### 验证的假设
- [ ] hi-agent RuntimeAdapter 的所有方法可映射到 agent-kernel API
- [ ] 两套状态机可双向映射（可能需要 adapter 层）
- [ ] EventEnvelope 和 RuntimeEvent 的差异可通过适配层解决
- [ ] Temporal Workflow 可承载 TRACE 的 Run/Stage/Branch 概念

### 推翻的假设（如有）
（实验后填写——如果某个 API gap 需要 agent-kernel 侧修改，在此记录）

### 需要修改架构的地方（如有）
（实验后填写）
