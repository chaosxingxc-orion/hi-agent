# Wave 36 A3 — Tier-1 Retention Adoption (8 stores)

**Date:** 2026-05-06
**Wave:** W36 binding
**Reference:** RIA W36 directive §3.1; W35-T4 idempotency reference; `docs/governance/retention-roadmap.md`
**Owner:** RO (track lead) + TE (observability) + DX (env-var convention)

---

## 1. Architectural baseline (W35-T4 reusable shape)

The reference for every adoption is `IdempotencyStore.purge_expired` plus its
lifespan loop. Each adoption clones this shape; only the SQL predicate and
metric label change.

**1.1 Store-level method** (`hi_agent/server/idempotency.py:193-239`)

- Signature: `purge_expired(now: float | None = None) -> int` OR
  `purge_older_than(retention_seconds: float, now=None) -> int`.
- Body: `with self._lock: DELETE WHERE <age_predicate> < cutoff; commit;
  if deleted >= 100: VACUUM (best-effort, OperationalError-safe)`.
- After the lock releases: emit
  `hi_agent_<store>_purged_total{tenant_id}` via the metrics module.
- Lazy-purge inside hot read paths is OPTIONAL — only adopt when the store
  has a per-key UNIQUE-style read that would otherwise return stale rows
  (idempotency does; events/audit do not).

**1.2 Lifespan loop** (`agent_server/runtime/lifespan.py:98-134`)

```
async def _<store>_purge_loop(agent_server, interval_s):
    store = getattr(agent_server, "_<store>_store", None)
    if store is None: return                                  # no-op
    loop = asyncio.get_running_loop()
    while True:
        try: await asyncio.sleep(interval_s)
        except asyncio.CancelledError: raise
        try:
            purged = await loop.run_in_executor(None, store.purge_expired)
        except asyncio.CancelledError: raise
        except Exception as exc:
            record_silent_degradation(component="<store>_purge_loop",
                                       reason="purge_failed", exc=exc)
            continue
        if purged > 0: _log.info("<store> purge: deleted %d", purged)
```

**1.3 Lifespan wiring** (`agent_server/runtime/lifespan.py:270-326`)

A single `build_real_kernel_lifespan` already supervises lease, watchdog, and
idempotency purge tasks. Per Rule 6 we extend that one supervisor with a
sibling task per store; we do NOT spawn a second lifespan helper.

**1.4 Bootstrap stash** (`agent_server/bootstrap.py`, mirroring the
`_idempotency_store` attach pattern at `agent_server/runtime/lifespan.py:275`)

- `agent_server._<store>_store = store` after backend construction.
- The lifespan reads via `getattr(...)` so test harnesses without the store
  collapse to no-op (per Rule 7's countability still passes — zero counter
  increments is observable).

**1.5 Metric** — registered in
`hi_agent/observability/collector.py::_METRIC_DEFS` and exposed by a small
helper module shaped exactly like `hi_agent/observability/idempotency_metrics.py`.
Per Track A C-1 (W35), `tenant_id` is emitted **raw**; aggregate (tenant-mixed)
purges emit `tenant_id=""` as a stable distinct series.

**1.6 Regression test** — clone
`tests/integration/test_idempotency_ttl_purge.py` (offline-default profile):

- `test_purge_deletes_only_expired` (mixed expired/fresh seed)
- `test_purge_no_expired_records` (empty + all-fresh paths)
- `test_disk_growth_regression` (`@pytest.mark.slow`, 10 K seed → 50 % shrink)
- `test_purge_loop_cancelled_on_lifespan_shutdown` (lifespan integration with
  stub backend)

---

## 2. Per-store plan

### Store 1 — `SQLiteEventStore` (`hi_agent/server/event_store.py`)

- **Schema:** `run_events(id, event_id UNIQUE, run_id, sequence, event_type,
  payload_json, tenant_id, user_id, session_id, trace_id, created_at,
  parent_run_id, attempt_id, phase_id)` (file:75-90).
- **Retention semantics:** delete events whose `run_id` belongs to a
  `run_records.status` in terminal set AND whose `created_at < cutoff`. For
  active runs, preserve the last N=200 events (W36 default; tunable).
- **purge signature:** `purge_older_than(retention_seconds: float = 30*86400)
  -> int` — joins `run_records` for terminal-state filter (acceptable: same
  DB file).
- **Lifespan wiring:** new `_event_store_purge_loop`.
- **Env vars:** `HI_AGENT_EVENT_STORE_RETENTION_DAYS=30`,
  `HI_AGENT_EVENT_STORE_PURGE_INTERVAL_S=3600` (events are highest volume —
  hourly is enough; tighter intervals raise lock contention).
