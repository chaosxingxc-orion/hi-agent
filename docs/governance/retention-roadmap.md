# Retention Roadmap — Unbounded-Growth Stores Catalog

**Date:** 2026-05-05
**Wave:** W35 → W36+ scoping
**Source audit:** `docs/governance/systematic-audit-w35-2026-05-05.md` §A3
**Status:** W36 binding for Tier 1 (highest-volume); W37+ for Tier 2/3.

This document catalogs persistent stores that today accumulate without garbage collection, TTL eviction, or rotation. The 7×24 architectural feasibility lens (RIA W35 §2.7) requires every store to either:
1. Have a documented retention policy with operator-actionable knobs, OR
2. Be bounded-by-design (per-run lifecycle, capped LRU, etc.)

A store with unbounded growth and no retention policy is a Rule 8 architectural-feasibility defect.

---

## Tier 1 — Highest-volume risk (W36 binding)

These stores receive `purge_expired` / `purge_older_than` mechanism + lifespan background task. The IdempotencyStore (W35-T4) is the reference implementation.

### 1. SQLiteEventStore

- **File:** `hi_agent/server/event_store.py`
- **Backend:** SQLite `run_events` table
- **Volume estimate:** O(events × runs); biggest volume risk on the platform
- **Current state:** append-only; no DELETE anywhere
- **W36 plan:** Add `purge_older_than(retention_days)` method (default 30 days for terminal-state runs); preserve last N events per active run. Add background task in lifespan. Add `hi_agent_event_store_purged_total{tenant_id}` counter.

### 2. SQLiteRunStore

- **File:** `hi_agent/server/run_store.py`
- **Backend:** SQLite `run_records` table
- **Volume estimate:** O(runs); 1 row per `POST /runs`
- **Current state:** only single-row `delete()` for explicit deletion
- **W36 plan:** Add `purge_completed_older_than(retention_days)` (default 30 days; terminal states only). Background task. Counter.

### 3. SQLiteGateStore

- **File:** `hi_agent/management/gate_store.py`
- **Backend:** SQLite `gates` table
- **Volume estimate:** O(gates × runs)
- **Current state:** `resolved_at` set but no DELETE
- **W36 plan:** Add `purge_resolved_older_than(retention_days)` (default 14 days). Background task.

### 4. SqliteDecisionAuditStore

- **File:** `hi_agent/route_engine/decision_audit_store.py`
- **Backend:** SQLite, append-only
- **Volume estimate:** O(decisions × runs)
- **Current state:** append-only forever
- **W36 plan:** Retention policy 90 days (audit trail), purge older. Background task.

### 5. SqliteEvidenceStore

- **File:** `hi_agent/runtime/harness/evidence_store.py` and `hi_agent/harness/evidence_store.py`
- **Backend:** SQLite, append-only
- **Volume estimate:** O(evidence × runs)
- **W36 plan:** Retention 60 days. Background task.

### 6–8. agent_kernel persistence triplet

- `agent_kernel/kernel/persistence/sqlite_event_log.py` — `action_commits` + `runtime_events` tables
- `agent_kernel/kernel/persistence/sqlite_dedupe_store.py` — `decision_fingerprints`, `dedupe_fingerprints`
- `agent_kernel/kernel/persistence/sqlite_task_view_log.py`
- `agent_kernel/kernel/persistence/sqlite_turn_intent_log.py`
- `agent_kernel/kernel/persistence/sqlite_recovery_outcome_store.py`
- `agent_kernel/kernel/persistence/sqlite_decision_deduper.py`

**Combined plan:** retention 30 days for live ops history; quarterly TTL for fingerprints (90 days). Background task per store.

---

## Tier 2 — Lower-volume but unbounded (W37 binding)

### 9. SqliteExperimentStore

- **File:** `hi_agent/evolve/experiment_store.py`
- **Backend:** SQLite `evolution_experiments`
- **Plan:** Retention 365 days (long-tail evolution data). Counter.

### 10. LongRunningOpStore

- **File:** `hi_agent/operations/op_store.py`
- **Backend:** SQLite `ops`
- **Plan:** Purge terminal ops older than 7 days. Background task.

### 11. SessionStore

- **File:** `hi_agent/server/session_store.py`
- **Backend:** SQLite `sessions`
- **Plan:** `archived_at` already set; add purge for `archived_at + 30d`.

### 12. TeamRunRegistry

- **File:** `hi_agent/server/team_run_registry.py`
- **Plan:** Tied to team lifecycle; purge orphaned (no active team_space_id) older than 90 days.

### 13. TeamEventStore

