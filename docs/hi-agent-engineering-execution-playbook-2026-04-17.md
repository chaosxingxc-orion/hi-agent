# hi-agent 工程改进 — 执行 Playbook

**日期**：2026-04-17
**用途**：后续每个 session 接续执行时的自用 playbook。不做 RFC 仪式、不做团队协作、不做拟人化开发流程。只记录**我要做什么、改什么文件、如何验证、什么情况停手**。

**上游输入**：
- `docs/hi-agent-large-scale-engineering-improvement-plan-2026-04-17.md`（专家原案）
- `docs/hi-agent-large-scale-engineering-improvement-response-review-2026-04-17.md`（专家评审，**8 条修订全部接受**）
- `docs/hi-agent-usability-audit-2026-04-17.md`（代码级审计证据）
- `docs/hi-agent-large-scale-engineering-improvement-response-2026-04-17.md`（我的响应 v1，已被评审修订）

**状态机**：每完成一项，在本文件里把 `[ ]` 改成 `[x]` 并记录 commit hash。

---

## 0. 锁定合同（不得擅自改动）

这一节是**我的 guard rail**。后续任何 PR 若需要改这些合同，必须回到本文件修订而不是在 PR 里即兴决定。

### 0.1 `execution_provenance` 合同（v1 即结构化 dict）

专家 §1.3 / §3 Q2：不接受单字符串 enum MVP。第一版即结构化：

```python
@dataclass
class ExecutionProvenance:
    contract_version: str  # 固定 "2026-04-17"
    runtime_mode: Literal["dev-smoke", "local-real", "prod-real"]
    llm_mode: Literal["heuristic", "real", "disabled"]
    kernel_mode: Literal["local-fsm", "http"]
    capability_mode: Literal["sample", "profile", "mcp", "external", "mixed"]
    mcp_transport: Literal["not_wired", "stdio", "sse", "http"]
    fallback_used: bool
    fallback_reasons: list[str]  # e.g. ["missing_llm_gateway", "kernel_http_unreachable"]
    evidence: dict[str, int]  # {"heuristic_stage_count": N, "real_capability_count": N, "mcp_tool_call_count": N}
```

**MVP 填充策略**（W1 Day 3）：
- `contract_version` / `runtime_mode` / `fallback_used` / `fallback_reasons` / `evidence.heuristic_stage_count` → **W1 必填**
- `llm_mode` / `kernel_mode` / `capability_mode` / `mcp_transport` → **W1 允许标 `"unknown"`**，W2-W3 逐字段填充
- Shape 不再变、contract_version 只能向前叠加

**对外位置**：
- `RunResult.execution_provenance`
- `/manifest.execution_provenance_contract_version`
- `/ready` 同样字段对齐

### 0.2 `evolve_mode` 合同（三态 policy）

专家 §1.2 / §3 Q1：接受三态。

```python
class TraceConfig:
    evolve_mode: Literal["auto", "on", "off"] = "auto"

# 解析规则（在 SystemBuilder 或 PolicyResolver 里实现）：
def resolve_evolve_effective(evolve_mode: str, runtime_mode: str) -> tuple[bool, str]:
    """Return (effective_enabled, resolution_source)"""
    if evolve_mode == "on":
        return (True, "explicit_on")
    if evolve_mode == "off":
        return (False, "explicit_off")
    # auto
    if runtime_mode == "dev-smoke":
        return (True, "auto_dev_on")
    # local-real / prod-real
    return (False, "auto_prod_off")
```

**可观察点**（都要填）：
- `/readiness` → `{"evolve_enabled": bool, "evolve_source": str, "evolve_mode_config": str}`
- `/manifest` → `{"evolve_policy": {"mode": ..., "effective": ..., "source": ...}}`
- `doctor` → warning 行："Evolve is ON in prod-real due to explicit_on; ensure intended"
- Audit event：`evolve.explicit_on` 事件在 profile/env/CLI 显式打开时 emit 一次

**迁移**：现有 `evolve_enabled: bool = True` 删除；兼容层：若 config 中仍有 `evolve_enabled`，打 deprecation warning 并映射（True→"on"、False→"off"）。

### 0.3 `/manifest.capabilities` 合同（additive，不 break）

专家 §5.2：不接受 `list[str]` → `list[dict]` 的 breaking change。采用并列加字段：

