# Wave 35 Plan — Systematic Audit Follow-ups

**Date:** 2026-05-05 (drafted at W34 close)
**Predecessor:** W34 manifest `2026-05-05-77222f8b`, verified=75.0
**Source audits:** 6 parallel audit agents dispatched at W34 close (tenant isolation beyond 4 registries; spine completeness across all dataclasses; lineage population at construction sites; idempotency middleware coverage + TTL; posture coverage; R-AS-1 layering).

---

## 0. Disposition Summary

The W34-close systematic audit surfaced ~30 hidden findings beyond the W34 BLOCKERs.
Approximately one-third are addressed in the W34+ patch batch (TIER 1 in this document); the
remainder is W35 carryover.

**TIER 1 (W34+ patch, executed at W34 close):**
- run_store.py multi-method tenant scoping (D1–D4 from audit A)
- StoredEvent lineage in event_bus + run_manager (audit C MISSING-1/2)
- runner_lifecycle audit-emit tenant_id (audit A D5)
- Idempotency-Key length cap + Unicode NFC (audit D MEDIUM)
- Spine `__post_init__` on RunRecord / StoredEvent / ManagedRun (audit B durable trio)

**TIER 2 (W35 carryover):**

### W35-T1 — Frozen-contract spine validation (audit B contract group)

13 agent_server contract dataclasses carry tenant_id but lack `__post_init__`:

- `agent_server/contracts/run.py::RunRequest, RunResponse, RunStatus, RunStream`
- `agent_server/contracts/tenancy.py::TenantContext, TenantQuota, CostEnvelope`
- `agent_server/contracts/skill.py::SkillRegistration, SkillVersion, SkillResolution`
- `agent_server/contracts/memory.py::MemoryReadKey, MemoryWriteRequest`
- `agent_server/contracts/streaming.py::Event, EventCursor, EventFilter`
- `agent_server/contracts/llm_proxy.py::LLMRequest, LLMResponse`

Each addition mutates a frozen contract module → digest re-snapshot required.
Recommended approach: **single batched commit + one re-snapshot** to minimise digest churn.

**Acceptance criteria:**
- All 13 classes acquire posture-aware `__post_init__` mirroring `ReasoningTrace` (research/prod
  raises `SpineCompletenessError`; dev warns).
- `scripts/check_dataclass_spine_validation.py::REQUIRED_VALIDATION_TARGETS` extended.
- Contract digest re-snapshot recorded in W35 delivery notice.

### W35-T2 — WEAK_PARITY posture sites (audit E)

Eight call sites where strict-posture branch raises but dev-posture branch is missing (or
identical), breaking Rule 11's permissive-dev / fail-closed-prod parity:

| Site | File:line | Severity |
|---|---|---|
| `LongRunningOpStore.create` | `hi_agent/operations/op_store.py:101-105` | HIGH |
| `SkillDefinition.__post_init__` | `hi_agent/skill/definition.py:193-196` | HIGH |
| `RunManager._resolve_workspace` (strict) | `hi_agent/server/run_manager.py:411-415` | MEDIUM |
| `RunRetrospective.__post_init__` and 3 sibling evolve contracts | `hi_agent/evolve/contracts.py:133/163/197/235` | MEDIUM |
| `recovery.alarm_recovery_reenqueue_disabled` | `hi_agent/server/recovery.py:61-82` | MEDIUM |

**Acceptance criteria per site:** dev branch logs WARNING + falls back gracefully; research/prod
branch raises with structured envelope; new test in `tests/posture/test_*.py` covering both
postures.

### W35-T3 — INVERTED posture (audit E CRITICAL)

`hi_agent/server/run_manager.py:418-432` — strict posture issues `DeprecationWarning` and accepts
middleware tenant_id when body tenant_id is missing; dev posture has no equivalent fallback.
Strict is *more permissive* than dev.

**Resolution:** restructure so both postures honour the same body→middleware fallback (it is the
right behaviour) OR remove the strict-only fallback. Decision pending root-cause review of why
the deprecation window was opened only for strict.

