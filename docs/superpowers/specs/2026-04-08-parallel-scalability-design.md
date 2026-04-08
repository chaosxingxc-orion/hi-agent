# 大规模并行调用架构设计

**日期：** 2026-04-08  
**范围：** hi-agent + agent-kernel 两库协同重构  
**目标：** 支持 1000+ 并发 Run，单机 200-400，多进程横向扩展至 1000+

---

## 背景与第一性原理

当前实现的核心瓶颈：
- `TaskScheduler` 使用 `ThreadPoolExecutor(max_workers=4)`，硬限 4 个并发
- 全局 `threading.Lock` 竞争，所有状态变更串行
- `_check_unblock` O(n²) 扫描，随任务数量劣化
- `RunSession` 本地 JSONL 文件，无法跨进程共享
- `ModelRegistry` 无线程安全保障
- LLM 调用阻塞线程（网络 I/O 应用 asyncio）

框架调研结论（LangGraph / claude-code / agent-kernel）：
- **LangGraph**：asyncio `AsyncBackgroundExecutor` + `asyncio.Semaphore` 背压 + 可插拔 `CheckpointSaver`
- **claude-code**：进程隔离 + `AbortController` 层级 + 磁盘 IPC
- **agent-kernel**（自有项目）：事件溯源 `EventLog` + `TurnEngine` 六权威 + `LocalFSMAdaptor` asyncio 底座

**核心结论：** agent-kernel 是 hi-agent 的自有项目，直接合并，不引入外部 MQ。

---

## 架构边界（接口契约）

### agent-kernel 职责：纯 kernel 原语

agent-kernel **不知道** Plan 类型、Stage、TrajectoryGraph——这些是业务逻辑，属于 hi-agent。

agent-kernel 只暴露：

```python
class KernelFacade:
    # 生命周期
    async def start_run(run_id: str, session_id: str, metadata: dict) -> None
    async def signal_run(run_id: str, signal: str, payload: dict) -> None
    async def terminate_run(run_id: str, reason: str) -> None

    # 执行原语
    async def execute_turn(
        run_id: str,
        action: Action,
        handler: AsyncActionHandler,
        *,
        idempotency_key: str,
    ) -> TurnResult

    # 查询（只读）
    async def get_run_projection(run_id: str) -> RunProjection

    # 事件订阅（SSE 层接这里）
    async def subscribe_events(run_id: str) -> AsyncIterator[RuntimeEvent]
```

### hi-agent 职责：认知逻辑 + 调度

- `TrajectoryGraph`：图结构、DAG、并行、投机执行
- `AsyncTaskScheduler`：超步调度、动态图生长、预算守卫
- `GraphFactory`：图模板工厂（按任务复杂度选初始图）
- TRACE Middleware 链：每个节点的认知执行逻辑
- SSE endpoint：对外推流

---

## Section 1：接口契约

### execute_turn 语义

一次原子 Turn，按顺序执行：

```
Admission  → 预算/安全准入检查
Dedupe     → 幂等键查重（已执行过直接返回缓存结果）
Execute    → 调用 hi-agent 传入的 handler（TRACE middleware 链）
EventLog   → append-only 记录事实
Recovery   → 失败时触发补偿
```

### hi-agent 调用示例

```python
async def _execute_node(self, node: TrajectoryNode, run_id: str) -> NodeResult:
    result = await self.kernel.execute_turn(
        run_id=run_id,
        action=Action(action_type="trace_stage", payload={"node_id": node.node_id}),
        handler=self._make_handler(node),
        idempotency_key=f"{node.node_id}:{node.attempt_seq}",
    )
    return NodeResult.from_turn_result(result)
```

---

## Section 2：动态图调度层（hi-agent）

### 三层决策链

```
TaskContract
    ↓
RouteEngine（复杂度评估 → 选图模板 + 分配模型 tier）
    ↓
TrajectoryGraph（初始图，执行中动态生长）
    ↓
AsyncTaskScheduler（超步调度 + Semaphore 背压 + 预算守卫）
    ↓
kernel.execute_turn()
```

### GraphFactory：图模板工厂