```json
{
  "capabilities": ["trace.route", "trace.act", ...],           // 旧字段保留
  "capability_views": [                                         // 新字段
    {
      "name": "trace.act",
      "status": "available" | "unavailable" | "disabled" | "not_wired",
      "toolset_id": "trace-default",
      "required_env": ["HI_AGENT_LLM_KEY"],
      "effect_class": "read_only" | "idempotent_write" | "irreversible_write" | "unknown_effect",
      "output_budget_tokens": 4096,
      "availability_reason": ""  // 非空当 status != "available"
    }
  ],
  "capability_contract_version": "2026-04-17"
}
```

保留 `capabilities: list[str]` 一个完整版本周期（≥ 4 周）。弃用公告在 W5 之后才发。

### 0.4 RBAC/SOC 接线合同（operation-driven）

专家 §1.5 / §3 Q4：不接受 per-handler 散写；不把 SOC 套到普通 `POST /runs`。

**集中化设计**：

```python
# hi_agent/auth/operation_policy.py (新)
@dataclass
class RoutePolicy:
    operation_name: str
    required_roles: list[str]  # 任一命中即通过
    require_soc_separation: bool  # submitter != approver
    dev_bypass: bool = True  # dev-smoke 默认 bypass 但记 audit
    audit_event: str = ""

OPERATION_POLICIES: dict[str, RoutePolicy] = {
    "skill.promote":     RoutePolicy("skill.promote", ["approver", "admin"], True, audit_event="skill.promote"),
    "skill.evolve":      RoutePolicy("skill.evolve",  ["approver", "admin"], True, audit_event="skill.evolve"),
    "memory.consolidate":RoutePolicy("memory.consolidate", ["approver", "admin"], False, audit_event="memory.consolidate"),
    # 暂不加 POST /runs
    # 暂不加 /runs/{id}/resume /runs/{id}/signal（评估后再加）
}

def require_operation(operation_name: str):
    """Decorator / middleware: load RoutePolicy, build AuthorizationContext, enforce, audit."""
    ...
```

**Role 矩阵**（专家 Q4 选 B）：
- 底层：`submitter` / `approver` / `auditor` / `admin`
- 产品层映射（向后兼容，延后做）：`viewer→auditor` / `operator→submitter` / `admin→approver+admin`

**dev 兼容**：dev-smoke 下 `dev_bypass=True` 的路由允许无 token 通过，但 response 里加 `auth_bypass_reason: "dev-smoke"` 并写 audit。prod-real 下 deny 返回 typed error `{"error": "unauthorized", "operation": "...", "required_roles": [...]}`。

### 0.5 `RunFinalizer` 定位（不是"只读"）

正确措辞："finalization 是一个副作用密集的生命周期阶段（memory consolidation / episode build / feedback write / telemetry flush / failure attribution / pending subrun cancellation / artifact assembly），适合被封装为副作用协调器"。

**提取准入**（专家 §2.4）：
1. 先写 characterization test，固定 completed / failed / cancelled 三类 outcome 下的外部行为
2. 再移动代码
3. 移动过程中**不改变副作用顺序**（L0 close → lifecycle finalize → failure attribution → L0→L2→L3 → feedback → duration → RunResult）
4. 移动完成后 `RunExecutor._finalize_run` 是一行 facade
5. 所有现有测试通过后再做语义改进（如果要做）

---

## 1. 执行顺序（修订后）

### W1（Runtime Truth MVP + Baseline，5 天）

**W1 不宣布 M1 完整达成**，只交付 MVP。专家 §4 五日方案：

- [ ] **W1 D1 — 基线冻结**（先于一切代码改动）
- [ ] **W1 D2 — Evolve Gate（三态 policy）**
- [ ] **W1 D3 — Structured Execution Provenance**
- [ ] **W1 D4 — Manifest Truthfulness**
- [ ] **W1 D5 — RBAC/SOC operation-driven 最小接线**

详细步骤见 §2。

### W2-W3（M1 收尾 + 运维层起步）

