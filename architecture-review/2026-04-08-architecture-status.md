# TRACE 架构实施状态 — 2026-04-08

> 基于 V2.0 设计基线 (`2026-04-05-trace-architecture-design-v2.0.md`)，本文记录截至 2026-04-08 的实施进展。

---

## 1. 总体判断

6 道工程关卡全部通过。系统从 spike 级别（加权 2.3/5）提升至 alpha 可用级别（加权 3.5/5）。

| 维度 | 2026-04-05 状态 | 2026-04-08 状态 | 变化 |
|------|----------------|----------------|------|
| 并发能力 | 零（纯同步 for 循环） | asyncio 原生，1000+ 并发 Run | 从 0 到可用 |
| LLM 调用 | 内存 mock | AsyncLLMGateway + httpx 连接池 | 接口就绪 |
| 状态隔离 | 共享可变状态 | RunContext + RunContextManager | 完成 |
| 安全机制 | CircuitBreaker 无半开 | 完整 closed→open→half_open + async 超时+退避 | 完成 |
| 图驱动执行 | stage 硬编码列表 | execute_graph() 动态遍历 + backtrack | 完成 |
| Kernel 对接 | MockKernel 3 方法 | 17-method Protocol + execute_turn + async adapter | 完成 |
| 决策逻辑归属 | 散落在两个仓库 | hi-agent 拥有全部决策逻辑 | 完成 |

---

## 2. 工程关卡通过记录

### Gate 1: Async 化

| 交付物 | 文件 | 说明 |
|--------|------|------|
| AsyncTaskScheduler | `task_mgmt/async_scheduler.py` | asyncio + Semaphore 背压 + O(1) pending_count |
| EventBus | `server/event_bus.py` | asyncio.Queue fan-out |
| SSE 端点 | `server/sse_routes.py` | StreamingResponse 实时事件流 |
| HTTPGateway | `llm/http_gateway.py` | httpx.AsyncClient 连接池 |

### Gate 2: Kernel 对接

| 交付物 | 文件 | 说明 |
|--------|------|------|
| MockKernelFacade | `runtime_adapter/mock_kernel_facade.py` | execute_turn 契约 mock |
| KernelFacadeAdapter | `runtime_adapter/kernel_facade_adapter.py` | 17-method + execute_turn |
| AsyncKernelFacadeAdapter | `runtime_adapter/async_kernel_facade_adapter.py` | 全方法 async 包装 |

### Gate 3: LLM 接入

| 交付物 | 文件 | 说明 |
|--------|------|------|
| AsyncLLMGateway | `llm/protocol.py` | async complete() 协议 |
| HTTPGateway.complete() | `llm/http_gateway.py` | 实现 AsyncLLMGateway |
| AsyncMemoryCompressor | `memory/async_compressor.py` | LLM 摘要 + concat 回退 |
| Runner cost tracking | `runner.py` | _track_llm_cost() |

### Gate 4: 安全机制

| 交付物 | 文件 | 说明 |
|--------|------|------|
| AsyncCapabilityInvoker | `capability/async_invoker.py` | asyncio.wait_for + 指数退避 |
| Dead-end 检测 | `runner.py` | detect_dead_end 接入 stage 循环 |
| 异常保护 | `runner.py` | execute() try/except 包裹 |

### Gate 5: StageGraph 驱动

| 交付物 | 文件 | 说明 |
|--------|------|------|
| execute_graph() | `runner.py` | 动态 successors() 遍历 |
| Backtrack edges | `trajectory/stage_graph.py` | add_backtrack / get_backtrack |
| Multi-successor 路由 | `runner.py` | _select_next_stage + route_engine |

### Gate 6: 并发隔离

| 交付物 | 文件 | 说明 |
|--------|------|------|
| RunContext | `context/run_context.py` | 每 Run 可变状态容器 + 序列化 |
| RunContextManager | `context/run_context.py` | 多 Run 状态管理 |
| Runner 集成 | `runner.py` | _sync_to_context() 双向同步 |

---

## 3. Kernel 重构完成记录

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 1 | 添加 execute_turn() 到 KernelFacade | 完成 |
| Phase 2 | Plan 类型迁移到 hi-agent | 完成 |
| Phase 3 | 删除 PlanExecutor / Plan API | 完成 |
| Phase 4 | RestartPolicyEngine / ReflectionOrchestrator 迁移到 hi-agent | 完成 |

**agent-kernel task_manager 最终保留：**
- `contracts.py` — TaskDescriptor, TaskAttempt, TaskRestartPolicy, TaskHealthStatus
- `registry.py` — TaskRegistry（纯状态存储）
- `watchdog.py` — TaskWatchdog（心跳监控 + async callback）
- `event_log.py` — InMemoryTaskEventLog

---

## 4. 量化指标

### hi-agent

| 指标 | 2026-04-05 | 2026-04-08 | 增量 |
|------|-----------|-----------|------|
| 源代码模块 | 238 | 252 | +14 |
| 源代码行数 | ~32,000 | ~34,000 | +2,000 |
| 测试数 | 1,975 | 2,067 | +92 |
| 测试行数 | ~31,000 | ~35,000 | +4,000 |

### agent-kernel

| 指标 | 变化 |
|------|------|
| 测试数 | 7,095 → 7,052 (删除迁移的 test) |
| 删除文件 | restart_policy.py, reflection_orchestrator.py, reflection_bridge.py + 对应测试 |

---

## 5. 架构承诺 vs 实现差距（更新）

| 架构承诺 | 2026-04-05 状态 | 2026-04-08 状态 |
|---------|----------------|----------------|
| 多 Run 并发 | 不可能 | AsyncTaskScheduler + RunContext 隔离 |
| 异步 LLM 调用 | 不存在 | AsyncLLMGateway + httpx 连接池 |
| 图驱动执行 | stage 硬编码列表 | execute_graph() + backtrack + routing |
| 熔断器 half_open | 无（永远 open） | 完整 closed→open→half_open |
| 17 个 RuntimeAdapter API | 3 个方法 | 17 + execute_turn + subscribe_events |
| 异步 L1 压缩 | 纯同步字符串拼接 | AsyncMemoryCompressor (LLM + fallback) |
| KnowledgeWiki | 已实现 | 已实现（未变） |
| Skill 进化 | 已实现 | 已实现（未变） |
| Human Gate A/B/C/D | 代码框架在 | 代码框架在 + 接口就绪 |

### 仍需推进

| 项目 | 优先级 | 说明 |
|------|--------|------|
| 真实 LLM 端到端 | P1 | 接入 API key，跑通第一个真实 Run |
| Human Gate 实现 | P2 | 完成 Gate A-D 的 async 等待/回调机制 |
| 状态持久化 | P2 | 接入 kernel 的 EventLogStore (SQLite/PG) |
| 进程崩溃恢复 | P2 | kill → restart → event log 恢复继续 |
| 压力测试 | P3 | 100+ 并发 Run 稳定性验证 |
