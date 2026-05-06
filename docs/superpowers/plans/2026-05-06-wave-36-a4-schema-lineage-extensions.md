# Wave 36 A4 — Schema-Shape Lineage Extensions

**Date:** 2026-05-06
**Wave:** W36 binding
**Reference:** RIA W36 directive `D:\chao_workspace\research\docs\hi-agent-wave36-engineering-expectations-2026-05-05.md` §3.3 (HIGH) and §2.3 (MEDIUM 4 sites); W35-T1 spine pattern; W34-F.2 lineage design; W35 audit `docs/governance/systematic-audit-w35-2026-05-05.md` §A4.
**Owner:** AS-CO (lead — `agent_server/contracts/run.py`) + CO (`hi_agent/contracts/reasoning_trace.py`) + RO (`hi_agent/server/event_store.py`, `run_manager.py`, `event_bus.py`, `operations/op_store.py`) + DX (consumer-doc handshake with RIA `evolution_engine/postmortem.py`).

---

## Architectural baseline

W35-T1 established a posture-aware spine validator pattern with two flavours:

- `agent_server/contracts/run.py` uses local helpers `SpineCompletenessError` + `_strict_posture()` from `agent_server.contracts.errors`. Frozen dataclass; `__post_init__` raises under research/prod, logs WARNING under dev. Verified: `RunRequest` (25–50), `RunResponse` (65–87), `RunStatus` (101–123), `RunStream` (137–159).
- `hi_agent/contracts/requests.py:16–50` defines `_validate_spine(obj_name, fields)` lazily importing `Posture.from_env()` + `SpineCompletenessError`; used from `__post_init__` of every dataclass (62–245).

The 53-target enrolment list lives in `scripts/check_dataclass_spine_validation.py::REQUIRED_VALIDATION_TARGETS` (26–80+). All five A4 schema dataclasses are already enrolled; A4 widens their **required-field set**, not the enrolment list.

Wire-format propagation is enforced ad hoc:
- Route handlers call `dataclasses.asdict` or build a literal dict (`routes_runs_extended.py::_status_dict` 92–100 hand-builds `RunStatus`).
- `event_facade.py::render_sse_chunk` (77–99) hand-builds the SSE JSON body; it does NOT pass through unknown keys.
- `hi_agent/server/event_store.py::StoredEvent` carries `parent_run_id`/`attempt_id`/`phase_id` (33–36) since W33-F; `RuntimeEvent` (`agent_kernel/kernel/contracts.py:67`) does NOT.

A4's architectural crux: lineage exists on the persistence side but is invisible at the wire-level read surface.

---

## Per-dataclass plan (5 HIGH)

For each dataclass below: file:line, current shape, target shape, serialization touch points, validation rule, regression test, three-part closure.

### Dataclass 1: `RunResponse`
**File:** `agent_server/contracts/run.py:53–87`. Current: `tenant_id, run_id, state, current_stage, started_at, finished_at, metadata`; required `tenant_id, run_id, state`.
**Target:** add `parent_run_id: str = ""`, `attempt_id: str = ""`, `attempt_count: int = 0`, `phase_id: str = ""` — all Optional for Phase 1.
**Wire-format:** every `RunResponse(...)` builder in `agent_server/api/routes_runs.py` + `routes_runs_extended.py` must propagate. Frozen dataclass + `dataclasses.asdict` picks them up; hand-built dicts must be updated.
**Validation (Phase 2):** under research/prod, `parent_run_id != ""` (re-attempt) requires `attempt_id` and `attempt_count >= 1`; initial-attempt accepts empties for back-compat.
**Regression test:** `tests/contracts/test_run_response_lineage.py` — three cases: (a) initial attempt with all four omitted PASS under research; (b) re-attempt missing `attempt_id` raises under research; (c) dev posture warns. Reuse `_strict_posture()` monkeypatch pattern.
**Three-part closure:** code fix SHA + `tests/contracts/test_run_response_lineage.py::test_*` + extended `check_dataclass_spine_validation.py` (see Cross-cutting).
**Risk:** low — facade goes through `asdict`; no field-stripping middleware in `agent_server/api/middleware/`.

