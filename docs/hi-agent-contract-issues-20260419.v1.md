这次我把链路基本查实了，结论比之前清楚很多：

现在 `hi-agent` 不是“完全跑不通”，而是“真实执行已经开始跑了，但 dev 模式下的 LLM 失败回退太慢，看起来像卡死”。

我确认到的事实：

- `hi-agent` 新代码替换是生效的，上午那批 `hi-agent -> agent-kernel` 契约错位已经过去了。
- 当前服务实际跑在 `/root/hi-platform/venv/bin/python3 -m hi_agent serve --host 127.0.0.1 --port 8080`。
- 当前 `/ready` 返回的是 `runtime_mode=dev-smoke`、`execution_mode=local`，说明它现在走的是本地 in-process kernel，不是老的 HTTP `agent-kernel` 进程。
- 所以“作者没升级 `agent-kernel`”这件事，眼下不是主阻塞。

真实端到端结果：

- `POST /runs` 能成功创建 run。
- 这个 run 不是空转，我查了 checkpoint，已经真实执行到了 TRACE 流程里。
- 具体这个 run：
  - `S1_understand` 在 `11:49:05 UTC` 开始，`11:57:13 UTC` 成功
  - `S2_gather` 在 `11:57:13 UTC` 开始，`12:05:21 UTC` 成功
  - `S3_build` 在 `12:05:21 UTC` 开始，`12:13:30 UTC` 成功
  - `S4_synthesize` 在 `12:13:30 UTC` 已进入 active
- 这些都写在 `/root/hi-platform/.checkpoint/checkpoint_77b9fae7-3b36-4c15-8488-a234d350e31f-f20d95ed.json` 里。

也就是说：
- 它不是死锁
- 不是 run 根本没启动
- 是每个 stage 都在非常慢地往前挪

我认为当前最核心的问题有 2 个。

1. `hi_agent/llm/http_gateway.py` 的失败回退太慢  
   `HttpLLMGateway._post()` 这里每次 LLM 请求失败都会走长超时和多次重试，日志里又明确看到：
   - `analyze_goal`
   - `search_evidence`
   - `build_draft`
   - `synthesize`
   - `evaluate_acceptance`
   都在报 `LLMProviderError: [Errno 101] Network is unreachable`，然后才 fallback 到 heuristic。  
   从 checkpoint 时间差看，单个 stage 大约要耗 `8 分钟`，这和“长 timeout + 多次 retry”完全吻合。  
   所以现在看起来像“run 卡住”，本质上是“每一步都先慢失败，再回退”。

2. `/runs/{id}` 对外状态基本不可观测  
   API 现在一直只返回：
   - `state: running`
   - `updated_at` 还是刚创建时那一瞬间  
   但真实执行其实已经推进到 `S4`。  
   这说明 `hi_agent/server/run_manager.py` 里的 `ManagedRun` 只在“启动/终态”更新，高频阶段进度都只进 checkpoint，不反映到 `/runs/{id}`。  
   所以外部调用方会误以为它完全没动。

另外两个重要排除项：

- 不是 `HI_AGENT_OPENAI_BASE_URL` 没生效  
  `TraceConfig.from_env()` 会正确读 `HI_AGENT_OPENAI_BASE_URL`，这条配置链本身没问题。
- 不是 `HttpLLMGateway` 代码本身完全坏了  
  我用线上同一套 venv 单独跑 `HttpLLMGateway.complete()`，直接打 DeepSeek 能返回 `OK`。  
  所以更像是“服务进程里的执行场景”在报 `Errno 101`，而不是这段网关代码在任何场景都不通。

系统性评价：

- 好消息：新 `hi-agent` 比旧版健康得多，主契约已经接上了，run 也确实能推进。
- 坏消息：当前 `dev-smoke` 仍然不适合演示“秒级响应”，因为 heuristic fallback 前面的 LLM 超时太长。
- 更准确地说：现在是“能跑，但体验上像挂了”。

我建议的修复优先级：

1. dev 模式下直接禁用真实 LLM 尝试，只走 heuristic  
   这是最值当的。既然 `/ready` 已经标明 `dev-smoke`，那就别再先等一轮外部 LLM 失败。

2. 如果不想完全禁用，至少把 dev 的 timeout/retry 大幅缩短  
   现在这套参数对 demo 很不友好。

3. `/runs/{id}` 增加阶段级进度  
   至少把当前 stage、最近 checkpoint 时间、最近事件摘要暴露出来，不然外部永远只能看到一个假 `running`。

4. `/events` 这条也要补可观察性  
   当前 checkpoint 明明有事件，但外部订阅几乎感知不到有效进展。

如果你愿意，我下一步可以直接继续帮你做两种之一：

- 给你整理成一份可直接发给作者/Claude Code 的问题单
- 继续盯这个 run，确认它最终会不会从 `S4/S5` 正常收敛到 `completed`
