# hi-agent 技术评委反馈裁决与系统整改方案

**日期**：2026-04-17  
**评审输入**：

- `docs/vulnerability-detection-analysis-2026-04-17-v2.md`
- `docs/hi-agent-code-review-notes-2026-04-17.md`

**评审目标**：严格判断哪些问题接纳、部分接纳、不接纳，并给出可执行整改方案。  
**评审原则**：外部反馈不盲收；安全候选按证据提高优先级；性能建议必须区分“确定热路径”和“需要 profiling 验证”。  

---

## 0. 执行结论

两份评委反馈总体有价值，但不能原样全收。

安全报告中的核心判断大多应接纳，尤其是：

1. 内置 `shell_exec` 默认注册且使用 `shell=True`，结合动态 capability 调用，构成高风险 RCE 候选。
2. `/tools/call` 与 `/mcp/tools/call` 支持按请求体中的 tool name 动态调用，缺少强制的 capability-level 治理入口。
3. `file_read`、`file_write`、`web_fetch` 是远程可调用高危能力，当前缺少 workspace sandbox、URLPolicy、risk metadata、审计和审批闭环。
4. `pickle.load` 用于检索索引缓存，虽然不等于已验证漏洞，但属于应整改的高危反序列化设计。

代码审查报告中的工程治理判断也基本成立，尤其是：

1. `runner.py` 和 `server/app.py` 过大，主链路职责集中。
2. sync/async 桥接中存在每次调用创建 `ThreadPoolExecutor(max_workers=1)` 的模式。
3. 同步 `HttpLLMGateway` 使用 `urllib` 与 `time.sleep` 重试，适合作为兼容层，不适合作为长期主链路。
4. `ContextManager`、`RetrievalEngine`、memory store、evidence store 都有明确的规模化优化空间。

但需要纠正几个过度结论：

1. `kernel_facade_client.py` 的 URL 访问不应和公开 `web_fetch` 等同处理。它是配置型后端地址，生产中可能合法指向内网 agent-kernel。不能简单套“只允许 https、禁止私网”的通用 SSRF 策略。
2. `scripts/load_test_runs.py` 是测试/压测脚本，不应按生产 SSRF 漏洞接纳。可加 warning 和 URL validation，但不进入 P0。
3. `runner.py` 拆分重要，但不应排在安全治理之前作为 P0。主链路瘦身是 P1/P2 工程治理，不是阻断安全整改的前置。
4. `ContextManager` 缓存和 memory store 结构化索引需要 profiling 与失效策略，不应直接做大改。
5. token 计数已有 pluggable counter，问题不是完全缺失 tokenizer，而是默认未配置真实 tokenizer、provider usage 偏差未观测。

本方案建议将整改分为四条主线：

1. **P0 安全治理底线**：危险工具默认关闭、统一 tool governance、路径/URL 安全策略、远程工具调用鉴权与审计。
2. **P1 安全与生产可靠性**：pickle 替换或签名、Capability metadata、RouteEngine 过滤 unavailable/dangerous capability、fallback/degraded 指标化。
3. **P1/P2 热路径治理**：sync/async 边界收敛、HttpLLMGateway 兼容层化、ContextManager 缓存、RetrievalEngine 索引治理。
4. **P2 可维护性收敛**：拆分 `runner.py` 与 `server/app.py`，清理私有字段穿透，memory/evidence store 扩展性优化。

---

## 1. 核验摘要

本次评审做了代码核验与窄测试验证。

### 1.1 代码事实

已核验事实：

- `hi_agent/capability/tools/builtin.py` 默认定义并注册 `file_read`、`file_write`、`web_fetch`、`shell_exec`。
- `shell_exec_handler` 使用 `subprocess.run(..., shell=True)`，且命令来自 payload。
- `SystemBuilder.build_capability_registry()` 默认调用 `register_builtin_tools(registry)`。
- `RunExecutor._invoke_capability()` 会以 `proposal.action_kind` 调用 `invoker.invoke(...)`。
- `/tools/call` handler 会直接读取请求中的 `name` 和 `arguments` 并调用 `invoker.invoke(name, arguments)`。
- `/mcp/tools/call` handler 会直接读取请求中的 tool name 并调用 `mcp_server.call_tool(...)`，而 `MCPServer.call_tool()` 最终调用 `self._invoker.invoke(name, arguments)`。
- `AuthMiddleware` 存在，但当 `HI_AGENT_API_KEY` 未设置时会禁用所有鉴权。
- `RateLimiter` 存在，但它不是 capability-level permission。
- `HarnessExecutor`、`PermissionGate`、`ToolPermissionRules.default_safe_rules()` 存在，但默认 `build_harness()` 没有传入 permission gate。
- `RetrievalEngine` 使用 `.index_cache.pkl` 保存/加载 TF-IDF index。
- `HttpLLMGateway.complete()` 在 failover chain 分支中存在 per-call `ThreadPoolExecutor(max_workers=1)`，`_post()` 使用 `time.sleep(delay)` 做同步重试。
- `ContextManager.prepare_context()` 每次都会组装 system/tools/skills/reflection/memory/knowledge/history。
- `ShortTermMemoryStore`、`MidTermMemoryStore`、`EpisodicMemoryStore` 存在目录扫描和 JSON 文件逐个读取模式。
- `SqliteEvidenceStore.store()` 每次写入后立即 `commit()`。

