# hi-agent 实施计划 W2-W5（Ticket 详版）

**父文档**：`docs/hi-agent-implementation-plan-2026-04-17.md`
**关联**：执行前必先读主文档 §0-§1（团队契约 + 锁定合同）

---

## W2 — M1 完整达成

**Sprint 目标**：扩展 provenance 到 stage-level / capability-level / action-level；锁定 snapshot；关闭 W1 遗留的 `"unknown"` 字段。

**前置**：W1 全部 ticket merged + Runtime Truth Review 通过

### HI-W2-001：Stage-level provenance

- Owner：Runtime Owner
- Reviewer：Arch Reviewer
- QA：QA Owner
- 目标：每个 stage 在 `StageSummary` 里带自己的 provenance，run-level 从 stage-level 聚合
- 文件变更：
  - `hi_agent/contracts/execution_provenance.py` — 新增 `StageProvenance` dataclass：
    ```python
    @dataclass(frozen=True)
    class StageProvenance:
        stage_id: str
        llm_mode: Literal["heuristic", "real", "disabled", "unknown"]
        capability_mode: Literal["sample", "profile", "mcp", "external", "unknown"]
        fallback_used: bool
        fallback_reasons: list[str]
        duration_ms: int
    ```
  - `hi_agent/runner.py` `_execute_stage` — 结束时组装 `StageProvenance`，挂到 `stage_summary["provenance"]`
  - `hi_agent/stage_executor.py`（如存在）— 同上，具体位置由 Owner 确定
  - `ExecutionProvenance.build_from_stages` — 改为基于 `StageProvenance` 聚合：
    - `llm_mode` = 若所有 stage 均 `real` → `"real"`，均 `heuristic` → `"heuristic"`，否则 `"mixed"`
    - `capability_mode` 同上
    - 其余字段保持既有逻辑
- 测试：
  - `tests/unit/test_stage_provenance.py`
  - `tests/integration/test_run_provenance_aggregation.py`
    - `test_all_heuristic_stages_yields_run_heuristic`
    - `test_mixed_stages_yields_mixed`
    - `test_all_real_stages_yields_real`
  - `tests/integration/test_prod_e2e.py` — 断言每个 stage 有 `provenance` 字段
- 验收：
  - [ ] `StageSummary` 输出 `provenance` 子 dict
  - [ ] `run.execution_provenance.llm_mode` 不再是 `"unknown"`（真实聚合）
  - [ ] `run.execution_provenance.capability_mode` 不再是 `"unknown"`
  - [ ] Snapshot 测试更新并通过
- 工作量：2 天
- 依赖：HI-W1-D3-001

### HI-W2-002：Capability/Action-level provenance

- Owner：Capability Owner
- Reviewer：Arch Reviewer
- 目标：每次 capability 调用带 provenance，聚合到 stage
- 文件变更：
  - `hi_agent/capability/invoker.py` `invoke()` — 返回结果 dict 带 `_provenance`：
    ```python
    result["_provenance"] = {
        "mode": "sample" | "profile" | "mcp" | "external",
        "capability_name": name,
        "mcp_server_id": ... if mcp,
        "duration_ms": ...,
    }
    ```
  - `hi_agent/stage_executor.py` — 消费 `_provenance` 聚合到 `StageProvenance`
  - `hi_agent/capability/defaults.py:145` — 保留 `_heuristic` 同时增加 `_provenance.mode="sample"`
- 测试：
  - `tests/unit/test_capability_provenance.py`
  - `tests/integration/test_stage_aggregates_capability_provenance.py`
- 验收：
  - [ ] capability invoke 结果带 `_provenance`
  - [ ] stage_summary 正确聚合
  - [ ] 回归 test_mcp_integration.py 全绿（MCP capability mode 正确标记）
- 工作量：2 天

### HI-W2-003：Kernel mode 真实聚合

