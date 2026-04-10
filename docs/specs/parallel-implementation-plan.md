# hi-agent 并行实施计划（融合版）

最后更新：2026-04-10  
适用范围：`hi-agent` 主仓（不改 `agent-kernel` 协议边界）

---

## 1. 输入与结论来源

本计划综合三类输入：
- 外部对标：`hermes-agent` 架构与工程实践（工具注册、上下文压缩、状态存储、网关化运维能力）。
- 现有内部分析：`findings.md` 与 `task_plan.md` 的问题清单与优先级建议。
- 当前代码实况：`hi_agent/` 已具备 TRACE 分层、治理与演化能力，但在“生产韧性 + 运营可观测 + 成本效率”链路仍有明显短板。

核心判断：
- `hi-agent` 不应“复制” Hermes 的单体实现，而应“吸收能力模型”并落到 TRACE 分层。
- 先补齐生产韧性闭环，再做效率优化与架构去耦。

---

## 2. 目标与非目标

## 2.1 目标（8 周）

1. 建立 LLM 调用生产韧性闭环：错误分类、凭证池、限流感知、可观测降级。  
2. 建立上下文成本优化闭环：结构化压缩 + Prompt 缓存 + 压缩状态透明化。  
3. 建立会话级可检索数据底座：SQLite/WAL + FTS5 + 跨会话检索注入。  
4. 降低核心执行器耦合：RunExecutor 依赖分组注入 + Management Facade。  
5. 保持兼容：`execute()/execute_graph()/execute_async()` 对外行为不变。

## 2.2 非目标（本期不做）

1. 不引入 Hermes 的多消息平台网关体系。  
2. 不引入大规模 UI/产品层改造。  
3. 不修改 `agent-kernel` 核心协议定义。

---

## 3. 并行工作流分轨（Tracks）

为避免单线程串行，本计划拆为 6 条并行轨道，按“最小交叉写集”组织。

## Track A：生产韧性（P0，关键路径）

范围：
- `hi_agent/llm/error_classifier.py`（新增）
- `hi_agent/llm/credential_pool.py`（新增）
- `hi_agent/llm/rate_limit_tracker.py`（新增）
- `hi_agent/llm/http_gateway.py`、`router.py`、`model_selector.py`（集成）

交付：
- `ClassifiedLLMError` 与 `LLMFailoverReason` 标准分类输出。
- 多凭证轮换（含 cooldown）与 provider 级 fallback。
- 响应头限流状态解析 + 路由决策接入。

## Track B：上下文效率（P1）

范围：
- `hi_agent/memory/async_compressor.py`
- `hi_agent/task_view/auto_compress.py`
- `hi_agent/llm/prompt_caching.py`（新增）
- `hi_agent/llm/http_gateway.py`（cache 控制注入）

交付：
- 结构化压缩模板（Goal/Progress/Decisions/Files/Next Steps）。
- 迭代式摘要更新（保留前序摘要，增量合并）。
- 压缩失败/降级可观测（事件+日志+统计）。
- Anthropic 优先的 prompt cache 控制策略。

## Track C：状态底座与检索（P2）

范围：
- `hi_agent/session/session_db.py`（新增）
- `hi_agent/memory/session_search.py`（新增）
- `hi_agent/session/run_session.py`（接入）
- 可选：与 JSONL 双写/切换策略

交付：
- SQLite WAL 会话存储，含 schema migration。
- FTS5 全文检索与跨会话 recall API。
- 与 TaskView/Memory 检索链路接通。

## Track D：能力注册与调度安全（P2）

范围：
- `hi_agent/capability/registry.py`
- `hi_agent/orchestrator/parallel_dispatcher.py`

交付：
- Capability 可用性探测（`requires_env`/`check_fn`）。
- 动态注册/注销能力接口（为 MCP 热更新做准备）。
- 子代理/并行调度安全约束（深度、并发上限、禁用能力集）。

## Track E：核心执行器去耦（P1）

范围：
- `hi_agent/runner.py`
- `hi_agent/management/facade.py`（新增）
- `hi_agent/management/*`（仅 facade 接线，不做大搬迁）

交付：
- `ExecutorSubsystems` 依赖聚合注入模型。
- RunExecutor 构造复杂度下降，职责边界清晰。
- Management 统一入口，避免横向模块直接耦合。

## Track F：配置治理与图安全（P3）

范围：
- `hi_agent/config/trace_config.py`
- `hi_agent/trajectory/graph.py`
- `hi_agent/task_mgmt/*`（调度前校验接入）

交付：
- 配置组合校验与单位一致性校验。
- 图循环/不可达节点校验工具化。
- 调度前合法性阻断，避免运行时死锁/坏图。

---

## 4. 关键依赖图（简化）

