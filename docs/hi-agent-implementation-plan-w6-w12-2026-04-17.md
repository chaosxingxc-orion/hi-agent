# hi-agent 实施计划 W6-W12（Ticket 详版）

**父文档**：`docs/hi-agent-implementation-plan-2026-04-17.md`
**上一阶段**：`docs/hi-agent-implementation-plan-w2-w5-2026-04-17.md`
**关联**：执行前必先读主文档 §0-§1（团队契约 + 锁定合同 + 红线）

---

## W6-W10 通用准入条件（专家 §2.3 硬要求）

god-object 拆分的每个 ticket 必须满足：

1. **Characterization tests first**：先写测试固定当前外部行为，再动代码
2. 新 builder/coordinator **不得访问其他 builder/coordinator 的私有属性**（`_xxx`）
3. 新 builder/coordinator **不得引入新的 post-construction mutation**
4. 外部 API **行为不变**（byte-identical output where applicable）
5. 每个 ticket **独立回滚**（facade 内部委托，旧方法保留一个版本周期）
6. **不在同一 PR 中改结构 + 改业务语义**

违反任一条 → Reviewer 必须退回。

---

## W6 — SystemBuilder 低风险拆分

**Sprint 目标**：ReadinessProbe + SkillBuilder + MemoryBuilder 独立

### HI-W6-001：Characterization suite for SystemBuilder

- Owner：QA Owner
- Reviewer：Arch Reviewer
- 目标：固定 `SystemBuilder` 所有公开 `build_*` 方法的外部行为
- 文件变更：
  - `tests/characterization/test_system_builder_api.py`（新）— 每个 `build_*` 方法：
    - 调用参数签名稳定
    - 返回类型稳定
    - 关键属性存在性
    - readiness snapshot byte-identical（固定 run_id / timestamp）
- 验收：
  - [ ] 35 个 `build_*` 方法全部有 characterization test
  - [ ] 测试运行 <60 秒
- 工作量：2 天
- 依赖：无

### HI-W6-002：抽 `ReadinessProbe`

- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer
- 目标：纯观察器，零 mutation，最安全首拆点
- 文件变更：
  - `hi_agent/config/readiness.py`（新，~300 LOC 移动）
    - `class ReadinessProbe(builder: SystemBuilder)` — 持引用，不写
    - `snapshot() -> ReadinessSnapshot`
    - `prerequisites_for_env(env: str) -> list[Prerequisite]`
  - `hi_agent/config/builder.py:1837-2045`
    - `readiness()` 变 facade：`return ReadinessProbe(self).snapshot().to_dict()`
- 测试：
  - `tests/unit/test_readiness_probe.py`
  - 原有 `/ready` E2E 测试不改
  - Snapshot 测试验证 byte-identical
- 验收：
  - [ ] `/ready` 输出 byte-identical
  - [ ] `ReadinessProbe` 有独立 unit test
  - [ ] `builder.py` 减少 ~300 LOC
  - [ ] Characterization suite 全绿
- 工作量：2 天
- 依赖：HI-W6-001

### HI-W6-003：抽 `SkillBuilder`

- Owner：Cognition Owner
- Reviewer：Arch Reviewer
- 目标：skill_registry / loader / observer / version_manager / evolver 独立
- 文件变更：
  - `hi_agent/config/skill_builder.py`（新，~200 LOC 移动）
    - `class SkillBuilder(config: TraceConfig)` 独立入口
    - 方法：`build_registry()`, `build_loader()`, `build_observer()`, `build_version_manager()`, `build_evolver()`
  - `hi_agent/config/builder.py` 对应方法 → facade
- 测试：
  - `tests/unit/test_skill_builder.py`
  - 现有 test_skill_lifecycle.py 不改
- 验收：
  - [ ] Characterization 全绿
  - [ ] `SkillBuilder` 独立可测
- 工作量：1.5 天
- 依赖：HI-W6-002

### HI-W6-004：抽 `MemoryBuilder`

- Owner：Cognition Owner
- 目标：short_term / mid_term / long_term stores 独立
- 文件变更：
  - `hi_agent/config/memory_builder.py`（新，~150 LOC 移动）
  - `builder.py` 方法 → facade
