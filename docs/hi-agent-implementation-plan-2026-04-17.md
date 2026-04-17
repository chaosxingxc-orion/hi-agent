# hi-agent 大规模工程落地 — 实施计划（下发工程团队）

**日期**：2026-04-17
**版本**：v1.0（可执行）
**状态**：专家评审通过，待团队确认 owner/reviewer 后启动 W1 D1

**上游依据**：
- `docs/hi-agent-large-scale-engineering-improvement-plan-2026-04-17.md`（专家12周原案）
- `docs/hi-agent-large-scale-engineering-improvement-response-review-2026-04-17.md`（专家评审，8条修订已全盘接受）
- `docs/hi-agent-usability-audit-2026-04-17.md`（代码级审计证据）
- `docs/hi-agent-engineering-execution-playbook-2026-04-17.md`（合同锁定版）

**配套文档**：
- `docs/hi-agent-implementation-plan-w2-w5-2026-04-17.md`（W2-W5 ticket 详版）
- `docs/hi-agent-implementation-plan-w6-w12-2026-04-17.md`（W6-W12 ticket 详版）

---

## 0. 团队契约（Ground Rules）

### 0.1 角色

| 角色 | 职责 |
|---|---|
| Runtime Owner | kernel / run lifecycle / scheduler / state / RunExecutor 拆分 |
| Capability Owner | capability / toolset / MCP / permission / harness |
| Cognition Owner | LLM / route / context / memory / knowledge / skill / evolve |
| Server/Ops Owner | HTTP / SSE / readiness / doctor / metrics / release gate |
| QA Owner | golden path / prod E2E / coverage / contract tests / characterization tests |
| Arch Reviewer | 跨边界合同、god-object 拆分准入、公开字段变更签字 |

每个 ticket 必须有 1 Owner + 1 Reviewer + 1 QA Owner 会签。

### 0.2 工作流

1. 每个 ticket 独立 PR
2. 每个 PR 必须含 Layer 1 + Layer 2 测试（Layer 3 按 ticket 要求）
3. PR 描述必须引用 ticket ID（HI-W1-D1 等）
4. 不允许跨 ticket 捆绑变更
5. Arch Reviewer 对以下变更有签字权：
   - 任何 `TaskContract` / `RunResult` / `/manifest` / `/ready` 字段变更
   - 任何 SystemBuilder / RunExecutor 结构拆分
   - 任何 RBAC/SOC 接线
6. 每周五 15:00 跑 Runtime Truth Review（30分钟）：文档、manifest、ready、tests 一致性检查

### 0.3 硬红线（违反即退回）

| 红线 | 原因 |
|---|---|
| 不允许在 hi-agent 内部子系统上用 Mock | P3 Production Integrity |
| 不允许 `except: pass` 或 silent fallback | CLAUDE.md Rule 5 |
| 不允许在 PR 中同时"移动代码"和"修改副作用顺序" | 专家 §6.4 |
| 不允许 handler 里散写 `if user.role == ...` | 专家 §6.3 |
| 不允许对外合同字段先发临时 enum 再迁移 | 专家 §6.2 |
| 不允许未完成 characterization test 就拆 god-object | 专家 §6.4 |

---

## 1. 锁定的对外合同（所有 ticket 必须遵守）

### 1.1 `ExecutionProvenance` 合同

```python
# hi_agent/contracts/execution_provenance.py
CONTRACT_VERSION = "2026-04-17"

@dataclass(frozen=True)
class ExecutionProvenance:
    contract_version: str
    runtime_mode: Literal["dev-smoke", "local-real", "prod-real"]
    llm_mode: Literal["heuristic", "real", "disabled", "unknown"]
    kernel_mode: Literal["local-fsm", "http", "unknown"]
    capability_mode: Literal["sample", "profile", "mcp", "external", "mixed", "unknown"]
    mcp_transport: Literal["not_wired", "stdio", "sse", "http"]
    fallback_used: bool
    fallback_reasons: list[str]
    evidence: dict[str, int]  # heuristic_stage_count, real_capability_count, mcp_tool_call_count
```

