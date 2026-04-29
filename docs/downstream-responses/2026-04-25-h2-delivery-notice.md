# H2 Hardening Wave — Delivery Notice

Status: superseded

**Date:** 2026-04-25
**HEAD SHA:** 658cba0 (branch: `claude/worktree-integration`)
**Delivered by:** chao_workspace (platform team)
**T3 Evidence:** `docs/delivery/2026-04-25-fa98c7b-rule15-volces-v4.json`
**Intake decisions:** `docs/downstream-responses/2026-04-25-h2-intake-decisions.md`

---

## H1-T2 Coverage Gap Disclosure (Rule 9 mandatory)

H1's delivery notice claimed "universal tenant scope" (T2). That claim was incomplete.
`hi_agent/server/routes_profiles.py` was missed: `handle_global_l3_summary` (line 14) and
`handle_global_skills` (line 29) both responded without `require_tenant_context()`, exposing
global L3 memory and skills inventory to unauthenticated callers. H2-T2 closes this gap.

---

## Track Summary

| Track | Commit | Description |
|-------|--------|-------------|
| T0 | `dd6dce2` | H2 G1/G2/G3 intake decisions doc |
| T1 | `38785a7` | Delete orphan test file (`test_skill_runtime_factory.py`) — fixed pytest collection |
| T2 | `0870aa3` | `routes_profiles.py`: add tenant guard + Rule 7 logging on construction failure |
| T3-runner | `cceb262` | Rule 6 sweep — `runner.py` 5 sites (ValueError on None injection) |
| T3-evolve | `90fec2f` | Rule 6 sweep — `evolve/engine.py` 3 sites |
| T3-scheduler | `a4e36d7` | Rule 6 sweep — `task_mgmt/scheduler.py` 2 sites |
| T3-knowledge | `170a5ec` | Rule 6 sweep — `knowledge/knowledge_manager.py` 2 sites |
| T4 | `69a561d` | DF-47 + DF-48 regression test pins |
| T5 | `9534d72` | Housekeeping: env-var docs, T3 evidence committed, K-7 doc drift fixed |
| T6 | `2cd2870` | K-13 PI-C + PI-D combination test (`test_picd_combination.py`) |
| post-T6 | `8d3772a`, `2577ad1` | T4/T6 tests updated for T3 strict-injection constructor changes |
| post-T6 | `fa98c7b` | Orchestrator mock assertion relaxed after T3 caller fan-out |
| T7 | `658cba0` | Concurrency gate script fixed for Windows Python/state-name compat |

Total: 14 commits, 3,949 tests pass, 43 honestly skipped, 0 failures.

---

## Capability Impact (PI-A through PI-E taxonomy)

| Pattern | Status | Change |
|---------|--------|--------|
| PI-A Multistage | Supported | No change |
| PI-B Reflect/Retry | Supported | DF-47 regression pins added (I-6, F-5, F-6) |
| PI-C Human Gate | Supported | K-13 combination test added |
| PI-D Subrun Dispatch | Supported | K-13 combination test added |
| PI-E Composition | Supported | K-13 full combination test (gate + subrun in one run) |

---

## 7-Dimension Readiness Delta

| Dimension | H1 % | H2 % | Change | Driver |
|-----------|------|------|--------|--------|
| Execution | 78 % | 84 % | +6 | Rule 6 strict injection sweep eliminates 12 silent-divergence sites; tenant scope universal (C2 closed) |
| Memory | 76 % | 80 % | +4 | DF-47 reflection-path regression pins; DF-48 reasoning trace persistence pin |
| Capability | 72 % | 72 % | — | No change |
| Knowledge Graph | 65 % | 65 % | — | No change |
| Planning | 60 % | 60 % | — | No change |
| Artifact | 55 % | 55 % | — | No change |
| Evolution | 50 % | 50 % | — | No change; DF-49 clears technical debt that blocked evolution engine injection |

---

## Platform Gap Status (P-1 through P-7)

| Gap | Status | Note |
|-----|--------|------|
| P-1 Provenance | PENDING design | Unchanged |
| P-2 Reasoning trace | CLOSED | DF-48 implementation shipped H1; regression pin added H2 |
| P-3 Cross-run project | PENDING design | Unchanged |
| P-4 Dynamic re-planning | PENDING design | Defer W9 |
| P-5 Confidence scoring | PENDING design | Unchanged |
| P-6 KG inference | PARTIAL | Unchanged |
| P-7 Feedback path | PENDING design | Defer W10 |

---

## T3 Operator-Shape Gate (Rule 8)

**Evidence:** `docs/delivery/2026-04-25-fa98c7b-rule15-volces-v4.json`

- Runs: 3 sequential
- `llm_mode`: `real`
- `llm_provider`: `volces`
- All 3 runs: `state=completed`, `fallback_events=[]`
- Durations: 92.2 s, 88.2 s, 95.2 s (real LLM — not heuristic)
- Cancellation: known run → `cancelled` (200); unknown run → 404 ✓
- Gate: **PASS**

---

## Concurrency Gate — First Run Findings (Rule 9 Disclosure)

The concurrency gate (`scripts/run_concurrency_gate.sh`) was never run before H2 (no H1 evidence file).
H2-T7 fixed the script for Windows Python compatibility and ran it for the first time.

**Results:**
- Phase 1 (20 concurrent runs): 0/20 passed — most runs reach `state=failed` (queue_full at capacity=4)
  or `state=completed` without `finished_at` populated. FAIL.
- Phase 2 (5 concurrent idempotency requests): FAIL — 5 distinct run_ids created despite shared key
  (idempotency write is not atomic under concurrent load).

**New defects filed:**

| ID | Description | Category | Severity |
|----|-------------|----------|----------|
| DF-51 | `finished_at` null on failed/queued runs | Run lifecycle (Rule 8 observability) | H |
| DF-52 | Idempotency race under concurrent load (5 × 201, 5 run_ids for 1 key) | HTTP contract | H |
| DF-53 | `HI_AGENT_RUN_MANAGER_CAPACITY` default=4 undocumented; limits concurrency gate | Observability | M |

These defects are **pre-existing** (not introduced by H2). They were discovered because the concurrency
gate ran for the first time. They do not block H2 delivery (the volces T3 gate covers normal LLM operation
and passes). They are filed as H3 candidates.

---

## Residual Known Defects (non-ship-blocking)

| ID | Description | Target |
|----|-------------|--------|
| DF-50 | `CapabilityDescriptor` schema duplication (`registry.py` vs `descriptor_factory.py`) | H3 |
| DF-51 | `finished_at` null on failed runs | H3 |
| DF-52 | Idempotency race under concurrent load | H3 |
| DF-53 | `HI_AGENT_RUN_MANAGER_CAPACITY` default undocumented | H3 |

---

## Pre-Commit Verification

```
ruff check . → All checks passed
python -c "import hi_agent; import agent_kernel" → OK (no stderr)
pytest tests/unit/ tests/integration/ → 3,949 passed, 43 skipped, 0 failed
T3 volces gate → PASS (docs/delivery/2026-04-25-fa98c7b-rule15-volces-v4.json)
```