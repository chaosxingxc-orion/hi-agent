# Wave 36 S-2 — Postgres Persistence Equivalence Plan

**Date:** 2026-05-07
**Wave:** W36 supplement (binding)
**Reference:** RIA W36 supplement directive §2.2; W34 SQLite-only PASS gap; `docs/perf/concurrency-methodology-v1.md` §7
**Owner:** RO (track lead) + GOV (CI workflow) + TE (evidence + provenance)

> **Last refreshed:** 2026-05-07. HEAD `975b7911`.

---

## 1. Purpose & Position

- Closes the W34 SQLite-only PASS gap recorded in `docs/downstream-responses/2026-05-05-w34-delivery-notice.md:40` — the `test_concurrency_persistence_swap.py::test_sqlite_postgres_equivalence_at_n10_m1` SKIP flips to PASS once `HI_AGENT_TEST_POSTGRES_DSN` is configured in CI.
- Strengthens persistence-backend extensibility (RIA "Lens 4 high concurrency"): Postgres is exercised on the durable-write path so backend swap can be defended on equivalence, not on inspection alone.
- This is **not** a Postgres migration. SQLite remains the default backend in `dev` / `research` / `prod` postures; Postgres is a parallel-run equivalence proof at small N. The architectural contract is "two backends produce the same terminal-state distribution under the same workload," not "Postgres is the new default."
- Aligned with W36 plan-set: complements A3 retention (durable-store hygiene) and S-1 6h Linux soak (persistence under pressure). No scope overlap.

---

## 2. Workload Specification

| Field | Value |
|---|---|
| Workload shape | `N` parallel `POST /v1/runs` from `M` simulated tenants — same harness as `tests/integration/test_concurrency_persistence_swap.py:32-89` |
| Backends compared | SQLite (current default-offline path) vs PostgreSQL (gated by `HI_AGENT_TEST_POSTGRES_DSN`) |
| Required N×M | **N=10 / M=1** — matches W34 baseline (`docs/downstream-responses/2026-05-05-w34-delivery-notice.md:40`, P50=28.0ms / P95=51.8ms / fairness=1.00) |
| Optional N×M | N=100 / M=10 if CI runner stability allows; **NOT required** for W36 closure |
| Equivalence target | Deterministic terminal-state distribution; identical bucket counts under both backends |
| Equivalence window | Per `docs/perf/concurrency-methodology-v1.md` §7 — correctness, not latency. Distributions MUST be exactly equal at the small-N target |
| Runner | GitHub Actions `ubuntu-latest` (4 vCPU / 16 GB / SSD), service-container Postgres |
| Postgres image | `postgres:16-alpine` (LTS-aligned with asyncpg ≥0.30 declared at `pyproject.toml:24`) |
| Provenance target | `measured` — actual run on CI service container, not synthesized JSON |

---

## 3. Backend-Abstraction Audit (per A3 store)

The 8 W36-A3 stores split cleanly into two groups: 4 already have a Postgres parallel implementation behind a Protocol port; 4 are SQLite-coupled with no current abstraction.