- **Metric:** `hi_agent_event_store_purged_total{tenant_id}` — chunk DELETE
  by `tenant_id` so the label is meaningful (see Risk 1).
- **Test:** `tests/integration/test_event_store_retention.py`.
- **Three-part closure:**
  (a) `event_store.py::purge_older_than` impl + `lifespan.py::_event_store_purge_loop`;
  (b) `tests/integration/test_event_store_retention.py`;
  (c) update `retention-roadmap.md` Tier 1 row 1 to "closed @ <SHA>".
- **Risk:** highest-volume table; single-shot DELETE on 1 M rows blocks
  writers — use chunked `DELETE ... LIMIT 5000` loop with commit between
  chunks.

### Store 2 — `SQLiteRunStore` (`hi_agent/server/run_store.py`)

- **Schema:** `run_records(run_id PK, tenant_id, user_id, session_id,
  task_contract_json, status, priority, attempt_count, cancellation_flag,
  result_summary, error_summary, created_at, updated_at, finished_at,
  parent_run_id, attempt_id, phase_id)` (file:141-159).
- **Retention semantics:** delete rows where `status IN (terminal_set) AND
  finished_at > 0 AND finished_at < cutoff`. Never delete non-terminal rows.
- **purge signature:** `purge_completed_older_than(retention_seconds: float =
  30*86400) -> int`.
- **Coupling note:** must run **before** SQLiteEventStore purge OR after,
  but never concurrently — events reference run_id. Lifespan supervisor
  serializes by ordering tasks; document the dependency.
- **Env vars:** `HI_AGENT_RUN_STORE_RETENTION_DAYS=30`,
  `HI_AGENT_RUN_STORE_PURGE_INTERVAL_S=3600`.
- **Metric:** `hi_agent_run_store_purged_total{tenant_id}`.
- **Test:** `tests/integration/test_run_store_retention.py`.
- **Risk:** terminal-state classification drift — assert against
  `_TERMINAL_STATES` in `agent_server/runtime/lifespan.py:58-68` so both
  modules use one source of truth.

### Store 3 — `SQLiteGateStore` (`hi_agent/management/gate_store.py`)

- **Schema:** `gates(gate_ref PK, run_id, project_id, stage_id, status,
  payload, created_at, updated_at, resolved_at, tenant_id, user_id,
  session_id)` (file:74-87) — `resolved_at` is already populated.
- **Retention semantics:** `WHERE resolved_at > 0 AND resolved_at < cutoff`.
- **purge signature:** `purge_resolved_older_than(retention_seconds: float =
  14*86400) -> int`.
- **Env vars:** `HI_AGENT_GATE_STORE_RETENTION_DAYS=14`,
  `HI_AGENT_GATE_STORE_PURGE_INTERVAL_S=1800`.
- **Metric:** `hi_agent_gate_store_purged_total{tenant_id}`.
- **Test:** `tests/integration/test_gate_store_retention.py`.
- **Risk:** lowest of the SQL stores — `resolved_at` filter is index-friendly
  if we add `CREATE INDEX idx_gates_resolved_at ON gates(resolved_at)` in the
  same PR.

### Store 4 — `SqliteDecisionAuditStore` (`hi_agent/route_engine/decision_audit_store.py`)

- **Schema:** `route_decision_audit(id, run_id, stage_id, payload_json,
  created_at)` (file:71-77). NOTE: no `tenant_id` column.
- **Retention semantics:** delete rows where `created_at < cutoff` (90-day
  audit window). Aggregate purge — no per-tenant breakdown possible.
- **purge signature:** `purge_older_than(retention_seconds: float =
  90*86400) -> int`.
- **Env vars:** `HI_AGENT_DECISION_AUDIT_RETENTION_DAYS=90`,
  `HI_AGENT_DECISION_AUDIT_PURGE_INTERVAL_S=3600`.
- **Metric:** `hi_agent_decision_audit_purged_total{tenant_id=""}` —
  documented per W35-T4 convention as the aggregate-batch label.
- **Test:** `tests/integration/test_decision_audit_retention.py`.
- **Risk:** missing `tenant_id` is a Rule 12 process-internal exception —
  add a `# scope: process-internal` rationale referencing this gap, OR
  schedule a Day-1 column-add migration (preferred: makes future per-tenant
  metrics possible). Owner choice; document outcome.