### 1.2 已运行验证

执行命令：

```powershell
python -m pytest tests\test_builtin_tools.py tests\test_auth.py tests\test_rate_limiter.py tests\test_mcp_server.py -q
```

结果：

```text
44 passed in 101.24s
```

这说明现有功能测试是通过的，但也强化了一个事实：当前测试把 `shell_exec`、`file_read`、`file_write`、`web_fetch` 作为默认可用工具在验证。因此安全整改会改变部分默认语义，需要做兼容迁移，而不能直接删功能。

---

## 2. 安全反馈逐条裁决

### SEC-01：动态工具调用可能串联 shell 执行能力

**裁决**：接纳。  
**优先级**：P0。  
**性质**：高风险漏洞候选，尚未复现 exploit，但具备真实可达链路。  

#### 证据

关键代码链路：

```text
route proposal.action_kind
  -> RunExecutor._invoke_capability()
  -> CapabilityInvoker.invoke(proposal.action_kind, payload)
  -> CapabilityRegistry
  -> shell_exec_handler()
  -> subprocess.run(command, shell=True)
```

同时，`shell_exec` 默认通过 `register_builtin_tools()` 注册进 capability registry。也就是说，模型输出、route proposal 或远程 tool call 一旦能影响 capability name 与 payload，就可能触达 shell sink。

#### 接纳范围

接纳以下判断：

- `shell_exec` 是高危 capability。
- 默认注册 `shell_exec` 不适合 production profile。
- `shell=True` 加自由文本命令不适合作为远程/模型可控工具的默认实现。
- 当前能力治理基座存在，但没有形成所有路径强制经过的唯一执行门。

不接纳以下隐含过度结论：

- 不把它定性为“已验证 RCE 漏洞”。当前报告没有完成 LLM validation 或 exploit 复现。
- 不直接删除 `shell_exec`，因为测试和开发工作流依赖它。应改为 profile/policy 控制。

#### 整改要求

1. `shell_exec` 默认在 `prod-real` 下禁用。
2. dev-smoke 可保留，但必须在 manifest/readiness 中标记 `risk_class=shell`、`enabled_by=dev_default`。
3. `shell_exec` 必须从自由文本命令迁移到安全执行模型：
   - 短期：denylist + allowlist 双层规则，禁止高危命令。
   - 中期：命令模板 + 参数白名单。
   - 长期：移出默认 builtin，改为受控 ops plugin。
4. 所有 shell 调用必须进入 audit log。
5. 所有 shell 调用必须经过 `GovernedToolExecutor` 或等价统一治理入口。

---

### SEC-02：服务端动态 `/tools/call` 与 `/mcp/tools/call` 缺少强制治理门

**裁决**：接纳。  
**优先级**：P0。  
**性质**：真实设计缺陷，不只是静态候选。  

#### 证据

`/tools/call`：

```text
request body.name
  -> handle_tools_call()
  -> invoker.invoke(name, arguments)
```

`/mcp/tools/call`：

```text
request body.name / params.name
  -> handle_mcp_tools_call()
  -> MCPServer.call_tool(name, arguments)
  -> self._invoker.invoke(name, arguments)
```

这两条路径都绕过了统一的 high-risk tool decision、approval、workspace sandbox、URLPolicy、argument redaction 和 audit 设计。

#### 需要澄清的现状

系统不是完全没有鉴权：

- `AuthMiddleware` 存在。
- `RateLimiter` 存在。
- `CapabilityPolicy` 存在。
- `HarnessExecutor` 和 `PermissionGate` 存在。

但当前问题是：

- `AuthMiddleware` 在未设置 `HI_AGENT_API_KEY` 时禁用所有鉴权。
- AuthMiddleware 只区分 read/write/admin，不理解 capability risk。
- `/tools/call` 直接调用 invoker。
- `/mcp/tools/call` 直接调用 MCPServer，再调用 invoker。
- 默认 harness 没有 permission gate。
- capability metadata 不足以驱动统一治理。

#### 整改要求

新增统一入口：

```text
GovernedToolExecutor.invoke(
  principal,
  session,
  capability_name,
  arguments,
  source,
  runtime_mode,
)
```

它必须负责：

- capability descriptor 查询。
- enabled/disabled 判断。
- required_env / availability 判断。
- risk_class 判断。
- side_effect_class 判断。
- RBAC 判断。
- approval 判断。
- path/url argument policy。
- argument redaction。
- audit record。
- output budget。

所有入口必须改为：

```text
/tools/call      -> GovernedToolExecutor
/mcp/tools/call  -> GovernedToolExecutor
RunExecutor      -> HarnessExecutor or GovernedToolExecutor
MCPServer        -> GovernedToolExecutor-backed invoker
```