W1 填充最小集合：`contract_version` + `runtime_mode` + `mcp_transport` + `fallback_used` + `fallback_reasons` + `evidence.heuristic_stage_count`。其余 W1 可填 `"unknown"`。
Shape 不得再变；CONTRACT_VERSION 只能向前叠加。

### 1.2 `evolve_mode` 合同

```python
# hi_agent/config/trace_config.py
evolve_mode: Literal["auto", "on", "off"] = "auto"
```

Resolution：

| evolve_mode | runtime_mode | effective_enabled | source |
|---|---|---|---|
| `on` | any | True | `explicit_on` |
| `off` | any | False | `explicit_off` |
| `auto` | `dev-smoke` | True | `auto_dev_on` |
| `auto` | `local-real` | False | `auto_prod_off` |
| `auto` | `prod-real` | False | `auto_prod_off` |

**外部暴露**：
- `/readiness.evolve_enabled` + `/readiness.evolve_source` + `/readiness.evolve_mode_config`
- `/manifest.evolve_policy = {"mode": str, "effective": bool, "source": str}`
- `doctor` 输出一行："Evolve is ON in prod-real due to explicit_on" 作为 warning
- `explicit_on` 时 emit `audit.evolve.explicit_on` 事件（一次/run）

**兼容**：旧 `evolve_enabled: bool` 字段保留为 property，读旧配置时打 deprecation warning 并映射：`True→"on"` / `False→"off"`。

### 1.3 `/manifest.capabilities` additive 合同

```json
{
  "capabilities": ["trace.route", "trace.act"],
  "capability_views": [
    {
      "name": "trace.act",
      "status": "available" | "unavailable" | "disabled" | "not_wired",
      "toolset_id": "trace-default",
      "required_env": ["HI_AGENT_LLM_KEY"],
      "effect_class": "read_only" | "idempotent_write" | "irreversible_write" | "unknown_effect",
      "output_budget_tokens": 4096,
      "availability_reason": ""
    }
  ],
  "capability_contract_version": "2026-04-17"
}
```

`capabilities: list[str]` 保留 ≥ 4 周后才考虑 deprecation 公告，公告后再 1 版本周期才可能删除。

### 1.4 `RoutePolicy` 合同

```python
# hi_agent/auth/operation_policy.py
@dataclass(frozen=True)
class RoutePolicy:
    operation_name: str
    required_roles: list[str]
    require_soc_separation: bool
    dev_bypass: bool = True
    audit_event: str = ""

OPERATION_POLICIES: dict[str, RoutePolicy] = {
    "skill.promote":     RoutePolicy("skill.promote",      ["approver", "admin"], True,  audit_event="skill.promote"),
    "skill.evolve":      RoutePolicy("skill.evolve",       ["approver", "admin"], True,  audit_event="skill.evolve"),
    "memory.consolidate":RoutePolicy("memory.consolidate", ["approver", "admin"], False, audit_event="memory.consolidate"),
}
```

Role 矩阵：`submitter` / `approver` / `auditor` / `admin`（底层）
兼容映射（延后做）：`viewer→auditor` / `operator→submitter` / `admin→approver+admin`
dev-smoke 下 `dev_bypass=True` → 允许无 token 但 emit `audit.auth.bypass`
prod-real 下 deny 返回 typed error：`{"error": "unauthorized", "operation": "skill.promote", "required_roles": [...], "reason": "missing_role"}`

**不允许**：
- handler 里直接 `if user.role == ...`
- `POST /runs` 接入 RBAC（除非触发 high-risk approval profile，后续评估）

### 1.5 `runtime_mode` 解析合同

```python
# hi_agent/server/runtime_mode_resolver.py
def resolve_runtime_mode(env: str, readiness: dict) -> Literal["dev-smoke", "local-real", "prod-real"]:
    if env == "prod":
        return "prod-real"
    # env == "dev" or anything else
    if readiness.get("llm_mode") == "real" and readiness.get("kernel_mode") == "http":
        return "local-real"
    return "dev-smoke"
```

所有三方（`/manifest`、`/ready`、`RunResult.execution_provenance`）必须用同一 resolver 输出，不得各自计算。

---