- Owner：Runtime Owner
- 目标：`ExecutionProvenance.kernel_mode` 反映真实执行所用 kernel
- 文件变更：
  - `hi_agent/runtime_adapter/` — adapter 暴露 `mode: Literal["local-fsm", "http"]` 属性
  - `hi_agent/runner.py` `_finalize_run` — 从 adapter 读 mode 写入 provenance
- 测试：
  - `tests/integration/test_kernel_mode_provenance.py`
- 验收：
  - [ ] `run.execution_provenance.kernel_mode` 不再 `"unknown"`
- 工作量：0.5 天

### HI-W2-004：Snapshot golden tests 固化

- Owner：QA Owner
- Reviewer：Arch Reviewer
- 目标：固化 `/manifest`、`/ready`、`RunResult` 的 shape，任何未来字段改动必须更新 snapshot
- 文件变更：
  - `tests/snapshots/manifest_dev_smoke.json`（新）
  - `tests/snapshots/manifest_prod_real.json`（新）
  - `tests/snapshots/ready_dev_smoke.json`（新）
  - `tests/snapshots/ready_prod_real.json`（新）
  - `tests/snapshots/run_result_dev_fallback.json`（新）
  - `tests/snapshots/run_result_prod_real.json`（新）
  - `tests/integration/test_contract_snapshots.py` — 使用 pytest-snapshot 或纯 diff
- 验收：
  - [ ] 6 个 snapshot 文件固化
  - [ ] 测试 framework 能检出字段增删
  - [ ] CI 在 snapshot 变化时明确 fail 并提示如何更新
- 工作量：1 天

### W2 Exit

- [ ] M1 Runtime Truth 完整达成声明
- [ ] Contract change notice 发给下游（若有 stage/capability provenance 字段被外部消费）
- [ ] 更新 `docs/sprints/w2-m1-completion.md`

---

## W3 — 运维层起步（Doctor + Release Gate v1）

### HI-W3-001：`hi-agent doctor` CLI + `GET /doctor`

- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer
- 目标：非核心开发者可自诊断
- 文件变更：
  - `hi_agent/ops/diagnostics.py`（新）— 纯函数 `build_doctor_report(builder) -> DoctorReport`
  - `hi_agent/ops/doctor_report.py`（新）— `DoctorReport` dataclass：
    ```python
    @dataclass
    class DoctorIssue:
        subsystem: str
        code: str
        severity: Literal["blocking", "warning", "info"]
        message: str
        fix: str
        verify: str  # 命令

    @dataclass
    class DoctorReport:
        status: Literal["ready", "degraded", "error"]
        blocking: list[DoctorIssue]
        warnings: list[DoctorIssue]
        info: list[DoctorIssue]
        next_steps: list[str]
    ```
  - `hi_agent/cli/doctor.py`（新）— 格式化 CLI 输出（human + `--json`）
  - `hi_agent/server/ops_routes.py`（新）— `/doctor` handler 返回 `DoctorReport.to_dict()`
  - `hi_agent/cli.py` — 注册 `doctor` subcommand
  - `hi_agent/server/app.py` — 注册 `/doctor` route
- 诊断维度（MVP 覆盖）：
  - LLM credentials (prod 硬检)
  - Kernel reachable (prod HTTP endpoint)
  - Capability registry 启动 + 至少有 fallback handler
  - MCP server 健康（若配置）
  - Skill loader 能读 SKILL.md
  - Memory / knowledge 可写目录
  - Profile 解析
  - Evolve policy 当前 effective
- 测试：
  - `tests/unit/test_diagnostics.py` — 各种 mock state 下 report 正确
  - `tests/integration/test_doctor_cli.py` — CLI exit code
  - `tests/integration/test_doctor_http.py` — HTTP 响应 shape