验收标准：

- 未授权远程请求不能调用 `shell_exec`。
- 未授权远程请求不能调用 `file_write`。
- `web_fetch` 访问私网地址被拒绝。
- 拒绝路径返回 typed error，不返回 500。
- 拒绝路径产生 audit event。
- 所有 tool call 测试覆盖 allow、deny、approval_required 三类。

---

### SEC-03：pickle 反序列化风险

**裁决**：部分接纳。  
**优先级**：P1。  
**性质**：高危设计，但当前未证明外部可写可达。  

#### 证据

`RetrievalEngine._load_index()` 使用：

```python
pickle.load(f)
```

缓存路径是：

```text
{storage_dir}/.index_cache.pkl
```

#### 接纳范围

接纳：

- `pickle.load` 本身是不安全反序列化 sink。
- 如果 storage_dir 可被低权限用户、插件、工具或外部上传写入，则可能形成 RCE。
- 作为企业级平台，不应长期保留 unsigned pickle cache。

部分接纳：

- 当前没有证据证明该 pickle 文件可由远程请求直接写入。
- 因此不把它列为 P0 exploit，而列为 P1 安全债。

#### 整改要求

优先方案：

- 用 JSON/SQLite/msgpack 替代 pickle cache。
- 保存明确 schema version。
- 加 index fingerprint。
- 加 rebuild fallback。

过渡方案：

- 对 pickle cache 加 HMAC 签名。
- 签名 key 来自 env 或 profile secret。
- 签名失败时删除 cache 并 rebuild。
- storage_dir 权限检查失败时禁用 cache。

验收标准：

- 篡改 `.index_cache.pkl` 后不会执行反序列化对象。
- cache schema version 不匹配时自动 rebuild。
- storage_dir 为 world-writable 时 prod readiness 降级或禁用 pickle cache。

---

### SEC-04：动态 URL 访问 / SSRF 候选

**裁决**：拆分接纳。  
**优先级**：`web_fetch` 为 P0/P1，kernel client 为 P1，脚本为 P3。  

#### 4.1 `web_fetch` SSRF

**裁决**：接纳。  
**优先级**：P0/P1。  

`web_fetch_handler` 接受 payload 中的任意 URL 并用 urllib 访问。该工具默认注册，且可通过 tool call 触达。它应纳入远程工具 SSRF 防护。

整改要求：

- 新增 `URLPolicy`。
- 默认禁止 localhost、loopback、private network、link-local、metadata IP。
- 默认禁止非 http/https。
- DNS 解析后校验 IP。
- 重定向后重新校验。
- dev profile 可显式放宽，但必须 audit。

#### 4.2 `KernelFacadeClient` SSRF

**裁决**：部分接纳。  
**优先级**：P1。  

`kernel_base_url` 是配置型后端地址，不是普通用户输入。生产中 agent-kernel 合法部署在内网或 localhost 的情况很常见。因此不接纳“统一禁止私网/localhost”的建议。

整改要求：

- `kernel_base_url` 只允许来自可信配置源，不允许来自 task payload、模型输出或普通 HTTP 请求。
- prod 模式必须显式配置 `kernel_base_url`，不能 fallback 到 local。
- 支持 `trusted_backend_url_policy`：
  - allow internal only if explicitly configured。
  - deny metadata IP。
  - deny userinfo URL。
  - validate scheme is http/https。
- `/doctor` 输出 kernel URL risk posture。

#### 4.3 `scripts/load_test_runs.py`

**裁决**：不作为产品漏洞接纳。  
**优先级**：P3 文档/脚本卫生。  

这是压测脚本，base URL 来自命令行。可增加 warning 和简单 URL validation，但不列入生产 P0/P1。

---

### SEC-05：动态路径读写 / 路径穿越候选

**裁决**：拆分接纳。  
**优先级**：文件工具 P0/P1，内部 managed store P2。  

#### 5.1 `file_read` / `file_write`

**裁决**：接纳。  
**优先级**：P0/P1。  

当前 `file_read_handler` 和 `file_write_handler` 直接使用 payload path。它们默认注册，可远程动态调用，必须加 workspace sandbox。

整改要求：

- 新增 `safe_resolve(base_dir, user_path)`。
- 禁止绝对路径，除非 profile 明确允许。
- resolve 后必须仍在 workspace/session/artifact allow root 内。
- 检查 symlink 最终路径。
- Windows 覆盖 drive letter、UNC path、大小写绕过。
- 写入默认只允许 artifact/session temp 目录。
- 删除类能力默认不提供。

#### 5.2 `runner.py` checkpoint path

**裁决**：部分接纳。  
**优先级**：P2。  

`checkpoint_path` 通常来自内部 resume/checkpoint 流程，不等同于公开文件工具。但仍应在后续引入统一 path utility。

#### 5.3 memory / knowledge store 路径

**裁决**：部分接纳。  
**优先级**：P2。  