- [ ] **W2 D1-D2** — Stage-level provenance（`StageSummary.execution_provenance` 子结构）
- [ ] **W2 D3-D4** — Capability/action-level provenance（`CapabilityResult.provenance` 子结构）
- [ ] **W2 D5** — provenance snapshot/golden tests 固化 → **M1 完整达成**
- [ ] **W3 D1-D3** — `hi-agent doctor` CLI + `GET /doctor` HTTP（复用 `builder.readiness()`）
- [ ] **W3 D4-D5** — `GET /ops/release-gate` v1（只聚合 readiness + doctor.blocking + config validation + current runtime mode，prod-real gate 标 `skipped` 直到 W11 nightly 建立）

### W4-W5（M4A：Minimum Governed Tool Plane）

专家 §2.2：M4 名称改为 M4A，范围缩小。

- [ ] **W4 D1-D2** — `CapabilityDescriptor` 扩 `toolset_id / required_env / output_budget_tokens`，`CapabilityRegistry.probe_availability()`
- [ ] **W4 D3** — `/manifest.capability_views` 新增（additive），`capabilities: list[str]` 保留
- [ ] **W4 D4-D5** — `RouteEngine.propose()` 后过滤 unavailable，`CapabilityInvoker.invoke()` 前置 availability 检查
- [ ] **W5 D1-D3** — MCP `tools/list` 动态发现 + merge 策略（动态发现为准，manifest 预声明作为 bootstrap hint，冲突 warn 但不阻塞）
- [ ] **W5 D4-D5** — MCP stderr tail + health degradation（专家 §5.3：必须覆盖空 tools / invalid schema / timeout / stderr 有内容 / crash / 冲突 merge 6 种场景）

完整 M4（permission/output budget/artifact/audit/schema version/restart-backoff/profile-scoped state/enterprise allowlist）保留在 **W8-W10**。

### W6-W7（SystemBuilder 低风险拆分 + RunExecutor 第一步）

**准入条件**（专家 §2.3）：每一步前必先：
1. Characterization test 固定外部 API shape
2. 证明新 builder 不访问其他 builder 私有属性
3. 新 builder 不引入 post-construction mutation
4. 可独立回滚（facade 内部委托，旧方法保留）

- [ ] **W6 D1-D2** — 抽 `ReadinessProbe`（最安全，纯观察面，300 LOC）
- [ ] **W6 D3-D5** — 抽 `SkillBuilder`（200 LOC）+ `MemoryBuilder`（150 LOC）
- [ ] **W7 D1-D3** — 抽 `KnowledgeBuilder`（250 LOC）+ `RetrievalBuilder`（100 LOC，消除 `engine._embedding_fn = ...` post-construction）
- [ ] **W7 D4-D5** — 抽 `RunFinalizer`（600 LOC，characterization first，副作用顺序严格不变）

### W8-W9（SystemBuilder 中风险 + RunExecutor 第二步）

- [ ] **W8 D1-D3** — 抽 `ServerBuilder`（200 LOC，消除 app.py:1816-1831 的 7 处 post-construction assignment）
- [ ] **W8 D4-D5 + W9 D1-D2** — 抽 `CapabilityPlaneBuilder`（400 LOC，打破 LLM-capability 循环依赖）
- [ ] **W9 D3-D4** — 抽 `GateCoordinator`（360 LOC，从 runner.py）
- [ ] **W9 D5** — 抽 `ActionDispatcher`（280 LOC，从 runner.py）

### W10（God Object 收尾 + 完整 M4）

- [ ] **W10 D1-D2** — 抽 `RecoveryCoordinator`（420 LOC，从 runner.py）
- [ ] **W10 D3-D4** — 抽 `StageOrchestrator`（430 LOC，从 runner.py，统一 execute / execute_graph / continue_from_gate_graph 内循环）
- [ ] **W10 D5** — 抽 `RuntimeBuilder` + `CognitionBuilder`（SystemBuilder 拆分收尾）
- [ ] **M3 Composable Execution 达成**
- [ ] **M2 Composable Runtime 达成**

### W11-W12（M5：Operable Platform）

- [ ] **W11 D1-D3** — Profile / `HI_AGENT_HOME` 隔离（`~/.hi_agent/profiles/{profile_id}/`，消除 W6-W10 标注但未动的共享 mutable cache）
- [ ] **W11 D4-D5** — fake servers fixtures（LLM HTTP / kernel HTTP / MCP stdio 已有，合规整理到 `tests/fixtures/`）
- [ ] **W12 D1-D3** — Golden path 三层（dev-smoke / local-real / prod-real）落 CI
- [ ] **W12 D4** — `/ops/release-gate` 补 prod-real 72h 硬门控（nightly 缺 secrets 时 `skipped`，release candidate 时必须通过目标 commit 的 prod-real）
- [ ] **W12 D5** — 最终 runbook + migration guide 定稿
- [ ] **M5 Operable Platform 达成**