### Dataclass 2: `RunStatus`
**File:** `agent_server/contracts/run.py:90–123`. Current: `tenant_id, run_id, state, current_stage, llm_fallback_count, finished_at`; required `tenant_id, run_id, state`.
**Target:** identical four lineage fields.
**Wire-format:** `_status_dict` (`routes_runs_extended.py:92`) hand-builds the dict — MUST emit the four new fields. `EventFacade.cancel` / `assert_run_visible` (`event_facade.py:43–66`) build `RunStatus` from a callable's `record` dict — the upstream callable in `hi_agent.server.run_manager` must populate them. Largest single wire-format change.
**Validation:** identical re-attempt invariant.
**Regression test:** `tests/contracts/test_run_status_lineage.py` + integration test driving `GET /v1/runs/{id}/status` end-to-end.
**Three-part closure:** same shape as Dataclass 1.
**Risk:** highest of the five — multiple hand-built dict construction sites.

### Dataclass 3: `RunStream` (SSE — biggest blast radius)
**File:** `agent_server/contracts/run.py:126–159`. Current: `tenant_id, run_id, event_type, payload, sequence, created_at`; required `tenant_id, run_id, event_type`.
**Target:** identical four lineage fields.
**Special wire-format:** `event_facade.py::render_sse_chunk` (77–99) hand-builds the SSE JSON body with a fixed key list (`run_id, event_type, sequence, payload`). MUST be widened to emit the four lineage fields. Source data exists: `StoredEvent._row_to_event` hydrates from SQL rows already carrying lineage since W33-F. Only the renderer must change.
**Regression test:** `tests/integration/test_sse_lineage_propagation.py` drives a real SSE stream with a re-attempt scenario, parses `data:` JSON client-side, asserts all four fields.
**Three-part closure:** standard; gate-evidence is integration, not unit.
**Risk:** RIA's parser is JSON; standard decoders ignore unknown keys — additive shape safe. Coordinate at sample-shape stage anyway.

### Dataclass 4: `StoredEvent` (HIGH part + M3 fold-in)
**File:** `hi_agent/server/event_store.py:20–71`. Already carries `parent_run_id, attempt_id, phase_id` (33–36) since W33-F; required `run_id, event_id, tenant_id`.
**Target (HIGH):** add `attempt_count: int = 0` to reach parity with RunResponse/RunStatus/RunStream — the missing fourth field for postmortem chain reconstruction.
**Target (M3):** `event_bus.py:116–118` reads `getattr(event, "parent_run_id", "") or ""` from a `RuntimeEvent` source that does NOT carry lineage (verified: `agent_kernel/kernel/contracts.py:67–107` has none). StoredEvent rows from `EventBus.publish` are structurally always empty on lineage. Two options:
- **Option A (preferred):** widen `RuntimeEvent` (`agent_kernel/kernel/contracts.py:67`, frozen+slots) with four lineage fields, defaults empty; producers populate. Touches every kernel emit-site.
- **Option B (narrower):** ride lineage in a `TenantContext` extension (per-request scope). Smaller diff but couples lineage to ambient context, not per-event ordering.
- **Recommendation:** Option A — `RuntimeEvent` is the authoritative event shape; lineage belongs on the event. Phase 4 task; coordinate with agent_kernel owners.
**SQL schema:** `_SCHEMA` (74+) `run_events` lacks `attempt_count` column — `ALTER TABLE ADD COLUMN` migration required.
**Validation:** under research/prod, `parent_run_id != ""` requires `attempt_count >= 1`.
**Regression test:** `tests/storage/test_stored_event_lineage_attempt_count.py` + `tests/storage/test_event_store_migration.py`.
**Three-part closure:** code + test + migration path is process-change evidence (no future PR can land runtime-store changes without column-mapping once `check_dataclass_spine_validation.py` enforces).
**Risk:** schema migration is the only non-additive step in A4. Phase migration before tightening; mismatch = production crash on first re-attempt event.

