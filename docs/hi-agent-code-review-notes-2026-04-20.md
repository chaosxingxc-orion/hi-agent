# hi-agent 代码审计与优化建议（复审版）

时间：2026-04-20
仓库：`https://github.com/chaosxingxc-orion/hi-agent`
本地路径：`/home/yansuqing/.openclaw/workspace/hi-agent`
审计基线：基于 2026-04-17 审计结果，对最新 `origin/main` 重新复查
当前 HEAD：`1be4e95083a5bd13988da636c4fd5a0f6055e41a`

---

## 1. 本轮总体结论

这次复审的结论和上次相比，有一个明显变化：

**仓库已经开始系统性修正上次提到的一批工程问题，但修复呈现出“底层能力已补齐，主链路还没完全切过去”的状态。**

也就是说：

1. 一些关键基础设施已经补上了，例如：
   - 进程级 async bridge executor
   - ContextManager 的 section cache
   - RetrievalEngine 的索引缓存与 fingerprint
   - ShortTermMemoryStore 的 manifest 索引
   - SqliteEvidenceStore 的批量写入接口
   - server 路由拆分的第一步
2. 但主执行链里仍然保留了几处旧写法，导致实际收益还没有完全释放出来。
3. 所以当前阶段最值得做的，不是再加新特性，而是**完成“从修复能力存在”到“主路径真正使用修复能力”的最后一公里收敛**。

---

## 2. 已明显改善的项

### 2.1 sync/async 桥接基础设施已经补齐

新增了 `hi_agent/runtime/async_bridge.py`，提供进程级共享 `ThreadPoolExecutor`，避免重复创建线程池。

参考：
- `hi_agent/runtime/async_bridge.py`

这说明仓库已经意识到“热路径不能每次临时 new 一个线程池”这个问题，方向是对的。

### 2.2 ContextManager 已开始做分层缓存

`ContextManager` 已经对 `system / tools / skills` 做了 fingerprint cache，对 `memory / history / reflection` 做了 dirty flag 控制。

参考：
- `hi_agent/context/manager.py:516-610`

这比之前“每次全量重组装”明显进了一步，尤其对长流程、多轮调用会更稳。

### 2.3 RetrievalEngine 已补上索引治理能力

现在已经不是粗糙的 pickle 落盘了，而是：
- JSON cache
- schema version
- fingerprint 校验
- `warm_index_async()`
- `mark_index_dirty()`
- `iter_nodes()` 公共接口替代部分私有字段穿透

参考：
- `hi_agent/knowledge/retrieval_engine.py:267-280`
- `hi_agent/memory/long_term.py:394-401`

### 2.4 Short-term memory 的 O(n) 扫描问题已有治理

`ShortTermMemoryStore` 已引入 `_manifest.json` 维护最近会话索引，`list_recent()` 不再总是全目录扫描。

参考：
- `hi_agent/memory/short_term.py:112-170`

### 2.5 EvidenceStore 已补充批量写接口

`SqliteEvidenceStore` 现在已经有：
- `store_many()`
- `transaction()`

参考：
- `hi_agent/harness/evidence_store.py:160-195`

这说明上次提的“每条证据单独 commit”问题，已经至少在能力层被修复了。

### 2.6 server 路由拆分已经启动

`server/app.py` 已经把 runs、sessions、tools/mcp、events、ops、team 的部分处理器提取到独立模块。

参考：
- `hi_agent/server/app.py:72-97`
- `hi_agent/server/app.py:1420-1505`
- `hi_agent/server/routes_runs.py`

这比之前“所有 handler 全塞 app.py”已经前进了一步。

---

## 3. 仍然存在的高优先级问题

### 3.1 ActionDispatcher 仍然保留每次调用临时创建线程池的旧桥接写法

这是我现在最在意的问题之一。

`hi_agent/execution/action_dispatcher.py` 里，hook 包装逻辑仍然在运行中的 event loop 场景下这样做：

- `asyncio.get_event_loop()`
- 判断 `loop.is_running()`
- `with ThreadPoolExecutor(max_workers=1) as _pool:`
- `_pool.submit(asyncio.run, ...)`

