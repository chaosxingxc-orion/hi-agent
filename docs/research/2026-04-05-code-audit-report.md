# hi-agent 核心模块代码审计报告

> 日期：2026-04-05
> 审计范围：hi_agent/ 下 15 个核心源文件
> 审计目的：判断当前实现能否支撑"大规模并发使用"

## 总体判断

**当前代码整体是 spike/prototype，加权生产就绪度 2.3/5。**

- 并发能力：零（全部同步阻塞，无 asyncio/Lock）
- 真实 I/O：几乎为零（仅 events/store.py 有文件 I/O）
- 架构规范覆盖度：约 25-30%（RuntimeAdapter 3/17 API）

## 逐文件评分

| # | 文件 | 就绪度 | 性质 | 关键问题 |
|---|---|---|---|---|
| 1 | runner.py (485行) | 2/5 | 高质量 spike | 纯同步；stage 硬编码为列表未用 StageGraph；无 async |
| 2 | protocol.py (37行) | 2/5 | 接口定义 | 只有 3/17 个规范 API |
| 3 | mock_kernel.py (95行) | 3/5 | 测试桩 | 作为 mock 合格；无对应生产实现 |
| 4 | kernel_adapter.py (157行) | 3/5 | alpha | 有 ConsistencyJournal（亮点）；只覆盖 3 API |
| 5 | invoker.py (68行) | 3/5 | 接近 alpha | 无超时；circuit breaker 无半开 |
| 6 | circuit_breaker.py (44行) | **1/5** | spike | 无半开状态，open 后永久断路；无线程安全 |
| 7 | compressor.py (30行) | **1/5** | spike | 纯字符串拼接，无 LLM 调用 |
| 8 | l1_compressed.py (15行) | 3/5 | 数据类 | 过于简单，缺压缩元信息 |
| 9 | emitter.py (19行) | **1/5** | spike | 内存 list 无限增长；无持久化 |
| 10 | store.py (56行) | 2/5 | alpha | 文件 I/O 无并发保护；无 fsync |
| 11 | greedy.py (35行) | 2/5 | spike | 只有贪心，无探索 |
| 12 | stage_graph.py (57行) | 3/5 | 合格（未集成） | **runner.py 根本没用它** |
| 13 | compensator.py (202行) | **3.5/5** | 接近生产 | 最佳实践：per-action 异常分类 |
| 14 | health.py (150行) | 3/5 | alpha | 无真实探测，只被动汇总 |
| 15 | shutdown.py (154行) | **4/5** | 接近生产 | Thread + timeout 设计合理 |

## 核心断裂点（架构承诺 vs 代码实际）

| 架构承诺 | 代码实际 | 性质 |
|---|---|---|
| 4 种轨迹优化器 | 只有 greedy，且 runner 没用 StageGraph | 设计与实现断裂 |
| 分层压缩记忆 L0→L1→L2→L3 | compressor 是字符串拼接 | 名存实亡 |
| KnowledgeWiki | 零代码 | 完全缺失 |
| Inline + Batch 双轨进化 | 零代码 | 完全缺失 |
| 熔断器 closed→open→half_open | 无半开，open 后永久断路 | 功能残缺 |
| 17 个 RuntimeAdapter API | 只有 3 个 | 覆盖 18% |
| Human Gate A/B/C/D | 零代码 | 完全缺失 |
| 异步 L1 压缩 + fallback | 纯同步 + 无 LLM 调用 | 名存实亡 |

## 从 spike 到生产需要闯的 6 道关

| 关卡 | 工作量 | 达到的能力 |
|---|---|---|
| 1. async 化 | 5-7 天 | 代码结构支持并发 |
| 2. 接入真实 kernel | 7-10 天 | Run 持久化可恢复 |
| 3. 接入真实 LLM | 5-7 天 | 第一个真实 Run |
| 4. 补齐安全机制 | 5-7 天 | 失败可恢复 |
| 5. StageGraph 驱动 | 3-5 天 | CTS 生效 |
| 6. 并发 Run 隔离 | 3-5 天 | 可被并发使用 |
| **总计** | **6-7 周** | **架构口号落地** |