## 2. W0-W1 实施计划（详版 ticket spec）

### W0（前置）

**HI-W0-001：初始化 sprint 追踪表**
- Owner：Arch Reviewer
- 动作：创建 `docs/sprints/w1-runtime-truth-mvp.md` 追踪 5 个 ticket 的 Owner / Reviewer / PR link / 状态
- 工作量：0.5 天
- 依赖：无

### W1 D1 — 基线冻结（全团队先停手）

**HI-W1-D1-001：采集运行时基线样本**
- Owner：QA Owner
- Reviewer：Arch Reviewer
- 目标：在任何代码改动前固化一份可比较的运行时基线，所有后续 PR 必须对照此基线证明无回归
- 产出：
  - `docs/platform/current-runtime-baseline-2026-04-17.md`
- 采集命令（全部在 worktree 根目录下运行）：
  1. `python -m pytest -q 2>&1 | tee /tmp/baseline_pytest.txt` — 全量 pytest 输出
  2. `python -m ruff check . 2>&1 | tee /tmp/baseline_ruff.txt`
  3. `python -m pytest --cov=hi_agent --cov-report=term 2>&1 | tee /tmp/baseline_coverage.txt`
  4. 启 dev server `python -m hi_agent serve --port 8080` 后：
     - `curl -s localhost:8080/ready | jq . > /tmp/baseline_ready.json`
     - `curl -s localhost:8080/manifest | jq . > /tmp/baseline_manifest.json`
     - `curl -s localhost:8080/mcp/status | jq . > /tmp/baseline_mcp_status.json`
     - `curl -s localhost:8080/health | jq . > /tmp/baseline_health.json`
     - `curl -sX POST localhost:8080/runs -H 'Content-Type: application/json' -d '{"goal":"baseline smoke"}' | jq . > /tmp/baseline_runs_post.json`
  5. prod prerequisites 缺失行为：`HI_AGENT_ENV=prod python -m hi_agent readiness --local 2>&1 | tee /tmp/baseline_prod_missing.txt`（应 fail，记录完整错误 shape）
- 基线文档 schema：每个样本段含 `{command, env_vars, timestamp, output_summary (≤500 chars), skip_reasons}`
- 验收：
  - [ ] 文档 ≥ 7 个样本段
  - [ ] 每个样本段可复跑（命令 + 环境变量齐全）
  - [ ] pytest 全绿 baseline（如有失败必须在文档中显式列出、不得隐瞒）
  - [ ] Commit：`docs: freeze runtime baseline 2026-04-17`
- 工作量：1 天
- 硬阻断：**未完成此 ticket，团队其他人不得开始 D2-D5 工作**

---

### W1 D2 — Evolve Gate（三态 policy）

**HI-W1-D2-001：引入 evolve_mode 三态 + policy resolver**
- Owner：Cognition Owner
- Reviewer：Arch Reviewer
- QA：QA Owner
- 目标：Evolve 默认不在生产路径 mutate skills；dev 保留研发体验；显式开启进入 audit
- 文件变更：
  - `hi_agent/config/trace_config.py`
    - 删除 `evolve_enabled: bool = True`
    - 新增 `evolve_mode: Literal["auto", "on", "off"] = "auto"`
    - 新增 property `evolve_enabled`（read-only，返回 resolved effective，打 deprecation warning）
  - `hi_agent/config/evolve_policy.py`（新）
    - `resolve_evolve_effective(mode: str, runtime_mode: str) -> tuple[bool, str]` 按 §1.2 表
  - `hi_agent/config/builder.py` `_build_executor_impl`
    - 调用 policy resolver
    - readiness snapshot 加 `evolve_enabled` + `evolve_source` + `evolve_mode_config`
  - `hi_agent/runner_lifecycle.py:326-387`
    - 在 `on_run_completed` 调用前检查 `resolved_enabled`，False 时 skip
    - True 且 `source == "explicit_on"` 时 emit audit event
  - `hi_agent/server/app.py`（manifest handler）
    - 加 `"evolve_policy": {"mode": ..., "effective": ..., "source": ...}`
  - `hi_agent/cli.py`
    - 加 `--enable-evolve` / `--disable-evolve`（互斥）
    - 解析 `HI_AGENT_EVOLVE_MODE` 环境变量
  - `hi_agent/observability/audit.py`（如不存在则新建）
    - `emit(event_name: str, payload: dict)` 写 `.hi_agent/audit/events.jsonl`
  - `docs/migration/evolve-mode-2026-04-17.md`（新）— 迁移说明：旧 config 的 `evolve_enabled` 如何映射
  - `README.md`、`ARCHITECTURE.md`、`CLAUDE.md` Module Index 同步