- 测试：
  - `tests/unit/test_memory_builder.py`
- 验收：
  - [ ] Characterization 全绿
  - [ ] profile_id 参数正确传递
- 工作量：1 天

### W6 Exit

- [ ] 3 个 builder 独立
- [ ] `SystemBuilder` LOC 减少 ~650（2045 → ~1400）
- [ ] `docs/sprints/w6-system-builder-split.md` 更新

---

## W7 — 继续拆分 + RunExecutor 第一步

### HI-W7-001：抽 `KnowledgeBuilder`

- Owner：Cognition Owner
- 目标：wiki / manager / retrieval engine 独立
- 文件变更：
  - `hi_agent/config/knowledge_builder.py`（新，~250 LOC 移动）
  - 依赖 memory stores 作为构造参数（不访问 MemoryBuilder 内部）
- 测试：
  - `tests/unit/test_knowledge_builder.py`
- 工作量：1.5 天

### HI-W7-002：抽 `RetrievalBuilder`

- Owner：Cognition Owner
- Reviewer：Arch Reviewer
- 目标：消除 `engine._embedding_fn = provider.as_callable()` post-construction mutation
- 文件变更：
  - `hi_agent/config/retrieval_builder.py`（新，~100 LOC 移动）
  - **关键改造**：embedding_fn 改为构造参数传入，不再后构造赋值
  - `RetrievalEngine.__init__` 必须接受 `embedding_fn`
- 测试：
  - `tests/unit/test_retrieval_builder.py`
  - `tests/integration/test_retrieval_no_post_construction.py` — 断言 `engine._embedding_fn is not None` 自构造起就成立
- 验收：
  - [ ] Post-construction mutation 消除（grep 无 `engine._embedding_fn = `）
  - [ ] Characterization 全绿
- 工作量：1.5 天

### HI-W7-003：Characterization suite for RunExecutor

- Owner：QA Owner
- Reviewer：Arch Reviewer
- 目标：固定 `RunExecutor` 3 个主入口（execute / execute_graph / execute_async）行为
- 文件变更：
  - `tests/characterization/test_run_executor_api.py`（新）
    - 各入口在 completed / failed / cancelled / gate_pending 4 outcome 下的 RunResult byte-identical
    - `_finalize_run` 副作用顺序：L0 close → lifecycle finalize → failure attribution → L0→L2→L3 → feedback → duration → result
    - 用 instrumentation 记录每个副作用调用时序
- 验收：
  - [ ] 12 场景（3 入口 × 4 outcome）全覆盖
  - [ ] 副作用顺序有测试断言
- 工作量：2 天

### HI-W7-004：抽 `RunFinalizer`

- Owner：Runtime Owner
- Reviewer：Arch Reviewer
- 目标：副作用密集的生命周期阶段封装为独立协调器（**非只读**）
- 文件变更：
  - `hi_agent/execution/__init__.py`（新）
  - `hi_agent/execution/run_finalizer.py`（新，~600 LOC 移动）
    - `class RunFinalizerContext` dataclass — 打包所有需要的引用（raw_memory, mid_term_store, long_term_consolidator, feedback_store, failure_collector, lifecycle, metrics_collector, session, contract, dag, action_seq, policy_versions, _pending_subrun_futures, _completed_subrun_results, _last_exception_msg, _last_exception_type, _skill_ids_used, _run_start_monotonic）
    - `class RunFinalizer(ctx: RunFinalizerContext)`
    - `finalize(outcome: str) -> RunResult` — 执行副作用并组装 RunResult
    - 关联方法 `_cancel_pending_subruns` / `_build_postmortem` 一并迁入
  - `hi_agent/runner.py:1845-2070`
    - `_finalize_run` 变 facade：
      ```python
      def _finalize_run(self, outcome: str) -> RunResult:
          ctx = self._build_finalizer_context()
          return RunFinalizer(ctx).finalize(outcome)
      ```
- 测试：
  - `tests/unit/test_run_finalizer.py`
  - Characterization suite（HI-W7-003）全绿