这些路径多数由 storage_dir/profile 管理，不是普通用户直接输入。但应逐步统一到 profile home/sandbox root 下，防止配置误用和插件污染。

---

### SEC-06：远程工具接口补鉴权、RBAC、速率限制

**裁决**：部分接纳。  
**优先级**：P0/P1。  

#### 现状

已存在：

- `AuthMiddleware`。
- `RateLimiter`。
- `CapabilityPolicy`。
- `RBACEnforcer`。

但需要补：

- prod 模式下未配置 `HI_AGENT_API_KEY` 应进入 readiness degraded 或 fail-close。
- `/tools/call`、`/mcp/tools/call` 需要 capability-level RBAC，而不仅是 HTTP method write role。
- rate limit 应对高风险 tool 单独加 stricter bucket。
- audit 需要记录 tool-level 决策。

#### 裁决

接纳“需要补强远程工具接口治理”，但不接纳“完全没有鉴权/限流”的绝对表述。

---

## 3. 工程性能与可维护性反馈逐条裁决

### ENG-01：`runner.py` 过大且职责过重

**裁决**：接纳。  
**优先级**：P1/P2，不列为 P0 安全阻断。  

当前 `runner.py` 约 3478 行，确实是 God Object。拆分方向与此前架构方案一致。

但执行顺序需要修正：

- 不应先大拆再补安全治理。
- 应先加 characterization tests。
- 优先抽副作用边界清晰的模块。

推荐顺序：

1. `RunFinalizer`，但明确它是副作用集中器，不是只读对象。
2. `GateCoordinator`。
3. `ActionDispatcher`。
4. `RecoveryCoordinator`。
5. `StageOrchestrator`。

不接纳：

- 不把“拆 runner.py”列为当前第一 P0。
- 不接受一次性移动大量代码的重构 PR。

---

### ENG-02：热路径 sync/async 临时桥接

**裁决**：接纳。  
**优先级**：P1。  

证据：

- `RunExecutor._invoke_capability_via_hooks()` 在 running loop 中每次创建 `ThreadPoolExecutor(max_workers=1)`。
- `HttpLLMGateway.complete()` 在 failover chain 分支也存在类似模式。
- `CapabilityInvoker` 的 timeout call 也会 per-call 创建 `ThreadPoolExecutor(max_workers=1)`。

整改要求：

- 引入共享 bridge executor 或专门的 async bridge service。
- 避免每次调用创建 executor。
- 为 `execute_async` 建立 async-native hook path。
- 对 sync API 保留兼容层，但不要让 sync bridge 成为 async 主链路。

验收：

- 压测 capability hook 调用时 executor 创建次数可观测且下降。
- 不破坏现有 `test_async_hook_wrapping` 语义。

---

### ENG-03：同步 `HttpLLMGateway` 阻塞式重试

**裁决**：接纳。  
**优先级**：P1。  

证据：

- `HttpLLMGateway._post()` 使用 `urllib.request.urlopen`。
- retry backoff 使用 `time.sleep(delay)`。
- 文件中已有 async `HTTPGateway`，使用 `httpx.AsyncClient` 和连接池。

整改要求：

- 明确 `HttpLLMGateway` 是兼容层。
- async `HTTPGateway` 成为 async runtime 的主实现。
- sync runtime 若继续使用 `HttpLLMGateway`，必须标记 execution provenance。
- failover chain 走 async path，不通过 per-call thread pool。

不接纳：

- 不要求所有调用立刻 async-first 重写。先把主生产路径切到 async gateway，再保留 sync compatibility。

---

### ENG-04：`ContextManager` 重复组装成本

**裁决**：部分接纳。  
**优先级**：P2。  

事实成立：`prepare_context()` 每次重建多个 section 并重复 token count。

但需要谨慎：

- system/tools/skills 低频变化，可以缓存。
- memory/knowledge/history/reflection 变化较快，必须有 dirty flag。
- skill prompt 涉及 loader/evolver，不能盲目 memoization。

整改要求：

- 引入 section-level cache。
- 每个 section 有 fingerprint。
- token count cache 以 content hash 为 key。
- cache hit/miss 进入 metrics。
- 先加 profiling，再设目标。

不接纳：

- 不做全量 context snapshot 缓存。
- 不缓存未定义失效规则的 memory/history。

---

### ENG-05：`RetrievalEngine` 索引策略脆弱

**裁决**：接纳。  
**优先级**：P1/P2。  

接纳原因：

- pickle cache 有安全债。
- 首次 retrieve 可能触发 build_index。
- index invalidation 不够明确。
- 直接访问 `_graph._nodes`，模块边界脆弱。

整改要求：

- 替换或保护 pickle cache。
- 加 index fingerprint。
- 加 dirty flag。
- 加 background warmup。
- 给 graph 提供 `iter_nodes()` 或 snapshot API。

---

### ENG-06：memory store 文件扫描扩展性一般

**裁决**：接纳。  
**优先级**：P2。  

短期文件扫描简单可靠，不应急着迁移数据库。