- 测试：
  - `tests/unit/test_evolve_policy_resolution.py`
    - 9 种组合（3 mode × 3 runtime_mode）穷举
  - `tests/unit/test_trace_config_evolve_compat.py`
    - 旧 `evolve_enabled=True` 读成 `mode="on"`
    - 旧 `evolve_enabled=False` 读成 `mode="off"`
    - deprecation warning 被触发
  - `tests/integration/test_runner_evolve_gated.py`
    - `test_default_config_dev_triggers_evolve`（兼容旧行为）
    - `test_default_config_prod_skips_evolve`
    - `test_explicit_on_prod_emits_audit`
    - `test_cli_flag_enables_evolve`
    - `test_env_var_enables_evolve`
- 验收：
  - [ ] `python -m pytest tests/unit/test_evolve_policy_resolution.py tests/integration/test_runner_evolve_gated.py -v` 全绿
  - [ ] dev 模式 default config run 结束后 `skills/list` 无 version 增加
  - [ ] prod 模式 + `HI_AGENT_EVOLVE_MODE=on` 触发 run → audit log 有 `evolve.explicit_on`
  - [ ] `curl /ready | jq .evolve_source` 返回正确值
  - [ ] baseline pytest 仍全绿（加 deprecation warning 但不 error）
- 工作量：1 天（不含测试）+ 0.5 天测试 = 1.5 天
- 回滚策略：revert 单 commit；policy_resolver 和 evolve_mode 保留为死代码

---

### W1 D3 — Structured Execution Provenance

**HI-W1-D3-001：`RunResult.execution_provenance` 结构化 dict**
- Owner：Runtime Owner
- Reviewer：Arch Reviewer
- QA：QA Owner
- 目标：下游机器区分 dev-smoke vs prod-real success
- 文件变更：
  - `hi_agent/contracts/execution_provenance.py`（新）
    - `ExecutionProvenance` dataclass（见 §1.1）
    - `CONTRACT_VERSION = "2026-04-17"`
    - 方法 `to_dict()` 序列化
    - 方法 `@classmethod build_from_stages(stage_summaries, runtime_context) -> ExecutionProvenance` 聚合
  - `hi_agent/contracts/requests.py:110-162`
    - `RunResult` 加 `execution_provenance: ExecutionProvenance | None = None`
    - `to_dict()` 输出 `{"execution_provenance": prov.to_dict() if prov else None}`
  - `hi_agent/server/runtime_mode_resolver.py`（新）
    - `resolve_runtime_mode(env, readiness) -> str` 按 §1.5 合同
  - `hi_agent/runner.py:1845-2070` `_finalize_run` 末尾
    - 调用 `ExecutionProvenance.build_from_stages(...)` 聚合
    - 设置到 `run_result.execution_provenance`
  - `tests/integration/test_prod_e2e.py:90-106`
    - 断言升级：`assert prov["fallback_used"] is False`、`assert prov["contract_version"] == CONTRACT_VERSION`
    - 移除 `:heuristic:` 字符串扫描的旧断言
- 测试：
  - `tests/unit/test_execution_provenance.py`
    - dataclass 序列化
    - `build_from_stages` 对各种 stage_summary 组合的聚合正确
    - `fallback_reasons` 去重 + 排序
    - `evidence.heuristic_stage_count` 准确
  - `tests/integration/test_runner_provenance_propagation.py`
    - `test_dev_fallback_run_has_fallback_used_true`
    - `test_dev_fallback_run_has_heuristic_stage_count_positive`
    - `test_contract_version_stable`
    - `test_provenance_dict_shape_matches_contract`（断言键集合等于预定义集合）
  - `tests/integration/test_runs_http_provenance.py`（Layer 3）
    - POST /runs + GET /runs/{id} 响应 JSON 含 `execution_provenance` dict