1. Track A 完成后，Track B 的网关缓存策略与压缩降级策略更稳定。  
2. Track C 可与 A/B 并行开发，但最终联调依赖 B（检索注入上下文预算协同）。  
3. Track E 可与 A/B 并行推进，发布前必须完成回归验证。  
4. Track D/F 与主链路弱耦合，可并行穿插。

关键路径：
`A -> B -> (C 联调) -> E 收口 -> 全量回归`

---

## 5. Sprint 级并行排程（建议 4 个 Sprint）

## Sprint 0（2-3 天，基线）

1. 冻结接口：明确各 Track 对外 API 草案。  
2. 建立验收基线：`ruff + pytest`、性能与成本基线样本。  
3. 建立特性开关：所有新增能力默认可关闭（防止一次性切换风险）。

## Sprint 1（第 1-2 周）

并行：
1. Track A：错误分类 + 凭证池骨架 + 限流解析骨架。  
2. Track B：结构化压缩框架与压缩状态事件。  
3. Track F：图校验与配置校验框架。

里程碑：
1. LLM 调用失败不再“黑盒失败”，有明确分类与动作建议。  
2. 压缩降级路径全链路可见。  
3. 图与配置具备预校验能力。

## Sprint 2（第 3-4 周）

并行：
1. Track A：凭证轮换策略完成并接入路由。  
2. Track B：prompt cache 接入网关调用。  
3. Track C：SessionDB + FTS5 初版落地。  
4. Track D：Capability 注册增强。

里程碑：
1. 成本与稳定性出现可量化改善。  
2. 会话检索能力可用（内部 API）。

## Sprint 3（第 5-6 周）

并行：
1. Track C：跨会话检索注入 TaskView。  
2. Track E：RunExecutor 依赖去耦与 Management Facade。  
3. Track D：并行调度安全策略（深度/并发/禁用能力）上线。

里程碑：
1. 核心执行器复杂度显著下降。  
2. 检索与执行链路联调通过。

## Sprint 4（第 7-8 周）

并行：
1. 全量回归与压测（稳定性、成本、响应时延）。  
2. 特性开关灰度发布与回滚预案演练。  
3. 文档与运维手册补齐。

里程碑：
1. 生产可发布版本。  
2. 指标达成与上线决策评审。

---

## 6. 可并行任务清单（执行级）

任务编号规则：`A/B/C/D/E/F-序号`。

P0：
- `A-01` 新增 LLM 错误分类器与单测。
- `A-02` 新增凭证池与轮换策略，接入网关调用。
- `A-03` 新增限流跟踪器，接入路由决策。
- `B-01` 压缩结果结构化与降级日志/事件化。

P1：
- `B-02` 结构化摘要 + 迭代摘要更新。
- `B-03` prompt cache 控制器与 provider 适配。
- `E-01` `ExecutorSubsystems` 注入模型落地。
- `E-02` `ManagementFacade` 落地并替换外部调用入口。

P2：
- `C-01` SQLite SessionDB 与迁移机制。
- `C-02` FTS5 搜索 API + TaskView 注入。
- `D-01` Capability 动态注册/可用性检查。
- `D-02` 并行调度安全约束。

P3：
- `F-01` TraceConfig validate 规则完善。
- `F-02` 图安全校验与调度前阻断。

---

## 7. 验收标准（DoD）

通用 DoD：
1. `ruff check hi_agent` 通过。  
2. 相关单测/集成测试通过，新增改动具备覆盖。  
3. 有开关、可灰度、可回滚。  
4. 关键路径有日志与指标。

业务 DoD（本期）：
1. LLM 故障可分类、可追踪、可自动降级。  
2. 平均输入 token 成本显著下降（缓存 + 压缩策略生效）。  
3. 支持跨会话检索并可注入当前任务上下文。  
4. RunExecutor 架构复杂度下降且行为兼容。

---

## 8. 风险与回滚

高风险：
1. RunExecutor 重构引发行为漂移。  
2. SessionDB 引入后数据一致性风险。  
3. Cache 与压缩策略冲突导致上下文污染。

回滚策略：
1. 所有新增能力通过 feature flag 控制。  
2. Session 层保留 JSONL 兜底与双写窗口。  
3. 重构阶段保留旧构造路径（兼容期后再移除）。

---

## 9. 执行协作建议（并行模式）

建议至少 3 个并行执行单元：
1. 单元 R（Reliability）：Track A + B 核心链路。  
2. 单元 P（Persistence）：Track C + F。  
3. 单元 A（Architecture）：Track E + D。

每周节奏：
1. 周一冻结本周接口与写集。  
2. 周三中期联调（仅接口，不追求最终性能）。  
3. 周五全量回归 + 指标复盘。

该节奏可最大化并行开发吞吐，并最小化合并冲突与返工。