### Store 5 — `SqliteEvidenceStore` (`hi_agent/runtime/harness/evidence_store.py`)

- **Schema:** `evidence(evidence_ref PK, action_id, evidence_type, content,
  timestamp TEXT)` (file:96-102). NOTE: `timestamp` is TEXT (ISO 8601), not
  a numeric epoch — purge predicate must convert (`timestamp < datetime(?, 'unixepoch')`)
  or store the ISO cutoff.
- **Duplication:** `hi_agent/harness/evidence_store.py` is a deprecated
  shim with `expiry_wave: Wave 36` (file:1-12). **W36 deletes the shim**;
  retention adoption targets the canonical path only. Track this in the
  closure block.
- **Retention semantics:** delete evidence older than 60 days.
- **purge signature:** `purge_older_than(retention_seconds: float =
  60*86400) -> int`.
- **Env vars:** `HI_AGENT_EVIDENCE_STORE_RETENTION_DAYS=60`,
  `HI_AGENT_EVIDENCE_STORE_PURGE_INTERVAL_S=3600`.
- **Metric:** `hi_agent_evidence_store_purged_total{tenant_id=""}` —
  schema lacks `tenant_id`; aggregate batch.
- **Test:** `tests/integration/test_evidence_store_retention.py`.
- **Risk:** TEXT-typed timestamp — tests must seed both formats present
  in production data; predicate must be range-correct on string-sorted
  ISO 8601 (which is sortable, so `WHERE timestamp < ?` with an ISO
  cutoff works without conversion — preferred).

### Store 6 — `SQLiteKernelRuntimeEventLog` (`agent_kernel/kernel/persistence/sqlite_event_log.py`)

- **Schema:** two tables — `action_commits(commit_sequence PK, stream_run_id,
  commit_id, created_at TEXT, event_count CHECK(>0))` and
  `runtime_events(id PK, commit_sequence FK, event_index, stream_run_id,
  event_run_id, commit_offset, event_id, event_type, event_class, ...)`
  (file:159-180).
- **Retention semantics:** terminal-run snapshot — when a `stream_run_id`
  reaches a kernel-terminal state, evict its commits + events older than
  30 days. Two-table cascade DELETE with FK ordering.
- **purge signature:** `purge_terminal_runs_older_than(retention_seconds:
  float = 30*86400) -> int` — returns combined row count across both tables.
- **Wiring point:** agent_kernel has NO independent lifespan;
  `KernelRuntime` (`agent_kernel/runtime/kernel_runtime.py`) is started by
  `agent_server/bootstrap.py`. The agent_server lifespan owns the purge
  loop; bootstrap stashes `agent_server._kernel_event_log_store = log`
  after `KernelRuntime.start()` returns.
- **Env vars:** `HI_AGENT_KERNEL_EVENT_LOG_RETENTION_DAYS=30`,
  `HI_AGENT_KERNEL_EVENT_LOG_PURGE_INTERVAL_S=3600`.
- **Metric:** `hi_agent_kernel_event_log_purged_total{tenant_id=""}` —
  schema lacks tenant; aggregate.
- **Test:** `tests/integration/test_kernel_event_log_retention.py`.
- **Risk:** dual-table FK cascade — order matters (events first, then
  commits); a partial purge leaves dangling commits. Wrap in a single
  transaction.

### Store 7 — `SQLiteDedupeStore` + `SQLiteDecisionDeduper` (group)

Both are fingerprint stores; share an interval task to keep the lifespan
supervisor compact.

- **Files:** `agent_kernel/kernel/persistence/sqlite_dedupe_store.py:475-482`
  (`dedupe_store(dispatch_idempotency_key PK, operation_fingerprint,
  attempt_seq, state, ...)`) and
  `agent_kernel/kernel/persistence/sqlite_decision_deduper.py:128-132`
  (`decision_fingerprints(fingerprint PK, run_id, created_at REAL)`).
- **Retention semantics:** dedupe_store has no `created_at` column — must
  add via migration on Day 1 OR purge by FK to terminal-run set. Decision
  deduper has `created_at REAL` — easy.
- **purge signatures:**
  - `SQLiteDedupeStore.purge_terminal_older_than(retention_seconds: float =
    90*86400) -> int`
  - `SQLiteDecisionDeduper.purge_older_than(retention_seconds: float =
    90*86400) -> int`
- **Wiring point:** single `_kernel_dedupe_purge_loop` in agent_server
  lifespan calls both purges sequentially.