- W1 允许的 unknown 字段：`llm_mode` / `kernel_mode` / `capability_mode`（这三个在 W2 填）
- 验收：
  - [ ] 专家"四问" Q1 机器可答
  - [ ] dev fallback run → `execution_provenance.fallback_used == True`
  - [ ] prod real run → `execution_provenance.fallback_used == False`
  - [ ] Shape 测试锁死合同
  - [ ] 现有 E2E 测试全绿（additive 字段）
- 工作量：1 天（实现）+ 0.5 天测试 = 1.5 天
- 依赖：HI-W1-D2-001 merged

**HI-W1-D3-002：基线对照验证**
- Owner：QA Owner
- 动作：D3 PR merge 后，重跑 HI-W1-D1-001 所有采集命令，diff baseline 文档，确认：
  - 样本 JSON 中 `execution_provenance` 为**新增**字段
  - 旧字段 byte-identical
- 工作量：0.5 天

---

### W1 D4 — Manifest Truthfulness

**HI-W1-D4-001：`/manifest` 诚实 + vocabulary 对齐**
- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer
- QA：QA Owner
- 目标：`/manifest.runtime_mode` 反映真实 env；与 `/ready` 同名字段取值一致；snapshot 测试防漂移
- 文件变更：
  - `hi_agent/server/app.py:415` — 替换硬编码：
    ```python
    manifest["runtime_mode"] = resolve_runtime_mode(env, readiness_snapshot)
    manifest["environment"] = env
    manifest["execution_mode"] = readiness_snapshot.get("execution_mode", "local")
    manifest["kernel_mode"] = readiness_snapshot.get("kernel_mode", "local-fsm")
    manifest["llm_mode"] = readiness_snapshot.get("llm_mode", "unknown")
    manifest["provenance_contract_version"] = CONTRACT_VERSION
    manifest["evolve_policy"] = {
        "mode": evolve_mode_config,
        "effective": evolve_enabled,
        "source": evolve_source,
    }
    ```
- 测试：
  - `tests/integration/test_manifest_truthfulness.py`
    - `test_manifest_runtime_mode_reflects_env_dev`
    - `test_manifest_runtime_mode_reflects_env_prod`
    - `test_manifest_ready_vocabulary_aligned`（两端同名字段值相等）
  - `tests/integration/test_manifest_snapshot.py`
    - 固化 2 个场景的 manifest JSON shape（去掉 time/run_id 等易变字段）
    - dev-smoke + no creds
    - prod-real + fake creds set
- 验收：
  - [ ] 专家"四问" Q2 可通过 manifest + ready 组合回答
  - [ ] snapshot 测试通过；后续任何 manifest 字段改动必须更新 snapshot（阻止漂移）
  - [ ] `HI_AGENT_ENV=dev` + 无 real LLM → `/manifest.runtime_mode == "dev-smoke"`
  - [ ] `HI_AGENT_ENV=prod` + real creds → `/manifest.runtime_mode == "prod-real"`
- 工作量：0.5 天 + 0.5 天测试 = 1 天
- 依赖：HI-W1-D3-001 merged（需要 CONTRACT_VERSION）

---

### W1 D5 — RBAC/SOC operation-driven 最小接线

**HI-W1-D5-001：operation policy 表 + `require_operation` helper**
- Owner：Server/Ops Owner
- Reviewer：Arch Reviewer + Security reviewer（如有）
- QA：QA Owner
- 目标：治理模块从"存在"变"接线"，仅保护 mutation 路由
- 文件变更：
  - `hi_agent/auth/operation_policy.py`（新）— `RoutePolicy` + `OPERATION_POLICIES` 表 + `require_operation(name)` decorator
  - `hi_agent/auth/authorization_context.py`（新）— `AuthorizationContext(role, token, runtime_mode, submitter, approver)` 从 request 构建
  - `hi_agent/auth/rbac_enforcer.py` — 若 API 不匹配新 policy 签名则适配（**不改语义**）
  - `hi_agent/auth/soc_guard.py` — 同上
  - `hi_agent/server/app.py` — 3 条 mutation route 加 `@require_operation(...)`：
    - `handle_skill_promote` → `"skill.promote"`
    - `handle_skills_evolve` → `"skill.evolve"`
    - `handle_memory_consolidate` → `"memory.consolidate"`
  - `hi_agent/observability/audit.py` — 加 `emit_auth_deny(ctx)` 和 `emit_auth_bypass(ctx)`