- 验收：
  - [ ] RunFinalizer 有独立测试覆盖 completed/failed/cancelled
  - [ ] 副作用顺序 byte-identical（characterization 断言）
  - [ ] `runner.py` LOC 减少 ~600
  - [ ] L0 close → L2 consolidation 顺序不变
- 工作量：3 天
- 依赖：HI-W7-003

### W7 Exit

- [ ] 5 个 builder 独立 + RunFinalizer 独立
- [ ] Post-construction mutation 减少 1 处（retrieval）

---

## W8 — SystemBuilder 中风险 + RunExecutor 第二步

### HI-W8-001：抽 `ServerBuilder`

- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer
- 目标：消除 `builder.py:1816-1831` 的 7 处 post-construction assignment
- 文件变更：
  - `hi_agent/config/server_builder.py`（新，~200 LOC 移动）
  - `AgentServer.__init__` 改造：**所有 wiring 通过构造参数**（memory, knowledge, skill, metrics, kernel_adapter 等），不再事后赋值
  - `hi_agent/config/builder.py:1807-1835` `build_server()` 变 facade
- 测试：
  - `tests/unit/test_server_builder.py`
  - `tests/integration/test_agent_server_no_post_construction.py`
- 验收：
  - [ ] `grep "server\.\w* = " hi_agent/config/` 无匹配（post-construction 消除）
  - [ ] `AgentServer.__init__` 参数列表显式声明所有依赖
  - [ ] 现有 server E2E 测试全绿
- 工作量：3 天
- 依赖：characterization

### HI-W8-002：抽 `CapabilityPlaneBuilder`

- Owner：Capability Owner
- Reviewer：Arch Reviewer
- 目标：打破 LLM-capability 循环依赖
- 文件变更：
  - `hi_agent/config/capability_plane_builder.py`（新，~400 LOC 移动）
    - 接受已构造的 `llm_gateway` 作为参数（依赖注入）
    - 内部管理 capability_registry / invoker / artifact_registry / harness
  - `hi_agent/config/builder.py`
    - `build_capability_registry()` 变 facade
    - **关键**：`llm_gateway` 构造必须先于 capability plane，消除 `build_capability_registry() → build_llm_gateway()` 循环
- 测试：
  - `tests/unit/test_capability_plane_builder.py`
  - `tests/integration/test_no_circular_build.py`
- 验收：
  - [ ] 循环依赖消除（构造顺序：llm → capability_plane → harness）
  - [ ] Characterization 全绿
- 工作量：3 天

### HI-W8-003：抽 `GateCoordinator`

- Owner：Runtime Owner
- Reviewer：Arch Reviewer
- 目标：Gate 状态管理独立（360 LOC）
- 文件变更：
  - `hi_agent/execution/gate_coordinator.py`（新）
    - `register_gate`, `resume`, `continue_from_gate`, `continue_from_gate_graph`, `_check_human_gate_triggers`
    - 独立管理 `_gate_pending` / `_registered_gates`
    - 持 `RunExecutor` 或 session 的**只读引用** + 回调接口
  - `hi_agent/runner.py` 相应方法变 facade，保持签名不变
- 测试：
  - `tests/unit/test_gate_coordinator.py`
  - 原有 test_runner_api.py 中 gate 测试保持通过
- 验收：
  - [ ] Characterization 全绿（特别是 gate_pending → resume → completed 路径）
  - [ ] 15-20 个引用 `executor._registered_gates` 的测试按专家指引迁移到 `executor.gate_coordinator.registered_gates` 或 public API
- 工作量：3 天

### W8 Exit

- [ ] SystemBuilder 中风险拆分完成 + RunExecutor 进阶
- [ ] Post-construction mutation 消除 7 处（server）

---

## W9 — God Object 深度拆分

### HI-W9-001：抽 `ActionDispatcher`

- Owner：Runtime Owner
- Reviewer：Arch Reviewer
- 目标：Route proposal → harness/capability invocation 独立
- 文件变更：
  - `hi_agent/execution/action_dispatcher.py`（新，~280 LOC 移动）
    - `_invoke_capability`, `_invoke_capability_via_hooks`, `_invoke_via_harness`, `_execute_action_with_retry`, `_parse_invoker_role` 等
  - `hi_agent/runner.py` facade