---

## 2. W1 每日 playbook（详细步骤）

每日开始前，`cd D:\chao_workspace\hi-agent\.claude\worktrees\distracted-poitras && git status` 确认 clean。

### W1 D1 — 基线冻结

**前置**：无。
**目标**：产出可比较基线文档 `docs/platform/current-runtime-baseline-2026-04-17.md`。没有基线不进入重构。

**步骤**：

1. 建目录：`mkdir -p docs/platform`
2. 采集命令行输出：
   - `python -m pytest -q 2>&1 | tee /tmp/baseline_pytest.txt`
   - `python -m ruff check . 2>&1 | tee /tmp/baseline_ruff.txt`
   - `python -m pytest --cov=hi_agent --cov-report=term 2>&1 | tee /tmp/baseline_coverage.txt`
3. 启动 dev server 采样端点：
   - `python -m hi_agent serve --port 8080 &`（后台）
   - `curl -s localhost:8080/ready | jq . > /tmp/baseline_ready.json`
   - `curl -s localhost:8080/manifest | jq . > /tmp/baseline_manifest.json`
   - `curl -s localhost:8080/mcp/status | jq . > /tmp/baseline_mcp_status.json`
   - `curl -s -X POST localhost:8080/runs -H 'Content-Type: application/json' -d '{"goal":"baseline smoke"}' | jq . > /tmp/baseline_runs_post.json`
   - 停 server
4. 采集 prod prerequisites 缺失行为：
   - `HI_AGENT_ENV=prod python -m hi_agent readiness --local 2>&1 | tee /tmp/baseline_prod_missing.txt`（应 fail，记录完整错误 shape）
5. 写 `docs/platform/current-runtime-baseline-2026-04-17.md`：含每个采样的命令、时间、完整输出摘要、失败/skip 原因
6. `git add docs/platform/ && git commit -m "docs: freeze runtime baseline 2026-04-17"`

**验收**：
- baseline 文档有 ≥ 7 个样例段
- 每个样例可复跑（命令 + 环境变量齐全）
- commit 落盘

---

### W1 D2 — Evolve Gate（三态 policy）

**前置**：W1 D1 baseline merged。
**目标**：`evolve_mode` 三态 + dev/prod 解析 + readiness/manifest/doctor 可观察 + 显式开启 audit。

**文件清单**：
- `hi_agent/config/trace_config.py` — 替换 `evolve_enabled: bool = True` 为 `evolve_mode: Literal["auto", "on", "off"] = "auto"` + 保留 `evolve_enabled` 作为 deprecated compat property（read-only，返回 resolved effective 值）
- `hi_agent/config/evolve_policy.py`（新）— `resolve_evolve_effective(mode, runtime_mode) -> tuple[bool, str]`
- `hi_agent/config/builder.py` — `_build_executor_impl` 里调用 policy resolver；readiness output 加 `{"evolve_enabled", "evolve_source", "evolve_mode_config"}`
- `hi_agent/server/app.py` — `/manifest` 加 `"evolve_policy": {...}`
- `hi_agent/cli.py` — 加 `--enable-evolve` 和 `--disable-evolve` flag（互斥），env `HI_AGENT_EVOLVE_MODE` 支持
- `hi_agent/observability/audit.py`（若不存在则新建）— `emit("evolve.explicit_on", {"source": ...})`
- `docs/migration/evolve-mode-2026-04-17.md`（新）
- 更新 `README.md` + `ARCHITECTURE.md` 声明默认行为
- 更新 `CLAUDE.md` 的"Module Index"条目

**测试文件**：
- `tests/unit/test_evolve_policy_resolution.py`（新）— 覆盖 9 种组合（3 mode × 3 runtime）
- `tests/unit/test_trace_config_evolve_migration.py`（新）— 旧 `evolve_enabled` 字段映射
- `tests/integration/test_runner_evolve_gated.py`（新）
  - `test_default_run_does_not_mutate_skills`（default config + dev → 旧行为）
  - `test_prod_auto_disables_evolve`（runtime=prod-real + mode=auto → 不触发 apply_evolve_changes）
  - `test_prod_explicit_on_emits_audit`（runtime=prod-real + mode=on → 触发 + audit emit）
  - `test_cli_flag_enables_evolve`
  - `test_env_var_enables_evolve`