| # | Store | Protocol port | SQLite impl | Postgres impl | W36-S-2 disposition |
|---|---|---|---|---|---|
| 1 | `SQLiteEventStore` (agent_server runs/events) | none — concrete class at `hi_agent/server/event_store.py:103` | yes | **none** | **SQLite-coupled** — equivalence test exercises stub backend (`AGENT_SERVER_BACKEND=stub`) which short-circuits durable writes; out-of-scope for W36-S-2. Future wave: extract `EventStorePort`. |
| 2 | `SQLiteRunStore` (agent_server runs) | none — concrete class at `hi_agent/server/run_store.py:133` | yes | **none** | **SQLite-coupled** — same disposition as #1. |
| 3 | `SQLiteGateStore` (management) | none — concrete class at `hi_agent/management/gate_store.py:61` | yes | **none** | **SQLite-coupled** — same disposition. |
| 4 | `SqliteDecisionAuditStore` (route_engine) | none — `InMemoryDecisionAuditStore` + `SqliteDecisionAuditStore` at `hi_agent/route_engine/decision_audit_store.py:14,62` (no Protocol) | yes | **none** | **SQLite-coupled** — out-of-scope. |
| 5 | `SqliteEvidenceStore` (runtime/harness) | `EvidenceStoreProtocol` at `hi_agent/runtime/harness/evidence_store.py:17` (Protocol exists) | yes | **none** | Protocol-abstracted but no Postgres implementation lands in W36; out-of-scope. |
| 6 | `SQLiteKernelRuntimeEventLog` (agent_kernel) | `KernelRuntimeEventLog` at `agent_kernel/kernel/contracts.py` (referenced by `pg_event_log.py:15`); also `EventLogStore` Protocol at `agent_kernel/kernel/persistence/ports.py:20-30` | yes | **`PostgresKernelRuntimeEventLog`** at `agent_kernel/kernel/persistence/pg_event_log.py:15` | **Protocol-abstracted, Postgres ready** — wired via `PostgresColocatedBundle` at `agent_kernel/kernel/persistence/pg_colocated_bundle.py:28`. |
| 7a | `SQLiteDedupeStore` (agent_kernel) | `DedupeStore` Protocol at `agent_kernel/kernel/persistence/ports.py:33-61` | yes | **`PostgresDedupeStore`** at `agent_kernel/kernel/persistence/pg_dedupe_store.py:17` | **Protocol-abstracted, Postgres ready** (bundle:34). |
| 7b | `SQLiteDecisionDeduper` (agent_kernel) | concrete class at `agent_kernel/kernel/persistence/sqlite_decision_deduper.py:21`; `InMemoryDecisionDeduper` is the pluggable alternative | yes | **none** | SQLite-only; not part of `PostgresColocatedBundle`. Out-of-scope for W36-S-2. |
| 8a | `SQLiteRecoveryOutcomeStore` (agent_kernel) | `RecoveryOutcomeStore` Protocol at `agent_kernel/kernel/contracts.py:1230` | yes | **`PostgresRecoveryOutcomeStore`** at `agent_kernel/kernel/persistence/pg_recovery_outcome_store.py:12` | **Protocol-abstracted, Postgres ready** (bundle:46). |
| 8b | `SQLiteTurnIntentLog` (agent_kernel) | `TurnIntentLog` Protocol at `agent_kernel/kernel/contracts.py:1255` | yes | **none** | Protocol exists but no Postgres impl. Out-of-scope for W36-S-2. |

**Aggregate:** 4 stores have an executable Postgres backend behind a Protocol port (kernel event_log, dedupe_store, recovery_outcome, plus the bonus `PostgresCircuitBreakerStore` at `pg_circuit_breaker_store.py`). 4 stores are SQLite-coupled with no current abstraction. The W36-S-2 equivalence target is the kernel persistence path — that is where backend swap is actually possible today and where the W34 test file already gates on the DSN.

**No new Protocol abstraction is extracted in W36-S-2.** The SQLite-coupled agent_server stores (1–4 + 7b + 8b) stay SQLite-only; their abstraction is tracked as W37+ work and recorded in §10 risk registry.

---

## 4. Equivalence Test Shape

### 4.1 Test file

`tests/integration/test_concurrency_persistence_swap.py` already exists (file:1-119) and is the structural target. **Renames or new file:** none — extend the existing file in-place so the W34 acceptance row remains the same artifact.

The existing `test_sqlite_postgres_equivalence_at_n10_m1` (file:113-119) drives the workload via `_run_workload_against_backend("sqlite", ...)` and `_run_workload_against_backend("postgres", ...)` — the helper at file:32-89 currently hard-codes `AGENT_SERVER_BACKEND=stub`. W36-S-2 extends this:

- **(a)** When `backend_marker == "postgres"`, the helper additionally sets `HI_AGENT_KERNEL_PERSISTENCE_BACKEND=postgresql` + `HI_AGENT_KERNEL_PG_DSN=$HI_AGENT_TEST_POSTGRES_DSN` so the wired-up `KernelRuntimeConfig.persistence_backend` (defined at `agent_kernel/runtime/kernel_runtime.py:123-126`) selects the Postgres bundle (`agent_kernel/runtime/kernel_runtime.py:531-545`).
- **(b)** When `backend_marker == "sqlite"`, helper leaves the kernel default in place (in-memory event log under stub backend; W34 baseline).
- The env-mutation try/finally pattern (file:55-63) is preserved so the mutation does not leak into other tests.

### 4.2 Pytest marker

`pytest.mark.integration` (existing, file:21). The new `requires_postgres` marker is implemented as the existing `@pytest.mark.skipif(not os.environ.get("HI_AGENT_TEST_POSTGRES_DSN"), ...)` decorator at file:106-112 — reuse, do not introduce a new marker concept.

### 4.3 Assertions