- 测试：
  - `tests/unit/test_action_dispatcher.py`
- 工作量：2.5 天

### HI-W9-002：抽 `RecoveryCoordinator`

- Owner：Runtime Owner
- Reviewer：Arch Reviewer
- 目标：Failure classification / restart policy / escalation 独立
- 文件变更：
  - `hi_agent/execution/recovery_coordinator.py`（新，~420 LOC 移动）
    - `_handle_stage_failure`, `_trigger_recovery`, `_resolve_recovery_success`, `_resolve_recovery_should_escalate`, `_parse_forced_fail_actions`
  - `hi_agent/runner.py` facade
- 测试：
  - `tests/unit/test_recovery_coordinator.py`
- 工作量：2.5 天
- 依赖：HI-W9-001

### W9 Exit

- [ ] `runner.py` LOC 减少累计 ~1660（从 3443 → ~1800）

---

## W10 — God Object 收尾 + 完整 M4

### HI-W10-001：抽 `StageOrchestrator`

- Owner：Runtime Owner
- Reviewer：Arch Reviewer
- 目标：统一 execute / execute_graph / continue_from_gate_graph 三入口内循环，消除 ~60 LOC 重复
- 文件变更：
  - `hi_agent/execution/stage_orchestrator.py`（新，~430 LOC 移动）
    - `execute`, `execute_graph`, `_execute_stage`, `_execute_remaining`, `_find_start_stage`, `_select_next_stage`
    - 抽出 `_execute_all_stages(traversal_fn)` 共享内循环（专家 §2.1 建议）
  - `hi_agent/runner.py`
    - 3 个入口变 facade，内部委托到 StageOrchestrator
    - LOC 最终降到 ~1500（10 cluster → 4 cluster：facade + SubRun + 少量 legacy）
- 测试：
  - `tests/unit/test_stage_orchestrator.py`
  - Characterization 全绿
- 验收：
  - [ ] 3 入口启动/异常/收尾逻辑重复 ≤ 20 LOC
  - [ ] Characterization byte-identical
- 工作量：3 天

### HI-W10-002：抽 `RuntimeBuilder` + `CognitionBuilder`

- Owner：Arch Reviewer 全程参与
- 目标：SystemBuilder facade 拆分收尾
- 文件变更：
  - `hi_agent/config/runtime_builder.py`（新，~600 LOC 移动，含原 _build_executor_impl 主体）
    - **关键**：消除 `builder.py:1621,1644,1663` 3 处 private mutation
    - `executor._stage_executor._middleware_orchestrator = mw` → 构造参数注入
    - `executor._lifecycle.skill_evolver` → 构造参数注入
    - `executor._telemetry.tracer = Tracer(...)` → 构造参数注入
  - `hi_agent/config/cognition_builder.py`（新，~300 LOC 移动）
    - kernel / LLM / middleware orchestrator
- 测试：
  - `tests/integration/test_no_post_construction_mutation.py` — grep 级测试，断言 runner/executor 私有属性不被外部赋值
  - Characterization 全绿
- 验收：
  - [ ] 3 处 private mutation 消除
  - [ ] `SystemBuilder` LOC 从 2045 → <500（facade only）
  - [ ] M2 Composable Runtime 达成
- 工作量：4 天
- 依赖：全部前置 builder merged

### HI-W10-003：完整 M4 — Permission policy 与 tool risk class

- Owner：Capability Owner
- 目标：Capability effect_class 扩 `dangerous` 枚举；invoke 前 RBAC + risk_class 组合检查
- 文件变更：
  - `hi_agent/capability/adapters/descriptor_factory.py` — effect_class 扩 `dangerous`
  - `hi_agent/capability/invoker.py` — invoke 前查 RoutePolicy：
    - `dangerous` capability → 必须 role in `["approver", "admin"]`
    - 其他按现有逻辑
  - `hi_agent/harness/governance.py` — 借鉴 hermes `DANGEROUS_PATTERNS` 正则（`hermes/tools/approval.py:68-100`）做命令级检测