- 测试：
  - `tests/unit/test_operation_policy.py`
    - `test_policy_table_exhaustive`
    - `test_require_operation_decorator_wires_policy`
  - `tests/integration/test_auth_wiring.py`
    - `test_prod_promote_without_token_returns_403`
    - `test_prod_promote_with_auditor_role_returns_403`
    - `test_prod_promote_with_approver_role_returns_200`
    - `test_dev_promote_without_token_succeeds_but_logs_bypass`
    - `test_soc_separation_same_submitter_approver_rejected_prod`
    - `test_post_runs_still_works_without_auth_in_dev`（确认未动 /runs）
    - `test_post_runs_still_works_without_auth_in_prod`（确认 /runs 未被意外保护）
- 验收：
  - [ ] 3 个 mutation route 在 prod 模式下被保护
  - [ ] dev 模式下旧集成测试不 break
  - [ ] `grep -r "rbac_enforcer" hi_agent/server/` 至少有 1 处间接通过 operation_policy
  - [ ] audit log 可见 `auth.deny` / `auth.bypass`
  - [ ] typed error shape 固定：`{"error": "unauthorized", "operation": str, "required_roles": list[str], "reason": str}`
- 工作量：2 天（含测试）
- 依赖：HI-W1-D4-001 merged

---

### W1 总体验收（Sprint Retro）

- Owner：Arch Reviewer
- 动作：
  1. 重跑 HI-W1-D1-001 所有采集命令，diff baseline 文档
  2. 检查 5 个 ticket 的 DoD checklist 全部 `[x]`
  3. `python -m pytest -q` 全绿
  4. `python -m ruff check .` 无新增 warning
  5. Coverage ≥ baseline
  6. 声明："Runtime Truth MVP achieved"（**不声明 M1 完整达成**）
  7. 更新 `docs/sprints/w1-runtime-truth-mvp.md` 标记完成
  8. 公告下游：见 §4 合同变更公告模板
- 工作量：0.5 天

---

## 3. W2-W12 Roadmap（摘要，详版见配套文档）

| 周 | Sprint 主题 | 关键交付 | 达成里程碑 |
|---|---|---|---|
| W2 | M1 完整达成 | stage / capability / action 三级 provenance + snapshot 测试固化 | M1 Runtime Truth |
| W3 | 运维层起步 | `hi-agent doctor` CLI + `GET /doctor` + `GET /ops/release-gate` v1 | - |
| W4 | M4A-a Capability 最小治理 | Descriptor 扩字段 + `probe_availability` + `/manifest.capability_views` + RouteEngine 过滤 | - |
| W5 | M4A-b MCP 动态发现 | `tools/list` + stderr tail + health degradation + merge 策略 | M4A Minimum Governed Tool Plane |
| W6 | SystemBuilder 低风险拆分 | ReadinessProbe + SkillBuilder + MemoryBuilder | - |
| W7 | 继续拆分 + RunExecutor 起步 | KnowledgeBuilder + RetrievalBuilder + RunFinalizer | - |
| W8 | SystemBuilder 中风险 + RunExecutor 继续 | ServerBuilder + CapabilityPlaneBuilder + GateCoordinator | - |
| W9 | God Object 深度拆分 | ActionDispatcher + RecoveryCoordinator | - |
| W10 | God Object 收尾 + 完整 M4 | StageOrchestrator + RuntimeBuilder + CognitionBuilder + 完整 Capability 治理（permission/output budget/artifact/audit/schema versioning/restart-backoff/profile-scoped state/enterprise allowlist） | M2 Composable Runtime + M3 Composable Execution + M4 Real Tool Plane |
| W11 | 产品化 a | Profile/HI_AGENT_HOME 隔离 + fake server fixtures 整理 | - |
| W12 | 产品化 b | Golden path 三层 + `/ops/release-gate` prod 硬门控 + runbook + migration guide | M5 Operable Platform |

