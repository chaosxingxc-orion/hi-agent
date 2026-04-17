# W1 Sprint — Runtime Truth MVP

**Dates**: 2026-04-18 ~ 2026-04-24
**Goal**: Baseline freeze + Evolve Gate + Structured Provenance + Manifest Truthfulness + RBAC/SOC minimal wiring

**父文档**：`docs/hi-agent-implementation-plan-2026-04-17.md`

**Sprint Owner**: Arch Reviewer
**Daily checkpoint**: 每日 18:00 更新状态表

---

## 0. Sprint 退出条件（Exit Criteria）

必须全部满足才能声明 "Runtime Truth MVP achieved"（**不声明 M1 完整达成**）：

- [ ] 6 个 ticket 全部 merged（状态列全 ✅ Merged）
- [ ] 基线对照验证：重跑 HI-W1-D1-001 采集命令，仅预期字段有 diff
- [ ] `python -m pytest -q` 全绿
- [ ] `python -m ruff check .` 无新增 warning
- [ ] Coverage ≥ baseline
- [ ] 所有 PR 通过 Arch Reviewer 签字
- [ ] Runtime Truth Review 会议完成（周五 15:00）
- [ ] Contract change notice 发给下游（见父文档 §4 模板）
- [ ] 更新 CLAUDE.md Module Index（新增：evolve policy / execution provenance / operation policy）

---

## 1. Tickets

| ID | Title | Owner | Reviewer | QA | 估算 | 依赖 | Status | PR | Merged At |
|---|---|---|---|---|---|---|---|---|---|
| HI-W0-001 | Initialize sprint tracker | Arch | - | - | 0.5d | - | ⬜ TODO | - | - |
| HI-W1-D1-001 | Freeze runtime baseline | QA | Arch | - | 1d | - | ⬜ TODO | - | - |
| HI-W1-D2-001 | Evolve tri-state policy | Cognition | Arch | QA | 1.5d | D1 | ⬜ TODO | - | - |
| HI-W1-D3-001 | Structured execution provenance | Runtime | Arch | QA | 1.5d | D2 | ⬜ TODO | - | - |
| HI-W1-D3-002 | Baseline diff verification | QA | Arch | - | 0.5d | D3-001 | ⬜ TODO | - | - |
| HI-W1-D4-001 | Manifest truthfulness + snapshot | Server/Ops | Arch | QA | 1d | D3-001 | ⬜ TODO | - | - |
| HI-W1-D5-001 | RBAC/SOC operation-driven wiring | Server/Ops | Arch + Sec | QA | 2d | D4 | ⬜ TODO | - | - |

**状态图例**：⬜ TODO / 🟨 In Progress / 🟦 In Review / ✅ Merged / ❌ Blocked

**总估算**：8 天（5 日历天内并行完成）

---

## 2. Daily Schedule

### Day 1 (Mon 2026-04-18) — 基线冻结（硬阻断）

**全员不得开始其他工作，直到 HI-W1-D1-001 merged。**

- HI-W1-D1-001 全员协作：
  - QA 主导采集
  - Arch Reviewer 当日 review
  - 目标：EOD 前 merge

**交付**：
- [ ] `docs/platform/current-runtime-baseline-2026-04-17.md`
- [ ] 7 个样本段
- [ ] Commit: `docs: freeze runtime baseline 2026-04-17`

### Day 2 (Tue 2026-04-19) — Evolve Gate

- HI-W1-D2-001：Cognition Owner 开工
- Arch Reviewer 并行准备 §1.2 合同最终稿
- QA 准备 D3 characterization

**交付**：
- [ ] 9 种组合（mode × runtime_mode）测试覆盖
- [ ] `/ready.evolve_source` 可见
- [ ] PR ready for review EOD

### Day 3 (Wed 2026-04-20) — Provenance + D2 收尾

- HI-W1-D3-001：Runtime Owner 开工（依赖 D2 merged）
- D2 早 merge → D3 早开工
- QA 准备 D3 Layer 3 测试

**交付**：
- [ ] `ExecutionProvenance` 合同 shape 固化
- [ ] `RunResult.execution_provenance` 可序列化
- [ ] PR ready for review EOD

### Day 4 (Thu 2026-04-21) — Manifest + D3 收尾

- HI-W1-D3-002：QA 做基线 diff 验证
- HI-W1-D4-001：Server/Ops Owner 开工
- 并行：D5 准备（operation_policy 表定稿）

**交付**：
- [ ] Manifest snapshot 固化 2 场景
- [ ] `/manifest` 与 `/ready` vocabulary 对齐
- [ ] PR ready for review EOD

### Day 5 (Fri 2026-04-22) — RBAC/SOC + Sprint Retro

- HI-W1-D5-001：Server/Ops Owner 开工
- 15:00 Runtime Truth Review（30 分钟）
  - Arch Reviewer 主持
  - 检查 Sprint Exit Criteria
  - 签字或列阻塞项
- EOD 前：所有 PR merged OR 列出 blocker

**交付**：
- [ ] 3 条 mutation route 在 prod 受保护
- [ ] dev bypass 可观察
- [ ] Sprint Retro 文档：`docs/sprints/w1-runtime-truth-mvp-retro.md`
- [ ] Contract change notice 发出

---

## 3. 每日 Standup 模板（15 分钟）

每日 09:30 standup，每个 owner 回答：

1. 昨天完成了什么（PR link）
2. 今天要做什么
3. 阻塞项（立即升级给 Arch Reviewer）

更新本文件的 Status 列。

---

## 4. 风险应对

| 风险 | 触发条件 | 应对 | 决策人 |
|---|---|---|---|
| D1 基线采集超时 | EOD Day 1 未 merge | 全员停手直到完成；delay 整个 sprint | Arch Reviewer |
| D2 evolve 迁移影响现有 CI | 跑全量 pytest 失败 | 在 PR 里加 compat 兼容层（旧 `evolve_enabled=True` → `mode="on"`）；不改默认值逻辑 | Cognition Owner |
| D3 provenance 聚合改副作用顺序 | characterization 失败 | 退回：只在 `_finalize_run` 末尾加聚合，不动前序副作用 | Runtime Owner |
| D4 snapshot 测试过于严格导致 flakiness | 连续 2 个 PR snapshot 失败 | 检查字段是否含时间戳；必要时加 `exclude_keys` | QA Owner |
| D5 RBAC 意外 break dev 集成测试 | 任一集成测试 fail | 确保 `dev_bypass=True` 在所有 3 policy 中生效；fail fast | Server/Ops Owner |

---

## 5. Blocker Log

记录阻塞项，供下一日 standup 参考。

| Date | Ticket | Issue | Owner | Resolution | Resolved At |
|---|---|---|---|---|---|
| - | - | - | - | - | - |

---

## 6. Retro Log（Sprint 结束时填）

### 完成了什么

- (待 Sprint 结束填)

### 未达成的

- (待 Sprint 结束填)

### 下 Sprint 改进

- (待 Sprint 结束填)

### 合同变更公告发送记录

- [ ] 下游 Research Intelligence App 团队
- [ ] 其他集成方（按需列出）

---

**End of W1 Sprint tracker.**

Sprint 结束后，本文件迁移到 `docs/sprints/archive/` 并创建 `w2-m1-completion.md`。