- 测试：
  - `tests/integration/test_dangerous_capability_requires_approval.py`
- 工作量：2 天

### HI-W10-004：完整 M4 — Output budget enforcement

- Owner：Capability Owner
- 目标：`output_budget_tokens` 真实 enforce（裁剪 + 标记）
- 文件变更：
  - `hi_agent/capability/invoker.py` — 调用后检查输出 token 长度，超预算裁剪并在 result 中标 `_output_truncated: True`
- 测试：
  - `tests/integration/test_output_budget_truncation.py`
- 工作量：1 天

### HI-W10-005：完整 M4 — Audit trail + schema versioning + server restart/backoff

- Owner：Capability Owner
- 目标：MCP + Capability 调用全部进入 audit；MCP server crash 自动 restart with backoff
- 文件变更：
  - `hi_agent/observability/audit.py` — 扩 event types（`capability.invoke` / `capability.deny` / `mcp.tools_call` / `mcp.server_restart`）
  - `hi_agent/mcp/transport.py` — crash 后 restart with exponential backoff（最多 5 次），超限标 unavailable
  - `hi_agent/mcp/schema_registry.py`（新）— 记录 tool schema version，drift 时 warn
- 测试：
  - `tests/integration/test_mcp_crash_restart.py`
  - `tests/integration/test_mcp_schema_drift_warning.py`
  - `tests/integration/test_audit_capability_events.py`
- 工作量：3 天

### W10 Exit

- [ ] M2 Composable Runtime 达成
- [ ] M3 Composable Execution 达成
- [ ] M4 Real Tool Plane 完整达成
- [ ] `runner.py` LOC ~1500（从 3443）
- [ ] `builder.py` LOC <500（从 2045）
- [ ] Post-construction mutation 总计消除 11 处

---

## W11 — 产品化 a: Profile 隔离 + 测试基础设施

### HI-W11-001：`HI_AGENT_HOME` + Profile 目录

- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer
- 目标：多 profile 互不污染
- 文件变更：
  - `hi_agent/profile/manager.py`（新）
    - `get_home() -> Path`（默认 `~/.hi_agent`）
    - `get_profile_dir(profile_id) -> Path`（`<home>/profiles/<id>`）
    - `list_profiles()`, `create_profile(id)`, `activate_profile(id)`
  - `hi_agent/config/stack.py`
    - profile-aware config loading（按 profile_id 读不同 config stack）
  - `hi_agent/cli.py`
    - `--profile <id>` flag pre-parse（类似 hermes `hermes_cli/main.py:83-158`）
    - `hi-agent profile list|create|activate` subcommand
- 迁移：
  - 旧 `.hi_agent/` 使用者 → 自动迁移到 `~/.hi_agent/profiles/default/`
- 测试：
  - `tests/integration/test_profile_isolation.py`
    - `test_two_profiles_have_independent_skills`
    - `test_two_profiles_have_independent_memory`
    - `test_default_profile_backward_compatible`
- 验收：
  - [ ] 两 profile 并行运行无状态交叉
  - [ ] 旧 user data 自动迁移
  - [ ] `hi-agent profile list` 显示所有 profile
- 工作量：3 天

### HI-W11-002：fake servers fixtures 整理

- Owner：QA Owner
- 目标：golden path 三层的基础设施
- 文件变更：
  - `tests/fixtures/fake_llm_http_server.py`（整理已有代码）— 兼容 anthropic/openai API shape
  - `tests/fixtures/fake_kernel_http_server.py`（新）
  - `tests/fixtures/fake_mcp_stdio_server.py`（整理 test_mcp_integration.py 里的 `_MCP_SERVER_SCRIPT`）
  - `tests/fixtures/__init__.py` — 公开 pytest fixtures
- 验收：
  - [ ] 3 个 fixture 可被所有 golden path 测试复用
  - [ ] 文档 `tests/fixtures/README.md`
- 工作量：2 天

### W11 Exit