### Dataclass 5: `ReasoningTrace`
**Files:** `hi_agent/contracts/reasoning_trace.py:14–88` (`ReasoningTraceEntry`), 90–139 (`ReasoningTrace`).
**Current:** `ReasoningTrace`: `run_id, entries, tenant_id, user_id, session_id, project_id`; required `run_id`. Entry: `run_id, stage_id, step, kind, content, metadata, created_at, ...spine`; required `run_id, stage_id, kind`.
**Target:** add to `ReasoningTrace`: `parent_run_id: str = ""`, `attempt_id: str = ""`, `attempt_count: int = 0`. At entry level, add `phase_id: str = ""` (TRACE phase tag, distinct from `stage_id`) and `attempt_id: str = ""` so per-entry attribution is reconstructible within a re-attempt run.
**JSONL back-compat:** `asdict` writes; defaults `""`/`0` keep legacy files round-trippable.
**Validation:** under research/prod, trace-level `parent_run_id != ""` requires `attempt_id` and `attempt_count >= 1`. Entry-level lineage not required (entries inherit run-level).
**Regression test:** `tests/contracts/test_reasoning_trace_lineage.py` + JSONL round-trip with a W35-era fixture.
**Risk:** depends on `_write_trace_stub` (`run_manager.py:1255`) populating from `ManagedRun` — which already carries lineage per W34-F.2 (see M2).

---

## Per-minor-site plan (4 MEDIUM)

### M1. `OpHandle` parent_run_id/attempt_id/phase_id
**File:** `hi_agent/operations/op_store.py:27–68`.
**Current shape:** carries `op_id, backend, external_id, submitted_at, tenant_id, run_id, project_id, status, artifacts_uri, heartbeat_at, completed_at, error`. Required: `tenant_id, run_id, project_id`.
**Target shape:** add `parent_run_id: str = ""`, `attempt_id: str = ""`, `phase_id: str = ""`. SQL schema (`_CREATE` line 73+) needs three new columns. Same migration discipline as Dataclass 4.
**Validation:** Phase 2 — re-attempt invariant only.
**Regression test:** `tests/storage/test_op_handle_lineage.py` + migration test.

### M2. `ManagedRun` replayed-stub lineage
**File:** `hi_agent/server/run_manager.py:80–145` (class), 546–559 (replayed-stub construction).
**Defect:** ManagedRun carries `parent_run_id, attempt_id, phase_id` (116–118) per W34-F.2 — but the `replayed` outcome stub (551–559) constructs `ManagedRun(run_id=record.run_id, ..., outcome="replayed", ..., tenant_id=tenant_id)` and OMITS lineage. Defaults `""` pass spine validation but the idempotent-replay surface loses lineage.
**Target:** replayed-stub call MUST populate `parent_run_id`/`attempt_id`/`phase_id`/`profile_id` from the persisted `record`. Prerequisite: verify `hi_agent/server/run_store.py::RunRecord` carries them; if not, M2 transitively widens RunRecord (extra migration).
**Regression test:** `tests/integration/test_idempotent_replay_lineage.py` — submit re-attempt, replay via idempotency key, assert lineage carried.
**Risk:** if RunRecord lacks fields, scope expands.

### M3. `StoredEvent` runtime-event default — folded into Dataclass 4 above
Cross-reference: see Dataclass 4 wire-format note. The fix is at `event_bus.py:116–118` — once `RuntimeEvent` carries the lineage fields (Option A), the `getattr(..., "") or ""` defaults stop being silent and start being meaningful. Closure level for M3 = `verified_at_release_head` once the cross-loop SSE integration test passes.