- **Env vars:** `HI_AGENT_KERNEL_DEDUPE_RETENTION_DAYS=90`,
  `HI_AGENT_KERNEL_DEDUPE_PURGE_INTERVAL_S=3600` (one var pair governs both
  fingerprint stores; documented in roadmap).
- **Metrics:** `hi_agent_kernel_dedupe_store_purged_total{tenant_id=""}`,
  `hi_agent_kernel_decision_deduper_purged_total{tenant_id=""}`.
- **Test:** `tests/integration/test_kernel_dedupe_retention.py` covers both.
- **Risk:** dedupe_store schema migration may need offline migration on
  existing deployments — emit a `WARNING` log when a missing-column
  exception fires and skip the purge for that backend until migration runs.

### Store 8 — `SQLiteRecoveryOutcomeStore` + `SQLiteTurnIntentLog` (group)

Two operational-history tables. NOTE: `sqlite_task_view_log.py` exists in
`agent_kernel/kernel/persistence/` but is NOT instantiated in
`agent_kernel/runtime/bundle.py` (verified — no `SQLiteTaskViewLog(`
construction site found). **Day-1 investigation:** confirm whether
`sqlite_task_view_log` is dead code or wired through a path the audit
missed; defer adoption until source is identified. Without an instantiation
site there is no lifespan attach point.

- **Files:** `sqlite_recovery_outcome_store.py:112-120` (`recovery_outcome(id
  PK, run_id, action_id, recovery_mode, outcome_state, written_at TEXT,
  operator_escalation_ref, emitted_event_ids_json)`),
  `sqlite_turn_intent_log.py:136-144` (`turn_intent_log(id PK, run_id,
  intent_commit_ref UNIQUE, decision_ref, decision_fingerprint,
  dispatch_dedupe_key, host_kind, outcome_kind, ...)`).
- **Retention semantics:** delete rows older than 30 days (live ops history).
- **purge signature** (each): `purge_older_than(retention_seconds: float =
  30*86400) -> int`. `written_at` is TEXT ISO 8601 — same treatment as
  Store 5.
- **Wiring point:** `_kernel_ops_history_purge_loop` runs both.
- **Env vars:** `HI_AGENT_KERNEL_OPS_HISTORY_RETENTION_DAYS=30`,
  `HI_AGENT_KERNEL_OPS_HISTORY_PURGE_INTERVAL_S=3600`.
- **Metrics:** one per table: `hi_agent_kernel_recovery_outcome_purged_total`,
  `hi_agent_kernel_turn_intent_log_purged_total` (both `{tenant_id=""}`).
- **Test:** `tests/integration/test_kernel_ops_history_retention.py`.
- **Risk:** task_view_log is deferred — record as known-defect (level
  `component_exists`) per Rule 15 if Day-1 investigation finds it is wired
  via an indirect path; otherwise mark the file dead-code and remove in a
  separate cleanup commit.

---

## 3. Cross-cutting concerns

**3.1 Posture-aware defaults (Rule 11):**
- `dev`: retention defaults apply; purge tasks start. Operators may set
  `HI_AGENT_<STORE>_PURGE_INTERVAL_S=0` (disabled) to opt out.
- `research`/`prod`: retention is on by default (no opt-out env var).
  Setting interval to 0 under research/prod logs a `WARNING` and clamps to
  the default interval — Rule 11 fail-closed for research/prod.

**3.2 Single supervisor task (Rule 6):**
- Agent_server lifespan owns ALL 8 store purge loops. We do NOT add a
  second lifespan helper for the agent_kernel-bound stores; they attach via
  `bootstrap.py` after `KernelRuntime.start()` so the agent_server lifespan
  is the single construction path.
- Deletion order matters between Stores 1 and 2 (events before runs is
  unsafe — events FK-reference runs). Stagger task `interval_s` start
  offsets by 60 s so they do not race.

**3.3 Metric label policy:**
- Where the schema carries `tenant_id`: chunk DELETEs per tenant and emit
  raw label values. Stores: 1, 2, 3.
- Where the schema lacks `tenant_id`: aggregate batch with
  `tenant_id=""` (Track A C-1 convention). Stores: 4, 5, 6, 7a, 7b, 8a, 8b.

**3.4 Env vars:** 16 new vars (8 stores × 2). They do NOT enter
`docs/governance/allowlists.yaml` (no env_vars section currently exists);
they are documented in the W36-updated `retention-roadmap.md` "Operational
note" section. DX track owns the env-var convention check.