- [ ] Profile 隔离可用
- [ ] Fake server fixtures 可复用

---

## W12 — 产品化 b: Golden Path 三层 + Release Gate 硬门控

### HI-W12-001：Golden path 三层

- Owner：QA Owner
- Reviewer：Arch Reviewer
- 目标：CI 默认 dev-smoke + local-real；nightly 跑 prod-real
- 文件变更：
  - `tests/golden/dev_smoke/test_dev_smoke_golden.py`（新）— 不依赖外部服务
  - `tests/golden/local_real/test_local_real_golden.py`（新）— 使用 W11 fake servers
  - `tests/golden/prod_real/test_prod_real_golden.py`（新）— 真实 creds（CI 从 secrets 读）
  - `.github/workflows/ci.yml` 或等价 CI 配置
    - PR 触发：dev-smoke + local-real
    - Nightly 触发（cron）：prod-real
    - prod-real 缺 secrets 时 `skipped`，不 fail PR
- 验收：
  - [ ] dev-smoke < 2 分钟
  - [ ] local-real < 5 分钟
  - [ ] prod-real nightly 运行记录可查
- 工作量：3 天

### HI-W12-002：Release gate prod-real 硬门控

- Owner：Server/Ops Owner
- 目标：`/ops/release-gate` 加 `prod_e2e_recent` 硬 gate
- 文件变更：
  - `hi_agent/ops/release_gate.py`
    - 新 gate：`prod_e2e_recent`
    - 规则：nightly 模式查最近 72 小时有 prod-real 通过；release candidate 模式查目标 commit 对应 prod-real 通过
    - `skipped` 状态不再自动 pass（nightly 配 secrets 缺失时 `skipped`；release candidate 时 `skipped` 必须人工 override）
- 测试：
  - `tests/integration/test_release_gate_prod_hard_gate.py`
- 验收：
  - [ ] 72 小时内无 prod-real 通过 → `pass=false`（nightly mode）
  - [ ] release candidate 无目标 commit prod-real → `pass=false`
  - [ ] 人工 override 机制可用且进 audit
- 工作量：2 天

### HI-W12-003：Runbook + Migration guide 定稿

- Owner：Server/Ops Owner + Arch Reviewer
- 目标：`docs/runbook/`、`docs/migration/` 完整化
- 文件变更：
  - `docs/runbook/deploy.md`（新）— 部署步骤
  - `docs/runbook/verify.md`（新）— 部署后验证清单
  - `docs/runbook/rollback.md`（新）— 回滚流程
  - `docs/runbook/incident-mcp-crash.md`（新）— MCP server crash 处置
  - `docs/runbook/incident-evolve-unexpected-mutation.md`（新）
  - `docs/migration/contract-changes-2026-04-17.md`（新，汇总所有合同变更）
  - 更新 `README.md` 添加 runbook 索引
- 工作量：2 天

### HI-W12-004：最终 Sprint Retro + Platform Self-Audit

- Owner：Arch Reviewer
- 目标：声明 M5 达成；产出新一轮 platform self-audit 作为下一个 cycle 的输入
- 文件变更：
  - `docs/platform/platform-self-audit-2026-q3-2026-07-17.md`（可选，按需）
  - `docs/sprints/w12-m5-completion.md`
- 验收：
  - [ ] M5 Operable Platform 达成
  - [ ] 专家"四问"四个问题均机器可答
- 工作量：1 天

### W12 Exit

- [ ] M5 达成
- [ ] Golden path 三层 CI 稳定运行一周
- [ ] Release gate 可阻断部署
- [ ] 完整 runbook + migration guide

---

## 全 Sprint 汇总