```python
class GraphFactory:
    @staticmethod
    def build(contract: TaskContract, complexity: ComplexityScore) -> TrajectoryGraph:
        if complexity.score < 0.3:
            # 简单任务：跳过 S2/S4，全程 light 模型
            return GraphFactory._chain([S1, S3, S5], model_tier="light")

        elif complexity.score < 0.6:
            # 中等任务：标准 TRACE 五阶段，tier 自动路由
            return GraphFactory._chain([S1, S2, S3, S4, S5], model_tier="auto")

        elif complexity.needs_parallel_gather:
            # 复杂收集型：S2 多路并行，S3 汇聚
            return GraphFactory._dag(
                nodes=[S1, S2_a, S2_b, S2_c, S3, S4, S5],
                edges=[(S1, S2_a), (S1, S2_b), (S1, S2_c),
                       (S2_a, S3), (S2_b, S3), (S2_c, S3),
                       (S3, S4), (S4, S5)],
            )

        else:
            # 探索型：多条 S3 候选，取最优
            return GraphFactory._speculative(
                candidates=[S3_v1, S3_v2, S3_v3],
                model_tiers=["strong", "medium", "medium"],
            )
```

### AsyncTaskScheduler：核心改造

**改造对比：**

| 维度 | 现在 | 改后 |
|------|------|------|
| 并发模型 | `ThreadPoolExecutor(max_workers=4)` | asyncio 原生 |
| 并发上限 | 硬限 4 个 worker | `Semaphore(max_concurrency)` 软限 |
| Ready 检测 | 每次 O(n) 全扫描 | `pending_count` 计数器，O(依赖数) 更新 |
| 锁 | `threading.Lock` 全局竞争 | 无锁（单线程事件循环） |
| 图生长 | 不支持 | 执行中动态 `add_node()` |

**核心逻辑：**

```python
class AsyncTaskScheduler:
    def __init__(self, kernel: KernelFacade, max_concurrency: int = 64):
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._ready_queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending_count: dict[str, int] = {}
        self._waiters: dict[str, list[str]] = {}

    def add_node(self, node: TrajectoryNode, depends_on: list[str] = []):
        """执行中动态插入节点"""
        self._pending_count[node.node_id] = len(depends_on)
        for dep in depends_on:
            self._waiters.setdefault(dep, []).append(node.node_id)
        if not depends_on:
            self._ready_queue.put_nowait(node.node_id)

    async def run(self, graph: TrajectoryGraph, run_id: str) -> ScheduleResult:
        self._init_from_graph(graph)
        async with asyncio.TaskGroup() as tg:
            while not self._all_terminal():
                node_id = await self._ready_queue.get()
                tg.create_task(self._execute_with_backpressure(node_id, run_id))

    async def _execute_with_backpressure(self, node_id: str, run_id: str):
        node = self._graph.get_node(node_id)

        # 预算守卫
        if not self._budget.can_afford(node.estimated_cost):
            if node.is_optional:
                self._complete_node(node_id, skipped=True)
                return
            node = node.with_tier("light")  # 降级模型

        async with self._semaphore:
            result = await self._kernel.execute_turn(
                run_id=run_id,
                action=Action(node_id=node_id, stage=node.stage),
                handler=self._make_handler(node),
                idempotency_key=f"{node_id}:{node.attempt_seq}",
            )

        self._budget.consume(result.tokens_used)

        # 动态图扩展
        if result.requests_new_branch:
            self.add_node(result.new_branch_spec, depends_on=[node_id])
        if result.quality_insufficient and self._budget.can_afford_retry:
            self.add_node(node.make_retry(tier="strong"))

        self._complete_node(node_id)
```

### 预算与模型 Tier 联动

```
budget_remaining > 70%  → 按图模板分配的 tier
budget_remaining 40-70% → 自动降一级（strong → medium）
budget_remaining < 40%  → 强制 light，optional 节点跳过
budget_remaining < 10%  → 只执行必须节点，其余 cancel
```

---

## Section 3：agent-kernel 裁剪 + EventLog + SSE

### agent-kernel 裁剪清单

