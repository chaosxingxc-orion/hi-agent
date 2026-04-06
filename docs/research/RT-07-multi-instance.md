# RT-07: 多实例协调与网络分区真实行为

> 优先级：P2
> 预计时间：5-7 天
> 前置依赖：RT-04（agent-kernel 真实对接）
> 负责人：待分配
> 状态：TODO

## 1. 核心问题

§13.6 设计了心跳 + 孤儿接管 + 网络分区三级降级。但 agent-kernel 基于 Temporal，而 Temporal 本身有原生的 Worker 故障处理能力。TRACE 的设计有多少与 Temporal 重叠？哪些需要自己实现？

**必须回答的问题：**
- Q1: Temporal 的原生故障恢复（Workflow replay, Activity retry, Worker heartbeat）覆盖了 §13.6 的多少？
- Q2: 从实例崩溃到孤儿 Run 被接管的端到端延迟是多少？
- Q3: 网络分区时 hi-agent 的 connected → degraded → partitioned 状态转移是否如预期发生？
- Q4: 防脑裂保证（§13.6：分区模式下不执行 irreversible_write）在真实环境中是否可靠？

## 2. 背景

### agent-kernel 的 Temporal 集成（基于源码）
```
agent_kernel/substrate/temporal/:
  - Temporal Workflow 抽象层
  - Worker 注册和心跳

agent_kernel/runtime/:
  - drain_coordinator.py: 停机协调（骨架）
  - heartbeat.py: 心跳管理
  - health.py: KernelHealthProbe
```

### TRACE §13.6 的设计
```
心跳：interval=30s
孤儿检测：3 次未心跳 → suspect，5 次 → dead + orphan
接管：adopt_orphan_run() 使用 CAS on run.owner_instance_id
网络分区：connected → degraded(60s) → partitioned(150s)
防脑裂：partitioned 模式下禁止 irreversible_write/irreversible_submit
```

## 3. 研究内容

### 3.1: Temporal 能力映射

**目标：** 确定 Temporal 已经"免费"提供了什么，TRACE 还需要自己实现什么。

```
对照表（需要通过阅读 Temporal 文档 + agent-kernel 代码填写）：

| TRACE 需求 | Temporal 原生能力 | 需要自己实现？ |
|---|---|---|
| Worker 心跳（30s 间隔） | Temporal Worker 有 heartbeat | 可能不需要——直接复用？ |
| 孤儿 Run 检测 | Temporal 的 Workflow Task Timeout | 可能重叠 |
| 孤儿 Run 接管（CAS） | Temporal 自动重新分配 Workflow | 可能不需要 CAS——Temporal 自己做？ |
| 网络分区检测 | ? | 可能需要自己实现 |
| 分区模式下禁止 irreversible | Temporal 不知道 effect_class | 一定需要自己实现 |
| graceful shutdown + drain | Temporal Worker 有 graceful stop | 可能部分重叠 |
| verify_run_ownership | Temporal Workflow 有 Worker identity | 可能可以复用 |
```

**研究方式：**
1. 阅读 Temporal 官方文档的 Failure Handling / Worker Session / Heartbeat 章节
2. 阅读 agent-kernel/substrate/temporal/ 的源码
3. 填写映射表 + 标记"确定可复用"/"确定需要自建"/"需要验证"

### 3.2: 孤儿接管端到端延迟测试

**目标：** 测量从实例崩溃到 Run 被另一个实例恢复执行的真实延迟。

**方法：**
```
环境：
  - 2 个 hi-agent 实例（A, B）+ 1 个 agent-kernel + 1 个 Temporal server
  - 实例 A 持有一个 active Run（在 S3 Build 阶段）

测试流程：
  T=0:    实例 A 正常运行 Run
  T=T1:   kill -9 实例 A（模拟崩溃）
  T=T2:   agent-kernel 检测到 A 的心跳丢失（T2 - T1 = 检测延迟）
  T=T3:   agent-kernel 标记 Run 为 orphan（T3 - T2 = 标记延迟）
  T=T4:   实例 B adopt_orphan_run() 成功（T4 - T3 = 接管延迟）
  T=T5:   实例 B 从 TraceRuntimeView 重建 Run 状态并继续执行（T5 - T4 = 恢复延迟）

测量：
  - total_downtime = T5 - T1
  - 对 quick_task（30min budget）：total_downtime < 5min 可接受
  - 对 deep_analysis（24h budget）：total_downtime < 30min 可接受

重复 5 次，取 P50/P99
```