参考：
- `hi_agent/execution/action_dispatcher.py:74-90`

这说明虽然仓库已经提供了 `AsyncBridgeService`，**但主热路径还没有统一迁移过去**。

影响：
1. 高频 action 执行仍然可能频繁付出线程池创建/销毁成本
2. sync/async 边界策略仍然不统一
3. 性能改善会被“老桥接残留”抵消

建议：
- 直接统一切到 `AsyncBridgeService`
- 或者更进一步，把 hook 链改成 async-first

这个问题的优先级，我认为仍然是 **P0**。

### 3.2 反射恢复链仍然保留 `asyncio.run()` / loop 分叉逻辑

`hi_agent/execution/recovery_coordinator.py` 里仍然存在：
- `asyncio.get_event_loop()`
- loop running 时 `create_task(...)`
- 否则 `asyncio.run(...)`

参考：
- `hi_agent/execution/recovery_coordinator.py:323-375`

这比 action dispatcher 稍微轻一点，因为它不一定是最高频路径，但它说明：

**全仓还没有形成统一的 async bridge 规范。**

风险：
- 不同模块各自处理 sync/async 边界
- 调试时行为分叉更多
- 后续很难做统一性能治理

建议：
- 抽一个统一 helper，所有 sync↔async 过渡都走同一套基础设施
- 把 `get_event_loop()/asyncio.run()` 组合收敛掉

### 3.3 LLM 网关的“默认异步主路径”目标，代码上还没有真正落地

这是这次复审里我认为最值得点名的问题。

`TraceConfig.compat_sync_llm` 默认值已经是 `False`，注释也明确写了“生产默认走 async HTTPGateway”。

参考：
- `hi_agent/config/trace_config.py:115-117`

但 `CognitionBuilder.build_llm_gateway()` 在 openai/provider 环境变量分支里，**实际仍然实例化的是 `HttpLLMGateway`**：

参考：
- `hi_agent/config/cognition_builder.py:281-290`

同时 `HttpLLMGateway` 本身依然保留：
- failover chain 的 sync bridge
- `time.sleep(delay)` 的阻塞式 retry

参考：
- `hi_agent/llm/http_gateway.py:146-155`
- `hi_agent/llm/http_gateway.py:297-309`

这意味着：

1. 配置注释、架构文档、实际代码之间存在偏差
2. “兼容层”可能仍在实际主路径上承担工作
3. 一旦服务端线程/worker 线程里大量走同步 gateway，吞吐和尾延迟都会受影响

我认为这是当前最实质性的 **P0/P1 交界问题**。

建议：
- 明确修正 `build_llm_gateway()`，让 `compat_sync_llm=False` 时真的走 `HTTPGateway`
- `HttpLLMGateway` 只在显式兼容模式下启用
- 把这条路径加测试，避免文档和实现再次漂移

### 3.4 RetrievalEngine 的“能力已加，但尚未接入生命周期”

`RetrievalEngine` 已经有：
- `warm_index_async()`
- `mark_index_dirty()`

但是我在仓库里复查时，没有看到它们被实际调用，grep 结果只有定义和架构文档。

参考：
- `hi_agent/knowledge/retrieval_engine.py:267-280`
- 全仓 grep `warm_index_async|mark_index_dirty`

这意味着当前状态更像是：

- 功能接口已经补上
- 但 server 启动阶段没有真正预热
- 数据写入/知识变更时也没有形成 dirty 通知链

结果就是：
1. 首次查询延迟仍可能打到线上首请求
2. 索引新鲜度治理还没有真正闭环

建议：
- 在 server 启动生命周期里显式调用 `warm_index_async()`
- 在 knowledge ingest / sync / memory consolidate 成功后显式 `mark_index_dirty()`

这是一个典型的“修了 70%，剩下 30% 最关键”的问题。

---

## 4. 中优先级问题

### 4.1 `server/app.py` 虽然开始拆了，但主文件仍然过大