The existing `assert _terminal_state_distribution(sqlite_states) == _terminal_state_distribution(postgres_states)` (file:117-119) is the equivalence assertion. W36-S-2 adds:

- **Per-store row-count equality** — query SQLite leg row counts (`run_records`, `run_events` for the test's run_ids) and assert the Postgres-leg counts match within the same run-id set. Read `purge_*` baselines via direct connection against `$HI_AGENT_TEST_POSTGRES_DSN`.
- **Per-tenant scoping invariant** — every Postgres-leg row has the test's `X-Tenant-Id` value populated; no row leaks an empty `tenant_id`. Mirrors Rule 12 contract spine.

These two adds are scoped to the gated test (skip when DSN absent), so the default-offline profile is unchanged.

### 4.4 Out-of-scope for W36-S-2

- Latency-distribution comparison (Postgres vs SQLite p95). The methodology says "correctness, not performance" (`docs/perf/concurrency-methodology-v1.md:142-145`). Future wave may add advisory latency comparison.
- N=50 / M=5 / N=100 / M=10 — optional; gated on CI runner stability.

---

## 5. CI Workflow

### 5.1 Workflow location

Add a new dedicated workflow `.github/workflows/postgres-equivalence.yml` rather than extending `main-ci.yml`. Rationale: a Postgres service container per main-ci shard would slow every PR; the equivalence test runs only when relevant files change (the 4 Protocol-abstracted stores + the test file + bootstrap). The workflow trigger is `pull_request` paths-filtered + `schedule` weekly.

### 5.2 Service container shape

```yaml
services:
  postgres:
    image: postgres:16-alpine
    env:
      POSTGRES_USER: hi_agent_test
      POSTGRES_PASSWORD: hi_agent_test
      POSTGRES_DB: hi_agent_equiv
    ports:
      - 5432:5432
    options: >-
      --health-cmd "pg_isready -U hi_agent_test"
      --health-interval 5s
      --health-timeout 3s
      --health-retries 5
```

### 5.3 DSN export

```yaml
env:
  HI_AGENT_TEST_POSTGRES_DSN: postgresql://hi_agent_test:hi_agent_test@localhost:5432/hi_agent_equiv
```

This is **non-secret** by design (test-only DB on a service container; never reaches a real cluster). No GitHub Actions secret is required, which keeps the workflow runnable from forks.

### 5.4 Test invocation

```yaml
- name: Run persistence equivalence
  run: pytest -m integration tests/integration/test_concurrency_persistence_swap.py -v
```

### 5.5 Evidence emission

The CI step writes `docs/verification/<sha>-postgres-equivalence.json` with shape:

```json
{
  "schema": "hi-agent.postgres-equivalence.v1",
  "head_sha": "<short>",
  "provenance": "measured",
  "params": {"N": 10, "M": 1, "backends": ["sqlite", "postgres"]},
  "result": "equal | divergent",
  "sqlite_distribution": {"queued": 10},
  "postgres_distribution": {"queued": 10},
  "wall_clock_seconds": <float>
}
```

The path mirrors the existing `<sha>-concurrency-N{N}M{M}.json` convention (`docs/perf/concurrency-methodology-v1.md:131`). Evidence is committed by the CI job into a release-evidence artifact — not into git directly — and surfaced in the W36 manifest via `scripts/_governance/evidence_loader.py`.

---

## 6. Equivalence Window

**Definition:** Per `docs/perf/concurrency-methodology-v1.md` §7 (file:138-145), persistence equivalence is **correctness, not latency**. The terminal-state distribution under both backends MUST be **exactly equal** at N=10/M=1.

**Why exact equality (not p99 + tolerance):** the W34 baseline `tests/integration/test_concurrency_persistence_swap.py:92-103` already proves the SQLite leg yields a single-bucketed deterministic distribution (`assert len(distribution) == 1`). Two deterministic distributions over the same workload either match or do not; there is no statistical noise to tolerate at this layer.

**Calibration recorded in methodology v1.1** (process change, see §7c):

> The equivalence-window for persistence backend swap is exact distribution equality at N=10/M=1. Any divergence is a hard FAIL — never a tolerance miss. Latency tolerance bands belong to the regression budget (§9 of methodology v1) and are tracked separately.

**W34 baseline reference:** P50=28.0ms / P95=51.8ms / fairness=1.00 at N=10/M=1 (`docs/downstream-responses/2026-05-05-w34-delivery-notice.md:39`); P50=77.5ms / P95=200.4ms at N=50/M=5. These are SQLite-leg numbers; W36-S-2 does not assert against them but records them in the evidence JSON for future regression tracking.

---

## 7. Three-Part Closure (Rule 15)

### (a) Code fix / artifact

- Test extension: `tests/integration/test_concurrency_persistence_swap.py` `_run_workload_against_backend` helper picks up `HI_AGENT_KERNEL_PERSISTENCE_BACKEND` + `HI_AGENT_KERNEL_PG_DSN` when `backend_marker == "postgres"` (commit reference recorded at W36 closure).
- CI workflow: `.github/workflows/postgres-equivalence.yml` (new file).
- Evidence: `docs/verification/<W36-final-sha>-postgres-equivalence.json` with `provenance: measured`.

### (b) Recurrence-prevention check

- New gate `scripts/check_postgres_equivalence_evidence.py` (mirrors `scripts/check_concurrency_evidence.py` shape): asserts `<HEAD>-postgres-equivalence.json` exists at release HEAD with `provenance: measured` and `result: equal`. Wired into `.github/workflows/release-gate.yml` next to `check_concurrency_evidence.py`.
- Plan-validation: `scripts/check_doc_consistency.py` Check 11 (Rule 15) parses W36 closure notice and asserts a `level: verified_at_release_head` row for `W36-S-2`.

### (c) Process change

- `docs/perf/concurrency-methodology-v1.md` revised to **v1.1**. New section §7.1 "Equivalence-window definition" pins exact-equality at N=10/M=1. New section §7.2 names Postgres equivalence as a **permanent quality gate** keyed on `HI_AGENT_TEST_POSTGRES_DSN` presence in CI; absence of the var in CI (i.e. SKIP returning to default-offline) is a release-gate FAIL post-W36.
- W36 delivery-notice template extension records the per-store backend-abstraction inventory from §3 above as a recurring scorecard row ("Protocol-abstracted persistence stores: 4/8") so future waves see the lift target explicitly.

---

## 8. Acceptance Criteria

- [ ] Plan published at `docs/superpowers/plans/2026-05-07-wave-36-postgres-equivalence.md` (this file).
- [ ] `HI_AGENT_TEST_POSTGRES_DSN` configured in CI via `.github/workflows/postgres-equivalence.yml` service container.
- [ ] `tests/integration/test_concurrency_persistence_swap.py::test_sqlite_postgres_equivalence_at_n10_m1` PASS in CI at the W36 release HEAD (no SKIP).
- [ ] Evidence file `docs/verification/<W36-final-sha>-postgres-equivalence.json` carries `provenance: measured` and `result: equal`.
- [ ] `scripts/check_postgres_equivalence_evidence.py` exit 0 at release HEAD; wired into `release-gate.yml`.
- [ ] `docs/perf/concurrency-methodology-v1.md` v1.1 published with §7.1 + §7.2.
- [ ] W36 delivery notice carries §3 backend-abstraction inventory and a three-part closure block for `W36-S-2` with `level: verified_at_release_head`.

---

## 9. Sequencing (≤14 days)

- **Day 1** — Backend-abstraction audit confirmation (this plan §3); decide whether `SQLiteDecisionDeduper` and `SQLiteTurnIntentLog` are added to `PostgresColocatedBundle` in this wave or deferred (default: deferred).
- **Day 2** — Local Postgres dev-loop: docker-compose Postgres + asyncpg ≥0.30 (already in `pyproject.toml:24`); verify `KernelRuntimeConfig(persistence_backend="postgresql", pg_dsn=...)` wires through (`agent_kernel/runtime/kernel_runtime.py:531-545`).
- **Day 3-4** — Extend `_run_workload_against_backend` helper at `tests/integration/test_concurrency_persistence_swap.py:32-89` to consume Postgres env vars when `backend_marker == "postgres"`. Run locally against Docker Postgres. Verify SQLite-leg unchanged.
- **Day 5** — Add per-store row-count + per-tenant scoping assertions (§4.3 adds).
- **Day 6-7** — Author `.github/workflows/postgres-equivalence.yml` with `postgres:16-alpine` service container, paths filter, weekly schedule.
- **Day 8** — Author `scripts/check_postgres_equivalence_evidence.py`; wire into `release-gate.yml`. Mirror `scripts/check_concurrency_evidence.py:1-N` exit-code shape.
- **Day 9** — Dry-run on a draft PR; collect first `<sha>-postgres-equivalence.json` evidence file; verify `provenance: measured`.
- **Day 10** — Publish `docs/perf/concurrency-methodology-v1.md` v1.1 with §7.1 + §7.2.
- **Day 11** — Cross-stack smoke: run W36-A3 retention test together with the new Postgres equivalence test on the same CI shard; verify no contamination.
- **Day 12** — Equivalence-window calibration: confirm N=10/M=1 is stable across 5 consecutive runs; record p99 of SQLite + Postgres legs in evidence JSON for future regression budget.
- **Day 13** — W36 delivery-notice draft: §3 inventory table + three-part closure block.
- **Day 14** — Land + sign off; verify `check_postgres_equivalence_evidence.py` PASS at the W36 release HEAD; update Rule 15 closure-level enum to `verified_at_release_head`.

---

## 10. Risk Registry

1. **Postgres-incompatible SQL** (e.g. SQLite `PRAGMA journal_mode=WAL`, JSON1 functions). Each `pg_*` store at `agent_kernel/kernel/persistence/pg_*.py` already implements its own SQL dialect (see `pg_event_log.py:15` constructor + DDL); the test only exercises behaviour through Protocol ports, so dialect drift is contained. **Mitigation:** none new — the existing pg modules are the dialect map; future Postgres impls inherit the same discipline.
2. **Connection-pool tuning at N=50** — `pool_min=2 / pool_max=10` (`pg_colocated_bundle.py:23-25`) is the current default. At N=10/M=1 (W36 required workload) this is more than sufficient; at the optional N=100/M=10 it may saturate. **Mitigation:** out of scope for W36; tracked as W37+ if N=100 raise lands.
3. **Schema migration under Postgres** — DDL between SQLite and Postgres differs (`IF NOT EXISTS` syntax, type names, `AUTOINCREMENT` vs `SERIAL/IDENTITY`). The pg modules already issue Postgres-native DDL on bridge bootstrap; the CI service container starts empty so migrations run on first connection. **Mitigation:** `pg_shared.py` `AsyncPGBridge` + per-store schema-init paths; verified on Day 2 of sequencing.
4. **Stores tested only under SQLite** (`SQLiteDecisionDeduper`, `SQLiteTurnIntentLog`, plus the 6 SQLite-coupled agent_server stores). These do not have Postgres parallels in W36; if the W36 equivalence run reveals divergence in the kernel-persistence-only path, the SQLite-coupled stores cannot be implicated. **Mitigation:** §3 inventory table records the gap explicitly; W37+ extracts `EventStorePort` / `RunStorePort` / `GateStorePort` and lands Postgres parallels.
5. **CI runner Postgres unavailability** — `postgres:16-alpine` service container may fail to come up on flaky runners (rare). **Mitigation:** health-check + 5 retries (§5.2); on failure, the test SKIPs (current behaviour), the gate `check_postgres_equivalence_evidence.py` FAILs (no evidence at HEAD), and CI blocks merge. Loud, structured, gate-asserted (Rule 7).
6. **Stub-backend short-circuit** — the existing helper hard-codes `AGENT_SERVER_BACKEND=stub` (file:55-56) which means agent_server-side durable writes are bypassed. The equivalence test therefore proves equivalence of the **kernel-persistence path**, not the agent-server-persistence path. **Mitigation:** §1 position statement makes this explicit; §3 inventory shows which layer is exercised. Future wave: real-backend equivalence test once agent_server stores have Protocol ports.

---

## 11. References

- RIA W36 supplement directive — `docs/upstream-directives/2026-05-07-hi-agent-w35-corrective-acceptance-and-w36-supplement-directive.md` (TO-CONFIRM at intake; currently lives at `D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md` §2.2).
- Concurrency methodology v1 — `docs/perf/concurrency-methodology-v1.md` (§7 equivalence definition; §9 regression budget proposal).
- W34 baseline numbers — `docs/downstream-responses/2026-05-05-w34-delivery-notice.md:39-40`.
- Existing equivalence test — `tests/integration/test_concurrency_persistence_swap.py:1-119`.
- Postgres backend bundle — `agent_kernel/kernel/persistence/pg_colocated_bundle.py:16-55`.
- KernelRuntime persistence selector — `agent_kernel/runtime/kernel_runtime.py:123-126,531-545`.
- W36 plan-set companions — `docs/superpowers/plans/2026-05-06-wave-36-a3-tier1-retention-adoption.md` (A3); A4, A5, S-1, S-3 plans.
- Three-part closure taxonomy — `CLAUDE.md` Rule 15; `docs/governance/closure-taxonomy.md`.

---

**End of W36-S-2 plan.**