### 3.3: 网络分区混沌测试

**目标：** 验证 §13.6 的三级降级行为。

**方法：**
```
环境：同 3.2

工具：Toxiproxy（在 hi-agent → agent-kernel 之间注入网络故障）

场景 1: 短暂断连（< 60s → 应保持 connected）
  操作：Toxiproxy 断开连接 30s 后恢复
  预期：hi-agent 日志显示重连，Run 继续执行，无降级

场景 2: 降级模式（60-150s → connected → degraded）
  操作：Toxiproxy 断开连接 90s
  预期：
    - 60s 后 hi-agent 进入 degraded 模式
    - /health/ready → 503
    - read_only Action 继续执行
    - external_write Action 暂停
    - 90s 时恢复连接 → 退出 degraded，暂停的 Action 重新分发

场景 3: 分区模式（> 150s → degraded → partitioned）
  操作：Toxiproxy 断开连接 180s
  预期：
    - 150s 后进入 partitioned 模式
    - 所有 Action 暂停
    - irreversible_submit 被阻止（防脑裂）
    - 180s 时恢复连接 → verify_run_ownership → 恢复或放弃

场景 4: 脑裂防护验证
  操作：
    - 实例 A 进入 partitioned 模式
    - 同时 agent-kernel 将 Run 分配给实例 B
    - 恢复 A 的网络
  预期：
    - A 执行 verify_run_ownership → 发现 owner 已变为 B → A 放弃本地状态
    - B 的 Run 不受影响
    - 无重复 Action 执行
```

### 3.4: graceful shutdown 验证

**目标：** 验证 §13.5 的 5 步停机协议在真实环境中的行为。

```
场景：实例 A 正在执行一个 deep_analysis Run 的 LLM 调用（预计 30s）

操作：发送 SIGTERM 到实例 A

预期：
  1. A 停止接受新 Run（/health/ready → 503）
  2. A 向 agent-kernel 注销心跳
  3. A 等待当前 LLM 调用完成（自适应 timeout = max(30s, expected_p99 × 2)）
  4. A 将 Run 状态 flush 到 agent-kernel
  5. A 退出

验证：
  - LLM 调用是否在 timeout 内完成？
  - Run 的 event log 是否完整（无丢失事件）？
  - 另一个实例是否可以从 flush 点继续？
```

## 4. 产出物清单

| 产出 | 格式 | 位置 |
|------|------|------|
| Temporal 能力映射表 | Markdown 表格 | `docs/research/data/rt-07-temporal-mapping.md` |
| 孤儿接管延迟数据 | CSV + 统计 | `docs/research/data/rt-07-orphan-latency.csv` |
| 网络分区混沌测试报告 | Markdown | `docs/research/data/rt-07-chaos-partition.md` |
| Toxiproxy 测试脚本 | Shell + Python | `tests/chaos/partition_test.sh` |
| graceful shutdown 验证报告 | Markdown | `docs/research/data/rt-07-shutdown.md` |

## 5. 对架构的反馈（实验完成后填写）

### 验证的假设
- [ ] Temporal 覆盖了 §13.6 的大部分故障恢复（减少自建工作量）
- [ ] 孤儿接管 total_downtime < 5min（quick_task 可接受）
- [ ] 网络分区三级降级行为如预期
- [ ] 防脑裂保证在真实环境中可靠（无重复 Action）

### 推翻的假设（如有）
（实验后填写——特别关注 Temporal 的原生能力是否足够，是否需要额外的自建层）

### 需要修改架构的地方（如有）
（实验后填写——如果 Temporal 的行为与 §13.6 设计冲突，需要调整架构）