- **File:** `hi_agent/server/team_event_store.py`
- **Plan:** Mirror SQLiteEventStore retention.

### 14. SkillRegistry promotion_history

- **File:** `hi_agent/skill/registry.py` (`registry.json`)
- **Plan:** Retain last N=20 promotion events per skill; older entries archived to `registry.history.<wave>.json` and rotated quarterly.

---

## Tier 3 — In-memory unbounded (W37+ urgent)

These are RAM-resident — they exhaust process memory faster than SQLite exhausts disk. Highest priority for capping.

### 15. OpsSnapshotStore

- **File:** `hi_agent/management/ops_snapshot_store.py`
- **Backend:** in-memory `_entries: list[dict]`
- **Plan:** Cap at N=10,000 entries (LRU eviction); add `entries_dropped_total` counter.

### 16. EventSummaryStore

- **File:** `hi_agent/runtime_adapter/event_summary_store.py`
- **Backend:** in-memory dict keyed by run_id
- **Plan:** Cap at N=1,000 active runs; LRU on completion.

### 17. InMemoryDecisionAuditStore

- **File:** `hi_agent/route_engine/decision_audit_store.py`
- **Plan:** Document as test-only; remove from production paths under research/prod posture.

### 18. InMemoryKnowledgeStore

- **File:** `hi_agent/knowledge/store.py`
- **Plan:** Same — test-only; production must use SQLite/JSON-backed L3 backend.

---

## Tier 4 — JSON / file append-only (W37+)

### 19. ArtifactLedger

- **File:** `hi_agent/artifacts/ledger.py`
- **Backend:** JSONL file, append-only
- **Plan:** Add log rotation (size-based, e.g. 100MB per file with .1, .2, .N suffix). Background rotator. Configurable retention by file count.

### 20. FeedbackStore

- **File:** `hi_agent/evolve/feedback_store.py`
- **Backend:** JSON file, one record per run_id
- **Plan:** Cap at N=10,000 records (FIFO eviction); migrate to SQLite under research/prod.

### 21. Tenant-scope audit

- **File:** `hi_agent/server/tenant_scope_audit.py`
- **Backend:** explicitly documented "append-only with no rotation; operators rotate out-of-band"
- **Plan:** Document operator rotation procedure in `docs/operations/audit-log-rotation.md`. Add log-size monitoring metric for ops dashboards.

---

## Implementation Pattern (W35-T4 reference)

For each Tier-1 store, the implementation follows the W35-T4 pattern:

1. **Store-level method:** `purge_expired(now=None) -> int` or `purge_older_than(retention_seconds) -> int` — thread-safe, returns rows deleted, optional VACUUM at threshold.
2. **Lazy purge:** in any "reserve" or "lookup" method, opportunistically delete-on-found-expired before the primary operation.
3. **Background loop:** `_<store>_purge_loop(agent_server, interval_s)` in `agent_server/runtime/lifespan.py`. Reads interval from env var. Calls `record_silent_degradation` on failure.
4. **Wire to bootstrap:** `agent_server/bootstrap.py` assigns `real_backend._<store_name> = store` after RealKernelBackend construction.
5. **Prometheus counter:** `hi_agent_<store>_purged_total{tenant_id}`.
6. **Tests:** `tests/integration/test_<store>_ttl_purge.py` mirroring `test_idempotency_ttl_purge.py`:
   - test_purge_deletes_only_expired
   - test_purge_no_expired_records
   - test_disk_growth_regression (`@pytest.mark.slow`)
   - test_purge_loop_cancelled_on_lifespan_shutdown

---

## Operational note — Why retention defaults are "30 days"

These defaults are starting points calibrated to the W34 concurrency baseline (P50=77.5ms / P95=200.4ms at N=50/M=5). Operators MUST review and adjust per deployment shape via env vars. Defaults exist so a fresh deployment is feasible-out-of-the-box, not because 30 days is universally optimal.

Each store's retention env var follows the convention:
```
HI_AGENT_<STORE>_RETENTION_DAYS=30
HI_AGENT_<STORE>_PURGE_INTERVAL_S=600
```

---

## Cross-reference

- W35-T4 reference: `tests/integration/test_idempotency_ttl_purge.py`, `hi_agent/server/idempotency.py::IdempotencyStore.purge_expired`, `agent_server/runtime/lifespan.py::_idempotency_purge_loop`
- Audit source: `docs/governance/systematic-audit-w35-2026-05-05.md` §A3
- W34 concurrency baseline: `docs/perf/concurrency-methodology-v1.md`, `docs/verification/c7d1054e-concurrency-N50M5.json`