**Acceptance criteria:**
- Behaviour symmetry: same fallback under both postures, OR strict raises and dev raises.
- Test `tests/posture/test_run_manager_body_tenant_id_fallback.py` covering both directions.
- Three-part closure (Rule 15).

### W35-T4 — Idempotency TTL purge (audit D HIGH)

`IdempotencyStore.expires_at` is stored but never queried for cleanup. Records accumulate
indefinitely; SQLite database grows unbounded.

**Architecture proposal:**
1. Background asyncio task in `agent_server/runtime/lifespan.py` that runs every N minutes.
2. `IdempotencyStore.purge_expired(now=...) -> int` returns count of deleted rows.
3. New Prometheus counter `hi_agent_idempotency_purged_total{tenant_id}`.
4. Lazy-purge fallback in `reserve_or_replay` (delete-then-insert if expired record found).

**Acceptance criteria:**
- Background task scheduled in lifespan startup; cancelled on shutdown.
- `tests/integration/test_idempotency_ttl_purge.py` exercises both lazy and proactive purge.
- Disk-growth regression test: insert 10,000 records, run purge, assert byte size shrinks.

### W35-T5 — Idempotency body hash hardening (audit D MEDIUM)

Two MEDIUM-severity hash defects:
- **Unicode normalization missing** (NFC vs NFD). FIXED in W34+ TIER 1 (T1e).
- **Float canonicalization missing** (`1` vs `1.0` hash differently). DEFER — fixing this is a
  *breaking change* for any tenant with retries-in-flight. Need migration plan + deprecation
  window.

**Acceptance criteria for W35:**
- Document the float-canonicalization plan in
  `agent_server/contracts/idempotency.py` Limitations section.
- Add CI gate that reports (does not fail) any new mutating route accepting non-string-keyed
  bodies; reviewer must justify the canonicalization choice.

### W35-T6 — Idempotency observability (audit D MEDIUM)

No metrics on:
- Idempotency cache age distribution
- Replay rate (cache hit vs new key)
- Conflict rate (body mismatch on same key)
- Purged-record count

**Acceptance criteria:**
- 4 Prometheus metrics emitted by `IdempotencyMiddleware` and `IdempotencyStore`.
- `docs/observability/idempotency-metrics.md` documents each metric's cardinality + use case.

### W35-T7 — agent_server CONFIG layer expansion (audit G follow-up; deferred)

Today's `agent_server/config/` carries `settings.py` (3 fields) + `version.py` (5 constants).
Future v2 contract work + per-tenant config overrides will require additional surfaces. Track as
W35 only if v2 work is approved; otherwise W36.

### W35-T8 — Idempotency MCP route coverage (audit D MEDIUM)

`POST /v1/mcp/tools/{name}` is conditionally included via `include_mcp_tools=True`; the route is
currently L1 stub (no real MCP execution). When the route lands real execution it will need the
idempotency middleware coverage explicitly verified — currently the conditional registration
flow leaves a gap if `include_mcp_tools` is set without `idempotency_facade`.

**Acceptance criteria:**
- Boot-time assertion in `build_app` that `include_mcp_tools=True` implies `idempotency_facade
  is not None` (or fail loudly otherwise).
- `tests/integration/test_mcp_tools_idempotency.py` covering replay + conflict on the MCP route.

---

## 1. Out of Scope for W35

- The `evidence_provenance` cap factor remains unchanged (RIA W31 §6).
- The 75.0 readiness cap is unchanged unless soak evidence is delivered.
- Front-end / client SDKs.
- Cross-region multi-process idempotency (requires external coordinator; out of scope).

---

## 2. Risk Note

W35-T1 (contract spine validation) and W35-T3 (INVERTED posture) both touch hot-path code per
CLAUDE.md Rule 8. T3 invariance demands a fresh T3 gate run AFTER those land. Plan one
T3 re-run at W35 close.

---

**End of Wave 35 plan.**