**验收**：
- `python -m pytest tests/unit/test_evolve_policy_resolution.py tests/integration/test_runner_evolve_gated.py -v` 全绿
- `curl /ready | jq .evolve_source` 返回 `"auto_dev_on"` 或 `"auto_prod_off"`
- `HI_AGENT_EVOLVE_MODE=on python -m hi_agent serve` + POST 触发 run → audit log 有 `evolve.explicit_on` 事件
- 旧测试（使用 `evolve_enabled=True` config 的）仍通过（compat）

**回滚**：`git revert` 单 commit。默认值回 True，policy resolver 保留不引用。

---

### W1 D3 — Structured Execution Provenance

**前置**：W1 D2 merged。
**目标**：`RunResult.execution_provenance` 按 §0.1 合同输出，W1 允许 4 字段标 `unknown`。

**文件清单**：
- `hi_agent/contracts/execution_provenance.py`（新）— `ExecutionProvenance` dataclass + `to_dict()` + `merge_from_stage(stage_summary)` helper + CONTRACT_VERSION 常量
- `hi_agent/contracts/requests.py:110-162` — `RunResult` 加 `execution_provenance: ExecutionProvenance | None = None` + `to_dict()` 序列化
- `hi_agent/runner.py:1845-2070` `_finalize_run` — 末尾聚合：
  ```python
  provenance = ExecutionProvenance(
      contract_version=CONTRACT_VERSION,
      runtime_mode=self._resolve_runtime_mode(),  # 从 HI_AGENT_ENV + has_real_kernel/LLM 推断
      llm_mode="unknown",   # W2 填
      kernel_mode="unknown",  # W2 填
      capability_mode="unknown",  # W2 填
      mcp_transport=self._mcp_registry.transport_status() if self._mcp_registry else "not_wired",
      fallback_used=any(s.get("_heuristic") for s in stage_summaries),
      fallback_reasons=[...],  # 从 stage_summaries 抽
      evidence={"heuristic_stage_count": count_heuristic_stages(stage_summaries), ...},
  )
  run_result.execution_provenance = provenance
  ```
- `tests/integration/test_prod_e2e.py:90-106` — 断言升级：
  ```python
  prov = result["execution_provenance"]
  assert prov is not None
  assert prov["fallback_used"] is False  # prod 不允许 heuristic success
  assert prov["contract_version"] == CONTRACT_VERSION
  ```

**测试文件**：
- `tests/unit/test_execution_provenance.py`（新）— dataclass 序列化、merge_from_stage、fallback_reasons 聚合
- `tests/integration/test_runner_provenance_propagation.py`（新）
  - `test_dev_fallback_run_has_fallback_used_true`
  - `test_dev_fallback_run_has_heuristic_stage_count_nonzero`
  - `test_contract_version_stable`
  - `test_provenance_in_run_result_json`（Layer 3，公共 HTTP）

**验收**：
- 专家"四问" Q1 机器可答：dev fallback run JSON 能通过 `execution_provenance.fallback_used==true` 区分
- `CONTRACT_VERSION == "2026-04-17"` 且在 `/manifest.execution_provenance_contract_version` 输出
- 现有 E2E 测试无 break（新字段 additive）

**回滚**：`RunResult.execution_provenance` 设 None + runner.py 不聚合，字段留着不影响下游。

---

### W1 D4 — Manifest Truthfulness

**前置**：W1 D3 merged。
**目标**：`/manifest.runtime_mode` 不再硬编码 + vocabulary 与 `/ready` 对齐 + snapshot test 防漂移。

**文件清单**：
- `hi_agent/server/app.py:415` — 替换硬编码：
  ```python
  manifest["runtime_mode"] = self._resolve_runtime_mode()  # "dev-smoke" | "local-real" | "prod-real"
  manifest["environment"] = os.environ.get("HI_AGENT_ENV", "dev")
  manifest["execution_mode"] = readiness_snapshot.get("execution_mode", "local")
  manifest["kernel_mode"] = readiness_snapshot.get("kernel_mode", "local-fsm")
  manifest["llm_mode"] = readiness_snapshot.get("llm_mode", "unknown")
  manifest["provenance_contract_version"] = CONTRACT_VERSION
  manifest["evolve_policy"] = {...}  # 来自 W1 D2
  ```