**3.5 Rule 7 four-part observability per store:**
- Countable: `hi_agent_<store>_purged_total{tenant_id}`.
- Attributable: `record_silent_degradation(component=..., reason="purge_failed", exc=exc)`
  on first failure; ERROR-level promotion if the same store fails 3 times
  consecutively.
- Inspectable: not applicable (background loops, not run records).
- Gate-asserted: operator-shape gate (Rule 8) already runs purge at least
  once on a 3-run sequence; assert `purged_total >= 0` and no
  `silent_degradation` entries for `<store>_purge_loop`.

**3.6 Evidence store deduplication finding:**
- `hi_agent/harness/evidence_store.py` is a 12-line shim with `expiry_wave:
  Wave 36`. **W36 task:** delete the shim file; update any imports.
  Retention work targets `hi_agent/runtime/harness/evidence_store.py`
  exclusively.

---

## 4. Risk registry (aggregate)

1. **Volume DELETE blocks writers** (Stores 1, 6) — chunked `DELETE LIMIT
   5000` with commit between chunks; never single-shot a million-row delete.
2. **VACUUM blocks writers** — only run when `deleted >= 100` AND not more
   than once per 24 h per store (cap inside the store via
   `_last_vacuum_at` instance attribute).
3. **TEXT-typed timestamps** (Stores 5, 6, 8) — ISO 8601 string ordering is
   compatible with `WHERE col < ?`; tests must verify this against real
   production data shapes.
4. **Schema lacks `tenant_id`** (Stores 4, 5, 6, 7, 8) — aggregate metric
   label `tenant_id=""` per W35 C-1; no per-tenant breakdown until column
   add (out of scope for W36).
5. **Cross-store referential ordering** (Stores 1↔2, Store 6 internal) —
   stagger task starts by 60 s; document explicit ordering rule in the
   lifespan helper docstring.
6. **dedupe_store missing `created_at`** (Store 7a) — Day-1 migration to
   add the column; on missing-column error, log WARNING and skip until
   migration runs.
7. **task_view_log instantiation unknown** (Store 8 sub-item) — Day-1
   investigation; defer if no construction site found.
8. **Lifespan task interference at shutdown** — reuse cooperative-cancel
   pattern from W35-T4 (`agent_server/runtime/lifespan.py:336-341`); each
   new task joins the same `bg_tasks` tuple and cancels in the same loop.

---

## 5. Cross-team coordination

B13 (boot-time assertion silent route omission, RIA R-RIA-9) is **not**
related to A3. No coordination needed.

---

## 6. Acceptance criteria (W36 closure, per RIA §3.1)

- [ ] 8 stores each have closed retention with structural test and metric.
- [ ] `retention-roadmap.md` Tier-1 rows updated to "closed @ <SHA>" with
      file:line of each `purge_*` method.
- [ ] Three-part closure rows in delivery notice per store (code-fix,
      regression-test, process-change).
- [ ] Metric label set follows W35-T4 + Track A C-1: raw `{tenant_id}` where
      schema supports it, `{tenant_id=""}` aggregate elsewhere.
- [ ] `hi_agent/harness/evidence_store.py` shim deleted; imports migrated.
- [ ] No new entries in `docs/governance/allowlists.yaml`; 16 new env vars
      documented in `retention-roadmap.md`.
- [ ] All 8 stores assert L3 in the W36 capability matrix (default-on under
      research/prod, observable, doctor-check coverage).

---

## 7. Implementation sequencing

- **Day 1:** investigation + scaffolding — confirm `sqlite_task_view_log`
  wiring; add `idx_gates_resolved_at` migration design; agree
  `_TERMINAL_STATES` shared constant location.
- **Day 2-3:** Store 1 (SQLiteEventStore) — highest-risk, set the chunked
  DELETE pattern that Stores 2, 6 will reuse.
- **Day 4-5:** Stores 2, 3 (SQLiteRunStore, SQLiteGateStore) — parallel,
  similar shape to Store 1.
- **Day 6-7:** Stores 4, 5 (SqliteDecisionAuditStore, SqliteEvidenceStore)
  + delete `hi_agent/harness/evidence_store.py` shim.
- **Day 8-10:** Stores 6, 7, 8 (agent_kernel triplet) — bootstrap stash
  pattern + lifespan supervisor extension.
- **Day 11-12:** cross-cutting wiring; allowlist sweep (no new entries
  expected); retention-roadmap update with closure SHAs.
- **Day 13-14:** Rule 8 operator-shape gate run with retention enabled in
  research posture; record evidence in `docs/delivery/<date>-<sha>.md`.