- 验收：
  - [ ] 缺 LLM key 的 prod：doctor 给出 "set ANTHROPIC_API_KEY or OPENAI_API_KEY" + verify 命令
  - [ ] 缺 kernel URL 的 prod：doctor 给出 "set HI_AGENT_KERNEL_URL"
  - [ ] MCP 配错：doctor 给 server_id + stderr 摘要
  - [ ] `hi-agent doctor` 返回 exit 0（ready）/ 1（degraded or error）
  - [ ] `curl /doctor` 返回结构化 JSON
  - [ ] `--json` 与 HTTP JSON 格式一致
- 工作量：3 天

### HI-W3-002：`GET /ops/release-gate` v1

- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer
- 目标：单端点给 CI/CD 判断
- 文件变更：
  - `hi_agent/ops/release_gate.py`（新）
  - `hi_agent/server/ops_routes.py` — 挂 `/ops/release-gate`
- 输出：
  ```json
  {
    "pass": true | false,
    "gates": [
      {"name": "readiness", "status": "pass", "evidence": "ready"},
      {"name": "doctor", "status": "pass", "evidence": "no blocking issues"},
      {"name": "config_validation", "status": "pass", "evidence": "..."},
      {"name": "current_runtime_mode", "status": "info", "evidence": "prod-real"},
      {"name": "known_prerequisites", "status": "pass", "evidence": "..."},
      {"name": "prod_e2e_recent", "status": "skipped", "evidence": "no nightly yet"}
    ],
    "pass_gates": 4,
    "skipped_gates": 1,
    "failed_gates": 0,
    "last_checked_at": "..."
  }
  ```
- W3 v1 明确：`prod_e2e_recent` 标 `skipped` 不阻断；W12 改为强制
- 测试：
  - `tests/integration/test_release_gate_v1.py`
- 验收：
  - [ ] 全绿时 `pass=true`
  - [ ] 任一 blocking gate fail 时 `pass=false`
  - [ ] `prod_e2e_recent` 在 W3 不 block deployment
- 工作量：2 天

### W3 Exit

- [ ] `hi-agent doctor` / `/doctor` / `/ops/release-gate` 可用
- [ ] 更新 ARCHITECTURE.md Ops Layer 章节
- [ ] 更新 `docs/sprints/w3-operable-basics.md`

---

## W4 — M4A-a: Capability 最小治理

### HI-W4-001：CapabilityDescriptor 扩字段

- Owner：Capability Owner
- Reviewer：Arch Reviewer
- 目标：Descriptor 承载治理元数据，不 break 现有 API
- 文件变更：
  - `hi_agent/capability/adapters/descriptor_factory.py:10-30`
    - 新增字段：
      ```python
      toolset_id: str = "default"
      required_env: dict[str, str] = field(default_factory=dict)  # {"ANTHROPIC_API_KEY": "LLM credential"}
      output_budget_tokens: int = 0  # 0 = unlimited
      availability_probe: Callable[[], tuple[bool, str]] | None = None
      ```
    - `CapabilityDescriptorFactory.build_descriptor()` 支持从 YAML / tool_info 填新字段
  - `hi_agent/capability/registry.py`
    - 新方法 `probe_availability(name: str) -> tuple[bool, str]`：
      1. 检查 `required_env` 全部在 `os.environ`
      2. 调用 `availability_probe()` 若定义
      3. 返回 `(True, "")` 或 `(False, reason)`
  - 配套：default capabilities 的 descriptor 用 factory 推断补齐
- 测试：
  - `tests/unit/test_capability_descriptor_extended.py`
  - `tests/unit/test_capability_probe_availability.py`
- 验收：
  - [ ] Descriptor 5 新字段可读可写
  - [ ] `probe_availability` 对 required_env 缺失返回 `(False, reason)`
  - [ ] 旧测试全绿（默认值保持向后兼容）
- 工作量：2 天

### HI-W4-002：`/manifest.capability_views` 新增

- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer
- 目标：Manifest 暴露结构化 capability 状态，保留旧 `capabilities: list[str]`
- 文件变更：
  - `hi_agent/server/app.py:366-376`
    ```python
    manifest["capability_views"] = [
        {
            "name": name,
            "status": status,  # "available" | "unavailable" | "disabled" | "not_wired"
            "toolset_id": desc.toolset_id,
            "required_env": list(desc.required_env.keys()),
            "effect_class": desc.effect_class,
            "output_budget_tokens": desc.output_budget_tokens,
            "availability_reason": reason,
        }
        for name, desc, status, reason in registry.list_with_views()
    ]
    manifest["capability_contract_version"] = "2026-04-17"
    # 保留
    manifest["capabilities"] = registry.list_names()
    ```
  - `hi_agent/capability/registry.py` — 新方法 `list_with_views()`
- 测试：
  - `tests/integration/test_manifest_capability_views.py`
  - Snapshot 更新（W2 D4 snapshot + capability_views 字段）
- 验收：
  - [ ] 两个字段并存
  - [ ] `capability_contract_version` 正确
  - [ ] 无 breaking change
- 工作量：1 天

### HI-W4-003：RouteEngine 过滤 + Invoker 前置检查

- Owner：Cognition Owner（RouteEngine 归 cognition）
- Reviewer：Arch Reviewer
- 目标：不可用能力不被 propose，不可被 invoke
- 文件变更：
  - `hi_agent/route_engine/base.py` 或各 engine — `propose()` 返回前 filter：
    ```python
    available_proposals = [
        p for p in proposals
        if capability_registry.probe_availability(p.action_kind)[0]
    ]
    ```
  - `hi_agent/capability/invoker.py:95-108` — 在 `registry.get(name)` 前置检查：
    ```python
    ok, reason = registry.probe_availability(name)
    if not ok:
        raise CapabilityUnavailableError(name, reason)
    ```
- 测试：
  - `tests/integration/test_route_engine_filters_unavailable.py`
  - `tests/integration/test_invoker_rejects_unavailable.py`
- 验收：
  - [ ] `required_env` 缺失的 capability 不在 route 选项里
  - [ ] 直接 invoke 抛 `CapabilityUnavailableError`（typed error）
  - [ ] 旧 flow 不 break（因为默认 descriptor 都 available）
- 工作量：2 天

### W4 Exit

- [ ] M4A-a 达成
- [ ] 更新 ARCHITECTURE.md Capability Plane 章节
- [ ] 发 capability_views 字段新增通知给下游

---

## W5 — M4A-b: MCP 动态发现 + Health Degradation

### HI-W5-001：`tools/list` 动态发现

- Owner：Capability Owner
- Reviewer：Arch Reviewer
- 目标：MCP server 的工具动态发现，不再依赖 plugin.json 预声明
- 文件变更：
  - `hi_agent/mcp/transport.py`
    - 新方法 `StdioMCPTransport.list_tools(server_id: str, timeout: float = 10.0) -> list[dict]`
    - 发送 `{"method": "tools/list", "params": {}}`，解析 response `{"tools": [{"name": ..., "description": ..., "inputSchema": ...}]}`
    - 异常：timeout / server crash / invalid schema 抛 typed error
  - `hi_agent/mcp/binding.py:96-106` — `bind_all()` 改造：
    1. Health check pass
    2. 调用 `transport.list_tools(server_id)`
    3. Merge 策略（下述 HI-W5-002）
    4. 用最终 tool set 注册到 `CapabilityRegistry`
- 测试（**专家 §5.3 硬要求 6 场景**）：
  - `tests/test_mcp_integration.py` 新增：
    - `test_mi09_tools_list_returns_tools`
    - `test_mi10_tools_list_empty`
    - `test_mi11_tools_list_invalid_schema`
    - `test_mi12_tools_list_timeout`
    - `test_mi13_tools_list_server_crash_during_list`
    - `test_mi14_tools_list_conflict_with_manifest_preclaim`（见 HI-W5-002）