整改要求：

- 先加 list_recent/list_by_date profiling。
- 超过阈值后启用 metadata manifest。
- 中期评估 SQLite metadata index。
- 正文仍可保留文件存储。

---

### ENG-07：`SqliteEvidenceStore` 每次写入 commit

**裁决**：部分接纳。  
**优先级**：P2。  

当前每次 `store()` commit 是 durability-first 设计，不一定错。只有在 evidence 高频写入成为瓶颈时才需要 batch。

整改要求：

- 增加可选 `store_many()`。
- 增加 explicit transaction context。
- 默认 `store()` 保持 immediate commit，避免破坏审计 durability。
- 高频 harness path 可选择 buffered writer。

---

### ENG-08：`server/app.py` 单文件过大

**裁决**：接纳。  
**优先级**：P2。  

当前 `server/app.py` 约 2708 行。拆分为 routes 模块有利于后续 auth、policy、tracing、profiling。

建议顺序：

1. routes_health_ops。
2. routes_tools_mcp。
3. routes_runs。
4. routes_memory_knowledge。
5. routes_skills_evolve。

不要在路由拆分时改变响应 shape。

---

### ENG-09：fallback 逻辑偏多，容易掩盖真实问题

**裁决**：接纳。  
**优先级**：P1。  

代码中存在大量 best-effort fallback。这在 agent 平台中合理，但必须可观测。

整改要求：

- 建立 fallback taxonomy。
- 区分 `expected_degradation`、`unexpected_exception`、`security_denied`、`dependency_unavailable`。
- 所有 fallback 写入 metrics。
- run result provenance 聚合 fallback。
- prod-real 下危险 fallback fail-close。

---

### ENG-10：私有字段穿透访问

**裁决**：接纳。  
**优先级**：P2。  

证据包括：

- `budget_tracker._max_calls`。
- `budget_tracker._total_tokens`。
- `graph._nodes`。
- route_engine `_context_provider` 后构造注入。

整改要求：

- `LLMBudgetTracker.snapshot()`。
- `LongTermMemoryGraph.iter_nodes()`。
- route engine constructor/provider 注入。
- 禁止新增跨模块私有字段访问，新增 lint/grep guard。

---

### ENG-11：token 计数启发式

**裁决**：部分接纳。  
**优先级**：P2。  

现状不是完全没有扩展点。`task_view/token_budget.py` 已有 `set_token_counter()`。

问题是：

- 默认仍是 `len(text)//4`。
- provider/model 未自动接入真实 tokenizer。
- usage 与估算偏差未记录。

整改要求：

- provider-aware token counter。
- 配置真实 tokenizer。
- fallback 到 heuristic 时 provenance 标记。
- 记录 estimated vs provider usage delta。

---

## 4. 不接纳或降级处理的建议

### 4.1 不接纳：把所有 URL 访问统一禁止私网

原因：

- agent-kernel、内部 webhook、内部 observability endpoint 在企业部署中常在私网。
- `kernel_base_url` 是 trusted backend config，不是普通用户 URL。

替代方案：

- 对 `web_fetch` 执行严格 SSRF policy。
- 对 `kernel_base_url` 执行 trusted backend URL policy。
- 对 scripts 只做 warning 和基本 validation。

### 4.2 不接纳：立即把 `runner.py` 拆分作为最高 P0

原因：

- 当前更紧急的是高危工具治理和远程调用入口。
- 大拆 runner 会扩大回归面，不应阻塞安全底线。

替代方案：

- P0 修安全治理。
- P1 开始 characterization-first 拆分。

### 4.3 不接纳：直接删除 `shell_exec`

原因：

- 当前测试和开发路径依赖它。
- 直接删除会破坏兼容，并导致开发者绕过平台自己执行 shell。

替代方案：

- prod 默认禁用。
- dev 保留但标记风险。
- profile/policy 显式开启。
- 长期迁移到受控 ops plugin。

### 4.4 不接纳：把压测脚本 SSRF 作为产品 P0

原因：

- `scripts/load_test_runs.py` 是手动压测工具。
- base URL 来自操作者命令行。

替代方案：

- 加 usage warning。
- 默认仍是 localhost。
- 可选加 `--allow-private` 明确开关。

---

## 5. 系统整改方案

### Phase 0：基线与安全冻结

**周期**：1-2 天  
**目标**：避免整改过程中不知道是否退化。

工作项：

- 记录当前 `/tools`、`/tools/call`、`/mcp/tools/list`、`/mcp/tools/call` 行为。
- 记录当前 builtin tools manifest。
- 记录当前 auth middleware 在有/无 `HI_AGENT_API_KEY` 下的行为。
- 记录当前 `shell_exec`、`file_read`、`file_write`、`web_fetch` 测试基线。
- 记录当前 full pytest、ruff、coverage。

产物：

```text
docs/platform/security-runtime-baseline-2026-04-17.md
```

准入：

- 无 baseline，不进入 P0 改造。

---

### Phase 1：P0 安全治理底线