**移出到 hi-agent：**
- `plan_executor.py` → `hi_agent/task_mgmt/`（由 `AsyncTaskScheduler` 替代）
- `reasoning_loop.py` → `hi_agent/runner.py`
- `plan_type_registry.py` / `action_type_registry.py` → `hi_agent/contracts/`

**保留（纯 kernel 原语）：**
- `turn_engine.py`：Admission + Dedupe + Execute + EventLog
- `minimal_runtime.py`：InMemoryKernelRuntimeEventLog（测试）
- `persistence/`：SQLite（开发）/ Postgres（生产），同一接口
- `task_manager/`：stable task_id + 重试策略 + Watchdog
- `substrate/local/`：LocalFSMAdaptor（asyncio 底座）

### EventLog：唯一事实来源

```
execute_turn() 完成
  → EventLog.append(result)    # append-only，永不修改

崩溃恢复：
  → 重启时 replay EventLog → 重建 RunProjection
  → 已有 idempotency_key → Dedupe 返回缓存，不重复执行

后端切换（同一接口）：
  InMemoryKernelRuntimeEventLog   ← 单元测试
  SqliteKernelRuntimeEventLog     ← 本地开发
  PostgresKernelRuntimeEventLog   ← 生产（asyncpg 连接池）
```

### 数据流（全程内部直接调用）

```
AsyncTaskScheduler
  └─► kernel.execute_turn(node, handler)
          └─► TurnEngine
                ├─► Admission
                ├─► Dedupe
                ├─► handler()（TRACE middleware 链）
                └─► EventLog.append(result)
                        └─► asyncio.Queue
                                └─► SSE endpoint（对外推流）
```

### SSE（薄 HTTP 包装）

```python
@app.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str):
    queue = event_bus.subscribe(run_id)
    async def generate():
        while True:
            event = await queue.get()
            yield f"data: {event.to_json()}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

`event_bus` = `dict[run_id, list[asyncio.Queue]]`，`execute_turn` 完成后 `put` 一条记录。

---

## Section 4：部署架构 + 扩容模型

### 单进程基础形态

```
hi-agent 进程
  FastAPI（HTTP + SSE）
    ↓
  AsyncTaskScheduler（asyncio 事件循环）
    Semaphore(max_concurrency=512)
    ↓
  KernelFacade.execute_turn()
    TurnEngine + EventLog
    ↓
  httpx.AsyncClient（LLM 调用，连接池复用）

单进程承载：200-400 并发 Run
瓶颈：LLM Provider rate limit，非进程本身
```

### 多进程横向扩容（1000+ Run）

```
Load Balancer（按 run_id 哈希路由）
  ├── hi-agent 进程 A
  ├── hi-agent 进程 B
  └── hi-agent 进程 C
            ↓（共享）
       Postgres（EventLog + DedupeStore）

扩容：加进程，不改代码
Postgres append-only 写入无冲突
```

### 开发 → 生产切换（只改配置）

```python
if env == "development":
    event_log = SqliteKernelRuntimeEventLog("./dev.db")
    max_concurrency = 32
elif env == "production":
    event_log = PostgresKernelRuntimeEventLog(dsn=DATABASE_URL, pool_min=5, pool_max=20)
    max_concurrency = 512
```

### 两库并行推进边界

```
hi-agent 侧                          agent-kernel 侧
────────────────────────────         ──────────────────────────
AsyncTaskScheduler 改写              移出 PlanExecutor 等业务逻辑
  asyncio + Semaphore                裁剪 KernelFacade 到 4 接口
  pending_count O(1) 调度            execute_turn() 接口稳定
  动态图生长 add_node()              EventLog 多后端打通
GraphFactory 图模板工厂              LocalFSMAdaptor asyncio 验证
SSE endpoint + event_bus             DedupeStore SQLite/Postgres
httpx.AsyncClient LLM 连接池        TaskManager 重试/Watchdog

同步点：execute_turn() 接口契约（已在 Section 1 定义）
```

---

## 不涉及本次重构的部分

以下模块本次不动，保持现状：
- Memory 三层（short/mid/long-term）
- Knowledge wiki + 检索层
- Skill 生命周期管理
- Observability / tracing
- Auth / RBAC

这些模块在 asyncio 化后自然受益（不再被 ThreadPool 阻塞），但不需要主动改造。