| 周 | Sprint | Exit 里程碑 | `runner.py` LOC | `builder.py` LOC | Post-construction mutations |
|---|---|---|---|---|---|
| W0 | 前置 | — | 3443 | 2045 | 11 处 |
| W1 | Runtime Truth MVP | — | 3443 | 2045 | 11 |
| W2 | M1 完整达成 | M1 | 3443 | 2045 | 11 |
| W3 | 运维层起步 | — | 3443 | 2045 | 11 |
| W4 | M4A-a Capability 治理 | — | 3443 | 2060 (+新字段) | 11 |
| W5 | M4A-b MCP 动态发现 | M4A | 3443 | 2060 | 11 |
| W6 | SystemBuilder 低风险拆分 | — | 3443 | ~1400 | 11 |
| W7 | 继续拆分 + RunFinalizer | — | ~2843 | ~1050 | 10 |
| W8 | 中风险拆分 + GateCoordinator | — | ~2483 | ~650 | 3 |
| W9 | 深度拆分 | — | ~1783 | ~650 | 3 |
| W10 | 收尾 + 完整 M4 | M2 + M3 + M4 | ~1500 | <500 | 0 |
| W11 | Profile + fixtures | — | ~1500 | <500 | 0 |
| W12 | Golden path + hard gate | M5 | ~1500 | <500 | 0 |

**核心定量目标**：
- `runner.py` LOC 减少 ≥ 55%（3443 → ~1500）
- `builder.py` LOC 减少 ≥ 75%（2045 → <500）
- Post-construction mutation 全部消除（11 → 0）
- `/ops/release-gate` 可硬阻断部署
- 专家"四问"四问均机器可答

---

## Coverage 提升策略

专家 §3 Q6：放弃 per-package `fail_under` 假设，改为 diff coverage + 单独脚本。

| 周 | 全局 coverage | 核心包 coverage | 新增代码 coverage |
|---|---|---|---|
| W0 baseline | 65 | — | — |
| W4 | 70 | execution 80 / config 80 / capability_plane 80 / server 80（用单独脚本检查，非 pyproject） | 85（diff coverage） |
| W8 | 75 | 同上 | 85 |
| W12 | 80 | 同上 | 90 |

**执行方式**：
- 全局 coverage 用现有 `pytest-cov` 配置
- 核心包 coverage 用 `scripts/check_core_coverage.py`（新，基于 coverage.json 输出）
- 新增代码 coverage 用 `diff-cover` 工具（CI 集成）

---

## 风险登记表（持续维护）

| ID | 风险 | 触发周 | 缓解 | Owner |
|---|---|---|---|---|
| R-001 | P0-1 evolve 默认改变影响现有 CI | W1 | 迁移前扫内部 CI 依赖 + `--enable-evolve` 迁移脚本 | Cognition Owner |
| R-002 | RBAC 接线可能 break 没 token 的集成测试 | W1 | dev 模式默认 bypass；prod 才 enforce | Server/Ops Owner |
| R-003 | Coverage 80 对核心包挑战大 | W4-W12 | 每周检查 trend，不达标单建 ticket 不阻塞主线 | QA Owner |
| R-004 | god-object 拆分回归风险 | W6-W10 | Characterization first；每步独立 PR；facade 可 revert | Arch Reviewer |
| R-005 | profile 迁移破坏旧 user data | W11 | 自动迁移 + dry-run 模式 + 备份 | Server/Ops Owner |
| R-006 | prod-real golden path secrets 管理 | W12 | 使用 GitHub secrets / vault；人工 override 记 audit | QA Owner |
| R-007 | MCP 动态发现可能引入新的 subprocess 泄漏 | W5 | lifecycle owner + stderr tail + 自动 cleanup + timeout | Capability Owner |

---

## 与专家"四问"对齐检查表

每周 Runtime Truth Review 检查：

| 专家"四问" | 机器可答？ | 达成周 | 证据字段 |
|---|---|---|---|
| Q1：真实执行 or fallback？ | | W1 末 MVP / W2 末完整 | `RunResult.execution_provenance.fallback_used` |
| Q2：用了哪个 kernel / LLM / capability / profile？ | | W2 末 | `RunResult.execution_provenance.{kernel_mode, llm_mode, capability_mode}` + `/manifest.active_profile` |
| Q3：失败码 / 阶段 / 证据？ | | W0 已有 | `RunResult.failure_code` / `failed_stage_id` / artifacts |
| Q4：上线证据？ | | W12 末 | `/ops/release-gate.prod_e2e_recent` |

---

**End of W6-W12 plan.**