目前 `server/app.py` 仍然有大约 2250 行。

它现在的问题不再是“完全没拆”，而是“拆了一部分，但核心聚合层还是过重”。

尤其从代码结构上看：
- 入口路由已经引入了部分外部 handler
- 但 app.py 里仍然保留大量本地 handler
- 文件尾部还保留了一批 legacy / test-facing `_handle_*` 方法

参考：
- `hi_agent/server/app.py:72-97`
- `hi_agent/server/app.py:1420-1505`
- `hi_agent/server/app.py:1987-2197`

这意味着路由层虽然迈出第一步，但可维护性收益还没有完全兑现。

建议：
- 继续拆 memory / knowledge / skills / replay / plugins / artifacts / management
- legacy/test helper 另移到 test adapter 或 compatibility shim

### 4.2 async handler 中仍有一批 `asyncio.get_event_loop()` 老写法

例如：
- `hi_agent/server/routes_runs.py:300`
- `hi_agent/server/app.py:1120, 1139, 1164`

这不一定立刻出 bug，但在现代 asyncio 写法里，协程上下文更建议统一使用 `get_running_loop()`。

问题本质不在“能不能跑”，而在：
- 代码风格不统一
- loop 生命周期语义不够清楚
- 后续维护者更难判断哪些代码是在协程内，哪些在同步路径

建议顺手统一。

### 4.3 mid-term memory fallback 分支有一个明确的返回值 bug

`hi_agent/memory/mid_term.py` 的 `list_recent()` 在 manifest 不存在时会走 fallback 全目录扫描。

但最后排序完 `all_summaries` 之后，返回的是：

- `return summaries[:days]`

而不是：

- `return all_summaries[:days]`

参考：
- `hi_agent/memory/mid_term.py:197-228`

这里的 `summaries` 只在 manifest 分支里定义，所以 fallback 路径下会直接触发错误。

这不是“代码味道”问题，而是一个确定性的实现 bug，优先级至少应当是 **P1**，因为它会直接影响 mid-term memory 的读取稳定性。

### 4.4 仍然有部分内部私有字段穿透访问

长时记忆图的公共接口已经补上 `iter_nodes()/stats()`，这是进步。

但仓库里仍然能看到一些直接使用 `_graph._nodes`、`graph._nodes` 的地方，主要集中在 graph/trajectory 体系内部模块之间。

这类问题的风险不像主链路性能那么急，但它会持续抬高维护成本。

---

## 5. 本轮优先级建议

### P0，建议本周优先处理

1. **统一清理主热路径里的旧 async bridge 写法**
   - `execution/action_dispatcher.py`
   - `execution/recovery_coordinator.py`
2. **修正 `build_llm_gateway()` 的默认实现与配置语义不一致问题**
   - 让 `compat_sync_llm=False` 真正切到 async `HTTPGateway`
3. **把 RetrievalEngine 的预热与 dirty 通知真正接入生命周期**

### P1，第二阶段处理

1. 继续拆 `server/app.py`
2. 统一 async handler 里的 loop API 写法
3. 梳理 remaining private-field access

### P2，可持续治理项

1. 给 ContextManager / Retrieval / Gateway 增加 profiling 指标
2. 为“fallback path”和“兼容路径”增加结构化 metrics
3. 给 LLM 网关主路径选择补契约测试，防止文档与实现再次偏离

---

## 6. 一句话总结

**这次刷新后的 hi-agent，比上次明显更工程化了。真正的问题已经从“有没有意识到这些坑”变成了“修复能力已经有了，但主路径还没完全切过去”。**

如果只让我挑 3 个最值得现在马上动的点，我会选：

1. `action_dispatcher` 还在每次创建 `ThreadPoolExecutor(max_workers=1)`
2. `build_llm_gateway()` 名义上 async-first，实际上 openai/env 路径仍走 `HttpLLMGateway`
3. `RetrievalEngine` 的预热和 dirty 标记只有能力，没有真正接到生命周期里

这三个点一旦收掉，性能、可维护性和系统行为一致性都会明显上一个台阶。