详见：
- `docs/hi-agent-implementation-plan-w2-w5-2026-04-17.md`
- `docs/hi-agent-implementation-plan-w6-w12-2026-04-17.md`

---

## 4. 下游合同变更公告模板

每次对外合同变更由 Arch Reviewer 发给下游集成方（Research Intelligence App 团队等），模板：

```
[hi-agent Contract Change Notice]
Date: 2026-04-17
Sprint: W1 Runtime Truth MVP
Changes:
1. RunResult.execution_provenance (new optional field) — additive, no break
   - Dict shape, see contract: contract_version="2026-04-17"
   - Keys: runtime_mode, llm_mode, kernel_mode, capability_mode, mcp_transport, fallback_used, fallback_reasons, evidence
2. /manifest.runtime_mode (changed value source) — POTENTIALLY BREAKING
   - Old: hardcoded "platform"
   - New: "dev-smoke" | "local-real" | "prod-real"
   - ACTION REQUIRED: check integration code for hardcoded "platform" expectations
3. /manifest.evolve_policy (new nested field) — additive
4. /manifest.capability_views (NOT YET; coming W4-W5) — additive; capabilities: list[str] retained
5. evolve_enabled default changed from True to False-effective in prod-real — BEHAVIOR CHANGE
   - New config: evolve_mode: "auto" | "on" | "off" (default "auto")
   - prod-real + auto → effective=false
   - ACTION REQUIRED (if depending on evolve mutations in prod): set evolve_mode="on"
6. POST /skills/{id}/promote, POST /skills/evolve, POST /memory/consolidate now require auth in prod-real
   - Role required: approver or admin
   - SOC separation applies to skill.promote and skill.evolve
   - ACTION REQUIRED: update integration to send role token or use admin credentials

Impact Assessment Deadline: [date]
Rollback Plan: All changes independently revertable; see PR list.
```

---

## 5. Sprint 追踪模板

`docs/sprints/w1-runtime-truth-mvp.md`：

```markdown
# W1 Sprint — Runtime Truth MVP

**Dates**: 2026-04-18 ~ 2026-04-24
**Goal**: Baseline freeze + Evolve Gate + Structured Provenance + Manifest Truthfulness + RBAC/SOC minimal wiring

## Tickets

| ID | Title | Owner | Reviewer | QA | Status | PR | Merged |
|---|---|---|---|---|---|---|---|
| HI-W1-D1-001 | Freeze runtime baseline | QA | Arch | - | TODO | - | - |
| HI-W1-D2-001 | Evolve tri-state policy | Cognition | Arch | QA | TODO | - | - |
| HI-W1-D3-001 | Structured execution provenance | Runtime | Arch | QA | TODO | - | - |
| HI-W1-D3-002 | Baseline diff verification | QA | - | - | TODO | - | - |
| HI-W1-D4-001 | Manifest truthfulness + snapshot | Server/Ops | Arch | QA | TODO | - | - |
| HI-W1-D5-001 | RBAC/SOC operation-driven wiring | Server/Ops | Arch + Sec | QA | TODO | - | - |

## Exit criteria
- [ ] All tickets merged
- [ ] Baseline diff documented
- [ ] pytest全绿 / ruff clean / coverage ≥ baseline
- [ ] Runtime Truth Review 会议记录
- [ ] Contract change notice 发给下游
```

---

## 6. 进度追踪与变更控制

- 每周 tickets 状态每日更新
- 任何 ticket 超期 > 1 天必须在 Runtime Truth Review 汇报原因
- 任何 §1 合同变更必须回到本文件修订并重新走 Arch Reviewer 签字
- 任何 §0.3 红线触发必须立即停手、召集 Arch Reviewer 讨论

---

**End of main implementation plan.**

下一步：产出 W2-W5 和 W6-W12 配套 ticket 详版。