### M4. `event_bus` `RuntimeEvent` silent default
**File:** `hi_agent/server/event_bus.py:96–125` (the `publish` method's StoredEvent construction).
**Defect:** lines 116–118 use `getattr(event, "parent_run_id", "") or ""`. This `getattr`-with-default pattern silently produces empty lineage when the source `RuntimeEvent` lacks the field. After Option A (Dataclass 4 / M3), the silent default becomes a typed read; under research/prod the M4 closure is to **convert the `getattr` calls to direct attribute reads** (`event.parent_run_id`) so a future regression where someone removes the field from RuntimeEvent fails loudly via AttributeError instead of silently emptying the lineage.
**Validation:** code-shape change only (no schema impact).
**Regression test:** `tests/unit/test_event_bus_lineage_propagation.py` — publish a `RuntimeEvent` with all four lineage fields set, assert the resulting `StoredEvent` carries them.

---

## Cross-cutting concerns

### Wire-format taxonomy
Every read endpoint that consumes one of these dataclasses, with field propagation status:

| Endpoint | Dataclass | Construction site | Risk |
|---|---|---|---|
| `POST /v1/runs` (create) | `RunResponse` | `agent_server/api/routes_runs.py` (existing routes) | low — frozen dataclass + asdict |
| `GET /v1/runs/{id}` | `RunResponse` | same | low |
| `POST /v1/runs/{id}/cancel` | `RunStatus` | `routes_runs_extended.py:46–53` via `_status_dict` | **HIGH — hand-built dict** |
| `GET /v1/runs/{id}` (status flavour) | `RunStatus` | `event_facade.py:54–66` | medium — facade builds RunStatus from `record` dict |
| `GET /v1/runs/{id}/events` (SSE) | `RunStream` (per chunk) wrapping `StoredEvent` row | `event_facade.py:77–99` `render_sse_chunk` | **HIGH — hand-built JSON body** |
| Any `/v1/runs/{id}/trace` (if present) | `ReasoningTrace` | TBD on route audit | medium |

`scripts/check_route_presence.py` (RIA G-RIA-13 per directive §3.2) will assert these endpoints exist; W36 A4 closure does NOT add new routes.

### Postmortem reconstruction handshake
RIA's `evolution_engine/postmortem.py` (R-W1 deliverable) walks attempt trees from these reads. A4 closure produces a **sample postmortem trace fixture** at `tests/fixtures/postmortem_sample_trace.json` that exercises every new field on every shape. Coordinate with RIA at the sample-shape stage (Phase 1 end, before tightening) so we don't ship a JSON shape RIA has to re-version. Consumer surface only — do not speculate on RIA's postmortem internals.

### Construction-site validation update
Update `scripts/check_dataclass_spine_validation.py::REQUIRED_VALIDATION_TARGETS` (lines 26–80+):
- All five A4 schema dataclasses are already enrolled (verified).
- Extend the script's per-target field check (current logic enforces presence-of-`__post_init__` only, not field set). Add a per-target `REQUIRED_FIELDS` map driving an AST walk that asserts the dataclass declares the four lineage attribute names. This shifts the gate from "has-validator" to "has-validator-AND-declares-spine-fields".
- M1/M2 sites enrol newly: `hi_agent/operations/op_store.py::OpHandle` (already enrolled per check), `hi_agent/server/run_store.py::RunRecord` (already enrolled), `hi_agent/server/run_manager.py::ManagedRun` (already enrolled).

### Contract digest re-snapshot
After Phase 2 lands, run the digest snapshot tool referenced in the W35 closure pattern (search `scripts/snapshot*` or `scripts/contract*` at execution time — the W36 delivery notice cites the actual command). RIA §3.3 requires `agent_server/contracts/` digest re-snapshot in the W36 delivery notice as proof of contract widening.

---

## Phased rollout

**Phase 1 (days 1–3) — Optional-additive shape.** Add Optional-with-default fields on all five HIGH dataclasses + `OpHandle` + `RunRecord` (M2 prerequisite). Update `_status_dict` and `render_sse_chunk` to emit them. Update `EventFacade.cancel` / `assert_run_visible` to read them from the record dict. NO `__post_init__` tightening yet. Land + ship.

**Phase 2 (days 4–7) — Tighten validation.** RIA confirms postmortem can populate fields under their R-W1 fixture. Tighten `__post_init__` under research posture for the re-attempt invariant (`parent_run_id != "" ⟹ attempt_id non-empty AND attempt_count >= 1`). Regression tests for both dev-allow and research-reject per Rule 11.

**Phase 3 (days 8–10) — SSE end-to-end.** Consumer-facing SSE shape verified end-to-end via integration test (`test_sse_lineage_propagation.py`) driving an actual SSE stream + parsing client-side. Coordinate sample-shape with RIA. Lock the digest.

**Phase 4 (days 11–14) — RuntimeEvent + minors + delivery.** Widen `agent_kernel/kernel/contracts.py::RuntimeEvent` (Option A). Close M1, M2, M3, M4. Run schema migrations. Re-snapshot contract digest. Write W36 delivery notice section per RIA §7 reporting format.

---

## Risk registry

- **R1 — SSE clients fail on extra fields.** Mitigation: standard JSON decoders ignore unknown keys; validate RIA parser tolerance at sample-shape coordination.
- **R2 — Phase 2 tightening breaks RIA fixtures.** Mitigation: phased — tighten only after RIA confirms R-W1 fixture populates fields.
- **R3 — Serialization round-trip drift** (dataclass→dict→json→bytes→dict→dataclass). Mitigation: per-dataclass round-trip test.
- **R4 — `ManagedRun` replayed-stub diverges.** Verified separate constructor at line 551. Integration test `test_idempotent_replay_lineage.py` gates.
- **R5 — RuntimeEvent widening breaks agent_kernel emit-sites.** Mitigation: defaults empty; verify slot+positional-allocation impact at AST level before merging Option A; fall back to Option B if cost too high.
- **R6 — Schema migration on populated SQLite DB.** Mitigation: `ALTER TABLE ADD COLUMN` with default; runtime migration test brings up pre-W36 DB file.
- **R7 — `RunRecord` widening (transitive M2 prerequisite).** Phase 1 must verify RunRecord shape before scoping M2.

---

## Acceptance criteria (W36 closure, per RIA §3.3 + §2.3)

- [ ] All 5 HIGH schema dataclasses gain attempt-chain fields (`parent_run_id`, `attempt_id`, `attempt_count`, `phase_id`).
- [ ] `agent_server/contracts/` digest re-snapshot in W36 delivery notice.
- [ ] Construction-site `__post_init__` posture-aware validation (re-attempt invariant under research/prod, dev warns).
- [ ] Three-part closure (Rule 15) per dataclass with `level: verified_at_release_head` minimum.
- [ ] All 4 MEDIUM minor sites closed (`OpHandle`, `ManagedRun` replayed-stub, `StoredEvent` runtime-event default folded into the RuntimeEvent widening, `event_bus` silent default converted to direct attribute read).
- [ ] Sample postmortem reconstruction trace fixture produced + agreed with RIA at sample-shape stage.
- [ ] Wire-format end-to-end test: SSE integration test parses lineage from a re-attempt scenario.
- [ ] `scripts/check_dataclass_spine_validation.py` extended to assert per-target `REQUIRED_FIELDS` (gate-evidence for process-change closure).
- [ ] Schema migration for `run_events` and `ops` tables runs cleanly against a pre-W36 DB file.
- [ ] Capability maturity: A4 closure reaches L2 (public-contract published + posture-aware default-on after Phase 2) — does NOT reach L3 until RIA's R-W1 confirms population in production fixtures.