- 验收：
  - [ ] 6 场景全通过
  - [ ] fake MCP server 支持返回 tools/list
  - [ ] Timeout 不阻塞其他 server 的 binding
- 工作量：3 天

### HI-W5-002：Merge 策略

- Owner：Capability Owner
- 目标：动态发现为准，manifest 预声明作为 hint
- 规则：
  1. 动态发现成功 → 使用动态结果
  2. 动态发现失败（timeout/crash/invalid）→ 使用 manifest 预声明（degraded 状态）
  3. 动态成功但与 manifest 冲突（名字有差异）→ 使用动态结果；manifest 独有的 tool 标 warning（"declared but not found in tools/list"）
  4. Server capability 降级 → 对应 tools 标 `unavailable`
- 文件变更：
  - `hi_agent/mcp/binding.py` — 加 `_merge_tools(preclaimed, discovered) -> (final_tools, warnings)`
  - `hi_agent/mcp/health.py` — `degraded` 状态
- 测试：
  - `test_mi14_tools_list_conflict_with_manifest_preclaim`
  - `test_mi15_server_degraded_tools_marked_unavailable`
- 验收：
  - [ ] Merge 策略 6 场景覆盖
  - [ ] warning 进入 doctor 报告
- 工作量：1 天

### HI-W5-003：stderr tail + health degradation

- Owner：Capability Owner
- 目标：MCP 子进程 stderr 被稳定消费、裁剪、暴露到 health
- 文件变更：
  - `hi_agent/mcp/transport.py`
    - 独立线程 `_stderr_reader` 消费 stderr，写入 ring buffer（默认 1024 行）
    - 方法 `get_stderr_tail(server_id: str, n: int = 20) -> list[str]`
    - subprocess 退出时触发 cleanup，stderr ring 保留 N 秒供 doctor 抓取
  - `hi_agent/mcp/health.py`
    - 扩展 `health_status` 语义：`healthy` / `degraded` / `unhealthy`
    - `degraded`：能调用但 stderr 有错误关键词或 tools/list 失败
    - `unhealthy`：subprocess crash 或 initialize 失败
  - `hi_agent/server/app.py` `/mcp/status` — 增加 per-server `stderr_tail: list[str]`
- 测试：
  - `test_mi16_stderr_captured_on_crash`
  - `test_mi17_stderr_tail_in_health_report`
  - `test_mi18_degraded_server_reported_correctly`
- 验收：
  - [ ] 模拟 MCP server 打印到 stderr → doctor 报告可见
  - [ ] Server crash → health 变 unhealthy
  - [ ] tools/list 失败但 server 存活 → health 变 degraded
- 工作量：2 天

### HI-W5-004：Release gate 加 MCP gate

- Owner：Server/Ops Owner
- 目标：任何配置但 unhealthy 的 MCP server 进入 release-gate warning
- 文件变更：
  - `hi_agent/ops/release_gate.py` — 加 gate `mcp_health`
- 工作量：0.5 天

### W5 Exit

- [ ] M4A Minimum Governed Tool Plane 达成
- [ ] `/mcp/status` 暴露 stderr_tail
- [ ] 更新 ARCHITECTURE.md MCP 章节
- [ ] 发 capability_views + MCP 治理公告

---

## W2-W5 汇总验收

| 里程碑 | 完成周 | Exit 条件 |
|---|---|---|
| M1 Runtime Truth | W2 末 | stage/capability/action 三级 provenance + snapshot 固化 |
| M4A Minimum Governed Tool Plane | W5 末 | Descriptor 治理 + capability_views + MCP tools/list + health degradation |

完整 M4（permission policy、output budget 实际 enforce、artifact integration、audit trail、schema versioning、restart-backoff、profile-scoped state、enterprise allowlist）放 W10。

**下一阶段**：见 `docs/hi-agent-implementation-plan-w6-w12-2026-04-17.md`

---

**End of W2-W5 plan.**