- `hi_agent/server/runtime_mode_resolver.py`（新）— 单独函数，供 manifest / ready / RunExecutor 共用
- `tests/integration/test_manifest_truthfulness.py`（新）
  - `test_manifest_runtime_mode_reflects_env_dev`
  - `test_manifest_runtime_mode_reflects_env_prod`
  - `test_manifest_ready_vocabulary_aligned`（两端同名字段取值相等）
- `tests/integration/test_manifest_snapshot.py`（新）— 固化 dev-smoke 和 prod-real missing prereqs 两个场景下的 manifest JSON shape（不含时间戳/运行 ID 等易变字段）

**验收**：
- `HI_AGENT_ENV=dev` start → `/manifest.runtime_mode == "dev-smoke"`（或根据 LLM/kernel 真实状态，可能 `local-real`）
- `HI_AGENT_ENV=prod` start with real creds → `/manifest.runtime_mode == "prod-real"`
- snapshot test 通过、后续任何 manifest 字段改动必须更新 snapshot（阻止漂移）

**回滚**：单 commit revert，`resolve_runtime_mode` 工具函数保留不引用。

---

### W1 D5 — RBAC/SOC operation-driven 最小接线

**前置**：W1 D4 merged。
**目标**：operation policy 表 + `require_operation` helper + 3 条 mutation route 接入 + dev bypass 可观察 + prod deny typed error。

**文件清单**：
- `hi_agent/auth/operation_policy.py`（新）— §0.4 的 `RoutePolicy` + `OPERATION_POLICIES` 表 + `require_operation` decorator/helper
- `hi_agent/auth/authorization_context.py`（新）— `AuthorizationContext(role, token, runtime_mode, submitter, approver)` 从 request header / env 构建
- `hi_agent/auth/rbac_enforcer.py` — 如果 API 不匹配新 policy 签名则少量适配（不改语义）
- `hi_agent/server/app.py` — 3 条路由加 `@require_operation("skill.promote")` 等：
  - `handle_skill_promote` (app.py 对应行)
  - `handle_skills_evolve`（注意：这是手动触发的 `POST /skills/evolve`，与 W1 D2 的自动 evolve 不冲突）
  - `handle_memory_consolidate`
- `hi_agent/observability/audit.py` — 加 `emit("auth.deny", {...})` 和 `emit("auth.bypass", {...})`

**测试文件**：
- `tests/unit/test_operation_policy.py`（新）— 查表、decorator 语义
- `tests/integration/test_auth_wiring.py`（新）
  - `test_prod_promote_without_token_returns_403`
  - `test_prod_promote_with_auditor_role_returns_403`（auditor 无 promote 权限）
  - `test_prod_promote_with_approver_role_returns_200`
  - `test_dev_promote_without_token_succeeds_but_logs_bypass`
  - `test_soc_separation_same_submitter_approver_rejected_prod`
  - `test_post_runs_still_works_without_auth_in_dev`（确认未动 /runs）

**验收**：
- 3 个 mutation route 受保护
- dev 模式下旧集成测试不 break（bypass 生效）
- `rbac_enforcer.py` + `soc_guard.py` 被 `require_operation` 引用（`grep -r "rbac_enforcer" hi_agent/server/` 应至少有 1 处间接通过 operation_policy）
- audit log 可见 `auth.deny` 和 `auth.bypass` 事件

**回滚**：移除 3 处 decorator；`operation_policy.py` 保留不被引用。

---

### W1 总体验收

- [ ] 5 天全部 commit 落盘
- [ ] `python -m pytest -q` 仍然全绿（baseline 对齐）
- [ ] `python -m ruff check .` 无新增 warning
- [ ] Coverage 不低于 baseline
- [ ] `CLAUDE.md` Module Index 更新（evolve policy / execution provenance / operation policy 新增条目）
- [ ] `docs/platform/current-runtime-baseline-2026-04-17.md` + 本 playbook 的 `[x]` 状态同步