**周期**：第 1 周  
**目标**：先阻断远程高危工具误调用。

#### P0-1：CapabilityDescriptor 风险元数据

新增或扩展 descriptor：

```python
CapabilityDescriptor(
    name: str,
    risk_class: Literal["read_only", "filesystem_read", "filesystem_write", "network", "shell", "credential"],
    side_effect_class: str,
    remote_callable: bool,
    prod_enabled_default: bool,
    requires_auth: bool,
    requires_approval: bool,
    required_env: list[str],
    output_budget_chars: int,
)
```

首批标注：

```text
file_read   -> filesystem_read
file_write  -> filesystem_write, requires_approval
web_fetch   -> network
shell_exec  -> shell, prod_enabled_default=false, requires_approval
```

验收：

- `/manifest` 输出 descriptor view。
- `/tools` 输出 risk metadata。
- 未标注 capability 在 prod 下不可远程调用。

#### P0-2：危险 builtin 默认策略

要求：

- prod-real 下 `shell_exec` 默认不注册或注册为 disabled。
- `file_write` 默认 requires_approval。
- `web_fetch` 默认启用 URLPolicy。
- `file_read` 默认启用 PathPolicy。

兼容：

- dev-smoke 保持可用，但响应和 manifest 标记为 dev-risk。
- 现有测试按 dev profile 继续可跑。

#### P0-3：统一 `GovernedToolExecutor`

所有 tool 调用入口收敛到一个执行器：

```text
RunExecutor action dispatch
/tools/call
/mcp/tools/call
MCPServer.call_tool
CLI tools call
```

验收：

- 直接 `invoker.invoke()` 不再出现在 server route handler 中。
- 所有拒绝路径返回 typed error。
- 所有 allow/deny/approval 记录 audit。

#### P0-4：PathPolicy

实现：

```python
safe_resolve(base_dir: Path, user_path: str) -> Path
```

规则：

- 默认禁止绝对路径。
- resolve 后必须仍在 allowed root 内。
- symlink 最终路径必须校验。
- Windows drive/UNC 覆盖测试。
- 写入目录与读取目录可分离配置。

首批接入：

- `file_read_handler`
- `file_write_handler`

#### P0-5：URLPolicy for `web_fetch`

规则：

- 默认只允许 http/https。
- 禁止 loopback/private/link-local/metadata IP。
- DNS 解析后校验。
- 重定向后重新校验。
- 限制 response size。
- 限制 timeout。

首批接入：

- `web_fetch_handler`

#### P0-6：远程工具接口 auth posture

要求：

- prod-real 下 `HI_AGENT_API_KEY` 未配置时 `/ready` degraded 或 fail。
- `/tools/call` 与 `/mcp/tools/call` 必须带 principal。
- API-key 只授予基本 write，不自动拥有 shell/file_write 权限。
- high-risk capability 需要 role 或 approval。

---

### Phase 2：P1 安全债与可观测性

**周期**：第 2-4 周  
**目标**：补齐反序列化、fallback、route filtering 和审计闭环。

#### P1-1：pickle cache 替换或签名

优先替换为 JSON/SQLite/msgpack。

如果短期保留 pickle：

- HMAC 签名。
- schema version。
- storage dir permission check。
- 签名失败 rebuild。

#### P1-2：RouteEngine capability availability filter

要求：

- route proposal 不能选择 disabled/unavailable capability。
- high-risk capability 必须有 explicit policy。
- unknown action_kind 不能直接落到 invoker。

验收：

- LLMRouteEngine 输出 `shell_exec` 时，在 prod 默认被拒绝或改为 approval pending。
- unavailable tool 不进入 final action proposal。

#### P1-3：fallback/degraded metrics

新增 taxonomy：

```text
expected_degradation
unexpected_exception
security_denied
dependency_unavailable
heuristic_fallback
policy_bypass_dev
```

要求：

- fallback 进入 metrics。
- run result provenance 聚合 fallback。
- release gate 可阻断 prod-real 中的 unsafe fallback。

#### P1-4：audit trail

所有 tool call 记录：

- principal。
- session/run id。
- tool name。
- risk class。
- argument digest/redacted summary。
- decision。
- approval id。
- result status。

---

### Phase 3：P1/P2 热路径治理

**周期**：第 4-8 周  
**目标**：减少主链路性能抖动，为大规模运行打基础。

#### PERF-1：sync/async bridge 收敛

工作项：

- 引入共享 bridge executor。
- async hook path 不再 per-call 创建 ThreadPoolExecutor。
- failover chain 走 async-native path。
- CapabilityInvoker timeout executor 可复用。

验收：

- 压测中 executor creation count 下降。
- p95 capability hook latency 降低或稳定。

#### PERF-2：HttpLLMGateway 兼容层化

工作项：

- 明确同步 gateway 仅用于兼容。
- async `HTTPGateway` 成为 local-real/prod-real 主路径。
- sync path provenance 标记。
- `time.sleep` 重试不进入 async runtime。

#### PERF-3：ContextManager section cache

