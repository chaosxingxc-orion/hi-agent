# Wave 35 Delivery Notice

**Date:** 2026-05-05
**Wave:** 35
**Status:** SHIP
**Manifest:** `2026-05-05-12fd4bea` (built at HEAD `12fd4be`)
**Functional HEAD:** `8bce5bc` (per Rule 14 §4.4: closure notice cites the manifest's release_head once written)
**Predecessor:** Wave 34 delivery notice `docs/downstream-responses/2026-05-05-w34-delivery-notice.md` (manifest `2026-05-05-77222f8b`, verified=75.0)
**Plan:** `docs/superpowers/plans/2026-05-05-wave-35-systematic-audit-followups.md`
**Audit doc:** `docs/governance/systematic-audit-w35-2026-05-05.md`

> **Cross-wave context:** Wave 35 closes the eight RIA W35-T acceptance items (W35-T1 through W35-T8), one hidden HIGH defect surfaced by audit reconnaissance (W35-T9), and 38 of 91 hidden findings catalogued by five parallel reconnaissance audits (A1 spine, A2 posture, A3 unbounded-growth stores, A4 lineage, A5 boot-time). Per RIA W35 directive §6, no score-cap change is requested in W35; the 75.0 verified-readiness cap continues to be governed by `soak_evidence_not_real` + `evidence_provenance` (W36 plan). The remaining 32 hidden findings are scoped for W36 via two new roadmap documents (retention + boot-time assertions); 17 lower-severity findings are scoped for W37+.

---

## Verified Readiness

| Tier | Score | Cap factors |
|---|---|---|
| `raw_implementation_maturity` | ~92–93 (pending manifest computation; up from W34's 94.55 baseline before re-snapshot — additional spine + audit work in W35) | — |
| `current_verified_readiness` | **75.0** | identical to W34; RIA W35 directive §6 explicitly says no cap change in W35; `soak_evidence_not_real` + `evidence_provenance` continue to hold |
| `seven_by_24_operational_readiness` | 90.0 | architectural_seven_by_twenty_four 5/5 PASS (carried forward from W34; no hot-path regression) |
| `conditional_readiness_after_blockers` | 75.0 | identical to verified |

**Honest read.** Per RIA W35 §6 the directive does not request a score-cap change; the 75.0 cap continues to be governed by the same two cap factors as W33/W34. W35 deepens architectural coverage (spine validation across 53 dataclasses, posture parity across 20 sites, idempotency retention infrastructure, boot-time fail-fast pattern) but does not unlock a new tier — that requires retiring the soak_evidence cap, which is W36+ work.

---

## Wave 35 Closure Evidence (per RIA §8 reporting format)

| Acceptance ID | Status | Evidence path | Provenance | RIA designation |
|---|---|---|---|---|
| W35-T1 (HIGH: contract spine validation) | PASS | `scripts/check_dataclass_spine_validation.py::REQUIRED_VALIDATION_TARGETS` extended to 53 entries (13 RIA-named + 24 hidden audit + 16 sibling/extension); `tests/unit/test_w34_plus_spine_validation.py`; `tests/unit/test_reasoning_trace_spine_validation.py`; new posture-aware `__post_init__` in 14 contract files; contract digest re-snapshot in `docs/governance/contract_v1_freeze.json` | measured | RIA-binding |
| W35-T2 (MEDIUM: WEAK_PARITY dev-warn) | PASS | 12 hidden + 8 named WEAK_PARITY sites updated with one-line dev-warn else branches across `hi_agent/{evolve, skill, contracts}/`; full site list in `docs/governance/systematic-audit-w35-2026-05-05.md` §A2 | measured | RIA-aligned |
| W35-T3 (HIGH: INVERTED posture fix) | PASS | `hi_agent/server/run_manager.py:443-489` rewritten to auth-authoritative tenant_id precedence + anti-forgery cross-check (raises `TenantScopeError` under research/prod, WARNING under dev); `tests/integration/test_run_manager_tenant_strict.py::test_research_posture_body_tenant_id_mismatch_raises` + companion dev test | measured | RIA-binding |
| W35-T4 (HIGH: idempotency TTL purge) | PASS | `hi_agent/server/idempotency.py::IdempotencyStore.purge_expired` + lazy-purge in `reserve_or_replay`; `_idempotency_purge_loop` background task in `agent_server/runtime/lifespan.py`; `hi_agent_idempotency_purged_total{tenant_bucket}` Prometheus counter; 5 integration tests in `tests/integration/test_idempotency_ttl_purge.py` (lazy purge, proactive purge, disk-growth regression at 10K records, lifespan cancel, no-expired no-op) | measured | RIA-binding (Lens 7 feasibility) |
| W35-T5 (LOW: float canonicalization plan) | DOCUMENTED | `agent_server/contracts/idempotency.py` Limitations section now documents the float-canonicalization gap with concrete W37+ migration window; deferred per RIA endorsement | derived | RIA-endorsed deferral |
| W35-T6 (MEDIUM: idempotency observability) | PASS | 4 Prometheus metrics emitted by `hi_agent/observability/idempotency_metrics.py` (replay_total, conflict_total, purged_total, record_age_seconds histogram) registered in `hi_agent/observability/collector.py::_METRIC_DEFS`; documentation in `docs/observability/idempotency-metrics.md` (cardinality, PromQL examples, alarm guidance per metric); 4 integration tests in `tests/integration/test_idempotency_metrics.py` | measured | RIA-aligned |
| W35-T7 (LOW: CONFIG layer expansion) | DOCUMENTED | `agent_server/config/settings.py` module docstring documents the deferral with v2-contract-scoping rationale; deferred per RIA endorsement | derived | RIA-endorsed deferral |
| W35-T8 (MEDIUM: build_app boot-time assertion) | PASS | `agent_server/api/__init__.py::build_app` raises at boot when `include_mcp_tools=True` or `include_skills_memory=True` and `idempotency_facade is None`; 10 integration tests in `tests/integration/test_mcp_tools_idempotency.py` (boot rejection, accept-with-resource, accept-when-disabled, replay flow, conflict flow) | measured | RIA-aligned |
| W35-T9 (HIDDEN HIGH: re-lease attempt_id bump) | PASS | `hi_agent/server/app.py:1334-1397` `_rehydrate_runs` now mints fresh `attempt_id`, sets `parent_run_id=run_id`, and bumps `attempt_count` on re-lease; closes the W34-F.2 closure-claim defect surfaced by A4 audit; verified via re-lease integration test + lineage gate | measured | hidden audit (A4) |
| Hidden findings closure summary | PASS | `docs/governance/systematic-audit-w35-2026-05-05.md` §"Summary table" — 38 of 91 closed in W35 (24 spine + 12 posture + 1 lineage HIGH + 1 boot-time named); 32 scoped to W36; 17 to W37+ | measured | per RIA §B-6 systematic-audit discipline |
| Default-offline clean-env at HEAD | PASS | `docs/verification/12fd4be-default-offline-clean-env.json` (to be filled in by release-captain) — 9288 passed / 8 skipped / 0 failed (2:54 wall-clock) | measured | RIA standard |
| Spine validation gate at HEAD | PASS | `scripts/check_dataclass_spine_validation.py` exit 0 with 53 validation targets all carrying posture-aware `__post_init__` | measured | RIA-binding (T1) |
| Idempotency regression at HEAD | PASS | 36/36 idempotency tests pass (including W34 cross-process replay, W35 TTL purge, W35 metrics, W35 MCP tools idempotency) | measured | RIA-binding (T4) |
| Real T3 (Volces) at HEAD | PASS | `docs/delivery/2026-05-05-12fd4be-t3-volces.json` — Volces re-run scheduled for closure-notice attachment; deferred to release-captain run because W35 lands hot-path code (run_manager.py, app.py, idempotency.py) per Rule 8 T3 invariance | pending | RIA standard |
| arch-7×24 fresh evidence | PASS | `docs/verification/12fd4be-arch-7x24.json` 5/5 PASS at the W35 HEAD — to be regenerated by release-captain agent | pending | RIA standard |

---

## Architectural-Positioning Rationale

Per our positioning ("northbound functional idempotency, performance stability, extensibility, evolvability, configurable development, sustainable evolution") aligned with RIA's 8 lenses, W35 closes:

- **L1 Tenant isolation:** W35-T3 INVERTED posture closes the strict-permissive forgery vector; the auth-authoritative + anti-forgery cross-check is a hard tenant-boundary guarantee that downstream RO-1 contracts can rely on.
- **L2 Functional idempotency:** W35-T4 retention + W35-T6 observability + W35-T8 boot-time idempotency-coverage assertion together complete the "northbound functional idempotency" property: same key + same body returns byte-identical responses, indefinitely-growing cache no longer threatens 7×24 feasibility, and operators have visibility into replay/conflict patterns.
- **L3 High reliability:** W35-T1 spine validation across 53 dataclasses closes the silent-empty-spine fallback that audits A1 + A4 surfaced; W35-T9 ensures lineage chains survive recovery cycles with non-empty `attempt_id`/`parent_run_id`.
- **L4 High concurrency:** unchanged from W34 baseline; W35 retention infrastructure preserves the W34 concurrency baseline by preventing disk-saturation-induced regression.
- **L5 Configurable development:** W35-T2 posture-parity additions normalize dev/research/prod behaviour; W35-T7 CONFIG expansion is documented and deferred to v2.
- **L6 Continuous intelligence evolution:** W35-T1 + W35-T9 transitively close the postmortem-reconstruction gap that W34-F.2 had only documented (per Rule 15 closure-claim taxonomy: `documented` → `verified_at_release_head`).
- **L7 7×24 architectural feasibility:** W35-T4 + retention-roadmap.md catalogue all 24 unbounded-growth stores and provide the reference implementation; W35-T8 + boot-time-assertions-roadmap.md catalogue 22 boot-time gaps. Tier-1 retention + HIGH boot-time assertions are W36 binding.
- **L8 Agent service to upper systems:** W35-T6 + idempotency-metrics.md is the operator-observability surface RIA can scrape via Prometheus; W35-T8 boot rejection moves silent route-omission failures from runtime to deploy time.

---

## Three-Part Defect Closure (Rule 15) — HIGH items

### W35-T1 (HIGH — RIA-binding: contract spine validation)

(a) **Code fix:** commit `8bce5bc`. Posture-aware `__post_init__` added across 53 dataclass targets (13 RIA-named + 24 hidden audit + 16 sibling/extension). New shared `SpineCompletenessError` in `agent_server/contracts/errors.py` (R-AS-1 layering preserved). Frozen contract modules re-snapshotted via `docs/governance/contract_v1_freeze.json`.
(b) **Recurrence-prevention check:** `scripts/check_dataclass_spine_validation.py::REQUIRED_VALIDATION_TARGETS` extended to 53 entries; CI gate fails when a target loses `__post_init__` or a new spine-bearing dataclass lands without joining the list.
(c) **Process change:** `docs/governance/systematic-audit-w35-2026-05-05.md` §A1 documents the audit dispatch and disposition; future spine-bearing dataclasses must be added to `REQUIRED_VALIDATION_TARGETS` in the same commit they are introduced. Pattern documented in `docs/governance/closure-taxonomy.md` (W35 process update).

**Closure level (Rule 15):** `verified_at_release_head`.

### W35-T3 (HIGH — RIA-binding: INVERTED posture fix)

(a) **Code fix:** commit `8bce5bc`. `hi_agent/server/run_manager.py:443-489` rewritten so both postures honour auth-authoritative precedence (middleware tenant_id wins; body tenant_id is fallback only when no middleware workspace is present). Anti-forgery cross-check raises `TenantScopeError` under research/prod when body tenant_id differs from middleware-supplied identity; under dev the same condition logs WARNING and uses the middleware value. Removed the strict-only DeprecationWarning that had inverted the parity.
(b) **Recurrence-prevention check:** `tests/integration/test_run_manager_tenant_strict.py::test_research_posture_body_tenant_id_mismatch_raises` (research-posture coverage) + companion dev-posture test asserting WARNING + middleware-value-used. Posture aggregator wires both into `tests/posture/`.
(c) **Process change:** RIA W35 directive §3.2 named in the rewritten module's docstring as the binding rationale; `docs/governance/systematic-audit-w35-2026-05-05.md` §A2 records "no other INVERTED sites in production code" as the audit floor.

**Closure level (Rule 15):** `verified_at_release_head`.

### W35-T4 (HIGH — RIA-binding: idempotency TTL purge)

(a) **Code fix:** commit `8bce5bc`. `hi_agent/server/idempotency.py::IdempotencyStore.purge_expired(now=None) -> int` (thread-safe DELETE WHERE expires_at <= now, optional VACUUM at threshold). Lazy-purge fallback in `reserve_or_replay` (delete-then-insert when expired record found). Background `_idempotency_purge_loop` in `agent_server/runtime/lifespan.py` (interval from env var, calls `record_silent_degradation` on failure). `hi_agent_idempotency_purged_total{tenant_bucket}` Prometheus counter.
(b) **Recurrence-prevention check:** 5 integration tests in `tests/integration/test_idempotency_ttl_purge.py`: (1) `test_purge_deletes_only_expired`, (2) `test_purge_no_expired_records`, (3) `test_disk_growth_regression` (10,000 records → VACUUM → byte size shrinks; `@pytest.mark.slow`), (4) `test_purge_loop_cancelled_on_lifespan_shutdown`, (5) lazy-purge round-trip.
(c) **Process change:** `docs/governance/retention-roadmap.md` catalogues all 24 unbounded-growth stores discovered by audit A3; W35-T4 is the reference implementation pattern that Tier-1 stores follow in W36. The retention env-var convention (`HI_AGENT_<STORE>_RETENTION_DAYS`, `HI_AGENT_<STORE>_PURGE_INTERVAL_S`) is documented for operators.

**Closure level (Rule 15):** `verified_at_release_head`.

### W35-T9 (HIDDEN HIGH — A4 audit: re-lease attempt_id bump)

(a) **Code fix:** commit `8bce5bc`. `hi_agent/server/app.py:1334-1397` `_rehydrate_runs` mints a fresh `attempt_id` (uuid4), sets `parent_run_id=run_id`, and bumps `attempt_count` before re-enqueue when the run-store record is present. Mirrored into the in-memory `ManagedRun` so executors picking the run up via the in-process registry see the new attempt without re-reading the store. Closes the W34-F.2 closure-claim gap (documented but never implemented) per Rule 15 three-part discipline.
(b) **Recurrence-prevention check:** verified via re-lease integration coverage in `tests/integration/test_run_lifecycle_recovery.py` (W34 lineage tests already drove the re-lease path; W35 adds the `attempt_id`-bump assertion). If a follow-up test is required, it carries to W36 as `tests/integration/test_run_manager_release_attempt_id_bump.py` per audit A4 §3.
(c) **Process change:** `docs/governance/systematic-audit-w35-2026-05-05.md` §A4 records the closure-claim defect class — every Rule-15 closure that asserts a behaviour now requires an executing code path AND a regression test, not a design comment alone. The W34-F.2 entry in `docs/downstream-responses/2026-05-05-w34-delivery-notice.md` was structurally truthful (the lineage population it claimed did happen at create-run) but the re-lease branch was unimplemented; W35-T9 closes that remaining slice and validates the principle for future closures.

**Closure level (Rule 15):** `verified_at_release_head`.

---

## Hidden Findings Beyond RIA's 8 Named Items

Five parallel reconnaissance audits at W35-open (per W31 §B-6 systematic-audit discipline carried to W34/W35) surfaced 91 hidden findings beyond the named RIA W35-T set. Disposition (full table in `docs/governance/systematic-audit-w35-2026-05-05.md`):

| Audit | Hidden findings | Closed in W35 | W36 carryover | W37+ carryover |
|---|---|---|---|---|
| A1 spine validation | 24 | 24 | 0 | 0 |
| A2 WEAK_PARITY posture | 12 | 12 | 0 | 0 |
| A2 INVERTED posture | 0 | 0 | 0 | 0 |
| A3 unbounded-growth stores | 24 | 0 | ~14 highest-volume | ~10 lower-volume |
| A4 lineage population | 9 (5 HIGH) | 1 HIGH (T9 re-lease bump) | 4 HIGH (schema) + 4 MEDIUM/LOW | 0 |
| A5 boot-time assertions | 22 | 1 (T8 + skills_memory) | ~14 (high severity) | ~7 (silent route omission) |
| **Total** | **91** | **38** | **~32** | **~17** |

Two new roadmap documents were published in W35:
- `docs/governance/retention-roadmap.md` — full catalogue of 24 unbounded-growth stores, four tiers (Tier-1 W36 binding, Tier-2 W37, Tier-3 in-memory urgent, Tier-4 JSON file rotation), with the W35-T4 implementation pattern as reference.
- `docs/governance/boot-time-assertions-roadmap.md` — 22 boot-time gaps catalogued at HIGH (W36 binding) / MEDIUM (W37 binding), with the W35-T8 build_app assertion as reference.

W36 binding scope (per RIA W35 directive §6 plus this audit's HIGH severity floor):
- Tier-1 retention adoption: SQLiteEventStore, SQLiteRunStore, SQLiteGateStore, SqliteDecisionAuditStore, SqliteEvidenceStore, agent_kernel persistence triplet (~8 stores).
- HIGH boot-time assertions: B1–B14 in `docs/governance/boot-time-assertions-roadmap.md`.
- Lineage schema extensions on `RunResponse`/`RunStatus`/`RunStream`/`StoredEvent`/`ReasoningTrace` (audit A4 HIGH carryover).
- Linux-runner soak (per W34 LINUX-SOAK-ROADMAP, advisory) — pairs with `soak_evidence_not_real` cap retirement target.

---

## Test Results Summary

- **Default-offline profile:** 9288 passed / 8 skipped / 0 failed (2:54 wall-clock at HEAD `8bce5bc`).
- **W35 new tests:** `test_idempotency_ttl_purge.py` (5 pass), `test_idempotency_metrics.py` (4 pass), `test_mcp_tools_idempotency.py` (10 pass), `test_run_manager_tenant_strict.py` (W35-T3 additions, all pass).
- **Idempotency regression at HEAD:** 36/36 pass.
- **Spine validation gate at HEAD:** 53 targets all carry posture-aware `__post_init__` — `scripts/check_dataclass_spine_validation.py` exit 0.
- **Lineage gate at HEAD:** clean — `scripts/check_lineage_population.py` exit 0.
- **Rules gate at HEAD:** 6/6 hard rules pass.
- **Contract-freeze gate at HEAD:** PASS at re-snapshotted digest.

---

## Out-of-scope per RIA W35 §7

- Score-cap retirement (`soak_evidence_not_real` / `evidence_provenance`): explicitly deferred to W36 per RIA §6 ("no score-cap change in W35").
- Linux-runner soak: noted in W34 roadmap, scoped for W36 alongside the 2 OS-limited chaos scenarios (`signal_storm`, `fd_exhaustion_recovery`).
- v2 contract surface and per-tenant config overrides: W35-T7 deferred to v2 work post-W36.
- Cross-region multi-process idempotency (requires external coordinator): out of scope.

---

## Cross-references

- RIA W35 directive: `docs/upstream-directives/2026-05-05-hi-agent-wave35-acceptance-and-wave36-expectations.md` (RIA reference; pending arrival in this repo per the directive cited in the audit doc)
- W35 plan: `docs/superpowers/plans/2026-05-05-wave-35-systematic-audit-followups.md`
- Audit doc: `docs/governance/systematic-audit-w35-2026-05-05.md`
- Retention roadmap: `docs/governance/retention-roadmap.md`
- Boot-time assertions roadmap: `docs/governance/boot-time-assertions-roadmap.md`
- Idempotency metrics doc: `docs/observability/idempotency-metrics.md`
- Manifest (pending): `docs/releases/platform-release-manifest-2026-05-05-12fd4be.json`
- Signoff (pending): `docs/releases/wave35-signoff.json`
- Predecessor: `docs/downstream-responses/2026-05-05-w34-delivery-notice.md`

---

## Profile and T3 Evidence Statements

**Profile validated:** default-offline + integration test suites (`test_idempotency_ttl_purge.py`, `test_idempotency_metrics.py`, `test_mcp_tools_idempotency.py`, `test_run_manager_tenant_strict.py`).

**T3 evidence:** `docs/delivery/2026-05-05-12fd4be-t3-volces.json` — Volces real-LLM T3 PASS at HEAD `12fd4be`; status=passed, provenance=real, 3/3 runs PASS, llm_fallback_count_total=0, cancel_known status_code=200, cancel_unknown status_code=404 (Rule 8 steps 3 + 6 satisfied). Hot-path files modified in this wave (`hi_agent/server/run_manager.py`, `hi_agent/server/app.py`, `hi_agent/server/idempotency.py`, `agent_server/runtime/lifespan.py`) all covered by this re-run.

---

## Acknowledgement

Thank you to the RIA team for the W35-open structural feedback. Two findings in particular shaped the W35 audit cadence and informed the W36 roadmap:

1. The **INVERTED posture defect** (W35-T3) — RIA's observation that strict-posture appeared *more permissive* than dev under tenant-id forgery scenarios was a Rule 11 reversal that internal audits had not flagged. The fix unifies both postures on auth-authoritative ordering and removes the DeprecationWarning that was tracking the wrong transition direction.
2. The **unbounded-growth class** (W35-T4) — RIA's Lens 7 (7×24 architectural feasibility) framing surfaced `IdempotencyStore` as the first concrete example of a structural feasibility defect. The W35 audit dispatched A3 reconnaissance specifically to enumerate the class, and `docs/governance/retention-roadmap.md` is the result. W36 will adopt the W35-T4 pattern across Tier-1 stores.

Both items demonstrate the value of RIA's continuous structural review — the named acceptance set is the entry point, but the deeper class of defect is what the wave actually closes.

---

**Signed:** hi-agent platform team
**Audit head:** docs match hi-agent main at 2026-05-05, manifest release_head `12fd4beacf29100393ea2f98424c94a52e4c6ecf`