**W1 达成的是"Runtime Truth MVP"，不是完整 M1**（专家 §2.1）。完整 M1 放 W2 末 / W3 末。

---

## 3. 每个 PR 的准入 checklist

这是我在每次 commit / PR 前自查的硬规则，违反即退回。

- [ ] 本次改动**只**触达 playbook 当前 step 列出的文件（Rule 3 Surgical Changes）
- [ ] 如果动结构（拆分 god object），先有 characterization test 落盘（专家 §6.4）
- [ ] 对外合同字段改动：本文件 §0 同步更新
- [ ] 新增字段是 additive（不删旧字段，除非经过一个版本周期 deprecation）
- [ ] Layer 1 + Layer 2 + Layer 3 三层测试至少有 2 层
- [ ] 没有用 Mock 包装 hi-agent 内部子系统（P3 Production Integrity）
- [ ] 没有 `except: pass` 或 silent fallback（CLAUDE.md Rule 5 错误可见性）
- [ ] `git log -1 --stat` 确认文件数合理（surgical）
- [ ] 本 playbook 对应 `[ ]` 改 `[x]` 并记 commit hash

---

## 4. 红线（专家 §6 必须避免的执行误区）

这 4 条是硬停手条件，任何 session 违反立即停。

### 4.1 不把"测试多"当作"生产可信"

MCP 的 8 个集成测试说明 stdio 正向链路存在，**不代表**：
- health degradation 已处理
- unavailable tool 被 route engine 排除
- direct invoke unavailable tool 抛 typed error
- manifest 与 readiness 不矛盾

任何涉及 MCP 生产描述的文档都必须显式列出上述 4 项状态。

### 4.2 不先上临时对外字段再迁移

`execution_provenance` / `/manifest` 字段是**下游依赖**。宁可 W1 填 `"unknown"` 也不发单字符串 enum。本文件 §0.1 / §0.3 合同**不得**临时松动。

### 4.3 不把权限逻辑写散

RBAC/SOC 只能通过 `require_operation(operation_name)` 接入，**不允许**在 handler 里写 `if user.role == ...`。散写即回归。

### 4.4 不一边拆 God Object 一边改业务语义

SystemBuilder / RunExecutor 拆分期间：
1. 先 characterization test
2. 再移动代码
3. 外部行为**不变**
4. 语义修正放到拆分完成后的独立 PR

同一 PR 不得同时出现"移动代码"和"修改副作用顺序"。

---

## 5. Resume mechanism（跨 session 接续）

每次 session 开始执行前：

1. `cd D:\chao_workspace\hi-agent\.claude\worktrees\distracted-poitras`
2. 读本 playbook，找到第一个 `[ ]`，即我要做的 step
3. `git log --oneline -20` 查看最近 commits，确认上次 session 落盘的步骤 hash
4. `git status` 确认 clean（如果有未 commit 改动，先评估是上次未完成还是 drift）
5. 执行当前 step 的"文件清单 + 测试文件 + 验收"
6. 完成后：`[ ] → [x]`，commit hash 写在 step 末尾
7. 如果 step 中途遇到未预期问题：停手，记录到本文件末尾的 `§6 Session Log`，不继续推进

---

## 6. Session Log（跨 session 问题记录）

格式：`[YYYY-MM-DD hh:mm] step_id: 描述 + 决策`

- [2026-04-17 10:38] playbook v1 定稿，锁定 §0 全部合同
- [2026-04-17 10:38] W1 D1-D5 待执行，用户未批准启动

---

## 7. 与上游文档的关系

| 文档 | 作用 |
|---|---|
| `hi-agent-large-scale-engineering-improvement-plan-2026-04-17.md` | 专家原案（12 周 5 阶段路线） |
| `hi-agent-usability-audit-2026-04-17.md` | 审计证据（file:line 引用） |
| `hi-agent-large-scale-engineering-improvement-response-2026-04-17.md` | 我的响应 v1（已被评审修订，保留作历史） |
| `hi-agent-large-scale-engineering-improvement-response-review-2026-04-17.md` | 专家评审（8 条修订 + Q1-Q6 回答） |
| **本文件** | **我的执行 playbook，唯一 authoritative 来源** |

以后任何执行决策以本文件为准；若与 response-v1 冲突以本文件为准（response-v1 已过时）。

---

**End of playbook.**