工作项：

- system/tools/skills cache。
- token count content-hash cache。
- memory/history dirty flag。
- cache metrics。

先做 profiling，再设优化目标。

#### PERF-4：RetrievalEngine index governance

工作项：

- fingerprint。
- dirty flag。
- background warmup。
- graph `iter_nodes()`。
- cache format 安全化。

---

### Phase 4：P2 可维护性与扩展性

**周期**：第 8-12 周  
**目标**：降低复杂度和长期维护成本。

#### MAINT-1：拆分 `runner.py`

顺序：

1. `RunFinalizer`
2. `GateCoordinator`
3. `ActionDispatcher`
4. `RecoveryCoordinator`
5. `StageOrchestrator`

要求：

- characterization tests 先行。
- 每个 PR 只拆一个边界。
- 外部 API shape 不变。

#### MAINT-2：拆分 `server/app.py`

顺序：

1. `routes_health_ops.py`
2. `routes_tools_mcp.py`
3. `routes_runs.py`
4. `routes_memory_knowledge.py`
5. `routes_skills_evolve.py`

要求：

- response shape snapshot。
- auth/rate-limit/gov helper 统一。

#### MAINT-3：Memory store metadata index

工作项：

- manifest metadata。
- list_recent O(log n) 或 O(k)。
- 正文 lazy load。
- 可选 SQLite metadata backend。

#### MAINT-4：Evidence store batch API

工作项：

- `store_many()`。
- transaction context。
- optional buffered writer。
- 默认 `store()` 保持 immediate commit。

#### MAINT-5：私有字段穿透清理

新增接口：

- `LLMBudgetTracker.snapshot()`。
- `LongTermMemoryGraph.iter_nodes()`。
- `LongTermMemoryGraph.stats()`。
- route engine provider constructor injection。

---

## 6. 推荐工单清单

### P0-SEC-1：危险 builtin policy

**文件**：

- `hi_agent/capability/tools/builtin.py`
- `hi_agent/config/builder.py`
- `hi_agent/capability/registry.py`
- `tests/test_builtin_tools.py`
- 新增 `tests/test_builtin_tool_policy.py`

**验收**：

- prod-real 默认不能远程调用 `shell_exec`。
- dev-smoke 可显式启用。
- manifest 显示 `shell_exec` disabled reason。

### P0-SEC-2：GovernedToolExecutor

**文件**：

- 新增 `hi_agent/capability/governance.py`
- `hi_agent/server/app.py`
- `hi_agent/server/mcp.py`
- `hi_agent/runner.py`
- `hi_agent/cli.py`

**验收**：

- server route handler 不直接调用 raw invoker。
- MCP 调用不绕过 governance。
- 拒绝路径有 typed response 和 audit。

### P0-SEC-3：PathPolicy

**文件**：

- 新增 `hi_agent/security/path_policy.py`
- `hi_agent/capability/tools/builtin.py`
- `tests/test_path_policy.py`

**验收**：

- `../` 跳出 workspace 被拒绝。
- 绝对路径默认被拒绝。
- symlink escape 被拒绝。
- Windows drive/UNC path 被拒绝或明确策略化。

### P0-SEC-4：URLPolicy for web_fetch

**文件**：

- 新增 `hi_agent/security/url_policy.py`
- `hi_agent/capability/tools/builtin.py`
- `tests/test_url_policy.py`

**验收**：

- `127.0.0.1` 被拒绝。
- `169.254.169.254` 被拒绝。
- 私网 IP 被拒绝。
- 重定向到私网被拒绝。
- allowlist 域名可通过。

### P1-SEC-5：Retrieval cache 安全化

**文件**：

- `hi_agent/knowledge/retrieval_engine.py`
- `tests/test_retrieval_engine_cache_security.py`

**验收**：

- 不再无条件 `pickle.load`。
- cache 版本不匹配 rebuild。
- 篡改 cache 不执行对象。

### P1-PERF-1：Async bridge service

**文件**：

- 新增 `hi_agent/runtime/async_bridge.py`
- `hi_agent/runner.py`
- `hi_agent/llm/http_gateway.py`
- `hi_agent/capability/invoker.py`

**验收**：

- per-call executor 创建消失或显著减少。
- async hook wrapping 现有测试保持通过。

### P2-MAINT-1：server tools/mcp routes 拆分

**文件**：

- 新增 `hi_agent/server/routes_tools_mcp.py`
- `hi_agent/server/app.py`

**验收**：

- `/tools`、`/tools/call`、`/mcp/tools/list`、`/mcp/tools/call` response shape 不变，除了新增安全字段和 typed errors。

---

## 7. 测试策略

### 7.1 安全测试

新增测试组：

```text
tests/security/test_tool_governance.py
tests/security/test_path_policy.py
tests/security/test_url_policy.py
tests/security/test_remote_tool_authz.py
tests/security/test_retrieval_cache_integrity.py
```

必须覆盖：

- 未授权调用 `shell_exec`。
- 普通 write token 调用 `file_write`。
- `web_fetch` SSRF payload。
- `file_read` 路径穿越。
- MCP tool 绕过 governance。
- prod 未配置 API key。
- cache 篡改。

### 7.2 性能回归测试

新增 benchmark 或 lightweight perf tests：

- ContextManager prepare_context cache hit/miss。
- Capability hook bridge executor creation。
- Http gateway retry behavior。
- RetrievalEngine warmup vs first query。
- Memory list_recent 大目录扫描。

### 7.3 合同测试

新增 snapshot：

- `/manifest.capability_views`
- `/tools` risk metadata。
- `/ready` auth/security posture。
- tool deny response shape。
- audit event shape。

---

## 8. 发布与兼容策略

安全整改会影响默认行为，必须做兼容发布。

### 8.1 兼容字段

`/manifest.capabilities` 保持旧 list：

```json
"capabilities": ["file_read", "web_fetch"]
```

新增：

```json
"capability_views": [
  {
    "name": "shell_exec",
    "risk_class": "shell",
    "enabled": false,
    "disabled_reason": "prod_default_disabled"
  }
]
```

### 8.2 行为变更

正式公告：

- prod 默认禁用 `shell_exec`。
- prod 默认要求远程 tool call 鉴权。
- prod 默认启用 PathPolicy/URLPolicy。
- dev-smoke 保留兼容，但带风险标记。

### 8.3 回滚策略

- 通过 profile flag 临时恢复旧行为，但只允许 dev/local-real。
- prod emergency override 必须写 audit。
- release gate 对 unsafe override fail 或 require manual waiver。

---

## 9. 最终裁决表

| 编号 | 问题 | 裁决 | 优先级 | 说明 |
|---|---|---|---|---|
| SEC-01 | 动态工具调用串联 shell 执行 | 接纳 | P0 | 高风险候选，默认 shell_exec 必须收敛 |
| SEC-02 | `/tools/call` / `/mcp/tools/call` 缺强制治理 | 接纳 | P0 | 真实设计缺陷 |
| SEC-03 | pickle 反序列化 | 部分接纳 | P1 | 未证明外部可写，但设计不安全 |
| SEC-04A | `web_fetch` SSRF | 接纳 | P0/P1 | 远程工具必须 URLPolicy |
| SEC-04B | kernel client SSRF | 部分接纳 | P1 | 配置型 backend URL，不能禁私网一刀切 |
| SEC-04C | load_test_runs SSRF | 不作为产品漏洞接纳 | P3 | 脚本卫生即可 |
| SEC-05A | file_read/write 路径穿越 | 接纳 | P0/P1 | 远程文件工具必须 sandbox |
| SEC-05B | checkpoint/internal store 路径 | 部分接纳 | P2 | 统一 path utility，但不是远程 P0 |
| SEC-06 | 远程工具 auth/RBAC/rate limit | 部分接纳 | P0/P1 | 基座存在，但 capability-level 不足 |
| ENG-01 | runner.py God Object | 接纳 | P1/P2 | 重要但不压过 P0 安全 |
| ENG-02 | sync/async 临时桥接 | 接纳 | P1 | 明确热路径风险 |
| ENG-03 | 同步 HTTP gateway 阻塞重试 | 接纳 | P1 | async gateway 应成为主路径 |
| ENG-04 | ContextManager 重复组装 | 部分接纳 | P2 | 需 dirty flag 和 profiling |
| ENG-05 | RetrievalEngine 索引脆弱 | 接纳 | P1/P2 | 安全与性能双重债 |
| ENG-06 | memory store 扫描扩展性 | 接纳 | P2 | 规模化前治理 |
| ENG-07 | SQLite evidence 每次 commit | 部分接纳 | P2 | 保留 durable default，新增 batch |
| ENG-08 | server/app.py 过大 | 接纳 | P2 | 路由模块化 |
| ENG-09 | fallback 过宽 | 接纳 | P1 | 指标化和 provenance |
| ENG-10 | 私有字段穿透 | 接纳 | P2 | 补 snapshot/iter/stats 接口 |
| ENG-11 | token 启发式估算 | 部分接纳 | P2 | 已有扩展点，需默认真实 tokenizer 与偏差观测 |

---

## 10. 最终建议

下一步不要先大拆 `runner.py`，也不要把静态扫描候选直接当已验证漏洞对外宣布。更稳的顺序是：

1. 用 Phase 0 冻结安全和运行基线。
2. 先修 P0 安全治理底线：危险工具默认策略、统一 governance、PathPolicy、URLPolicy、远程工具鉴权和审计。
3. 再修 P1 安全债：pickle、route capability filtering、fallback metrics。
4. 然后治理热路径：sync/async bridge、HTTPGateway、ContextManager、RetrievalEngine。
5. 最后拆 God Object 和扩展 store/index。

这套顺序能同时满足三件事：

1. 先挡住真实高风险能力暴露。
2. 不把未验证静态候选夸大成已利用漏洞。
3. 不在安全底线未收敛前启动大范围结构迁移。

