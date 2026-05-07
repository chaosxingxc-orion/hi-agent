> **Mirrored from RIA on 2026-05-07.**
> Source: D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-audit-2026-05-07.md
> Maturity in this repo: M2 (mirrored to docs/upstream-directives/).
> See `docs/superpowers/plans/2026-05-07-wave-36-plan-index.md` for hi-agent's W36 §0 disposition.
> No content changes from source other than this preamble.

# hi-agent W35 Corrective Acceptance Audit (RIA-internal)

**Date:** 2026-05-07
**Document maturity:** M1 — internally reviewed
**Audit author:** RIA team
**Audit basis:** four parallel code-level verification agents dispatched against `D:\chao_workspace\hi-agent\` at HEAD `ad521c07` (W35-corrective-CLOSE).

This audit produces the M1 evidence underwriting `hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md`.

---

## 0. Audit method

Four parallel verification agents were dispatched, each with a self-contained brief and read-only access to the hi-agent repository:

1. **Agent 1** — C-1 (label revert) + C-2 (provenance cap lifecycle_note) at code level.
2. **Agent 2** — C-3 (W35-T9 regression test) + C-4 (dev-side WARNING test) + closure-level promotion.
3. **Agent 3** — §5.1 (wave-ledger drift gate) + §5.2 (release-captain artifact disposition) + score-drop investigation.
4. **Agent 4** — W36 plan disposition for A3 / A5 / A4 binding items + soak / Postgres / §0 disposition.

Findings are synthesised below. Each line carries a file:line citation or commit SHA.

---

## 1. W35 corrective verification matrix

| Item | Status | Key evidence |
|---|---|---|
| **C-1** label revert | **VERIFIED M2** | 4 metrics confirmed `{tenant_id}` raw at `idempotency_metrics.py:88,108,137,158`. Policy paragraph in `idempotency-metrics.md:185-204` AND `observability/ARCHITECTURE.md:288-302` (ADR-OBS-2). Regression `test_metric_label_set` uses frozenset for explicit drift guard at `test_idempotency_metrics.py:236-307`. No orphan `tenant_bucket` references in production emit paths; `hi_agent_llm_tokens_total` (W31 cardinality precedent) retained as documented exception. |
| **C-2** `provenance_unknown_or_synthetic` | **VERIFIED M2** | `score_caps.yaml:147-152` `lifecycle_note` declares **reading (a) implicit-resolution** with: (i) verification grep evidence at W35 release_head `24cfa0a6` and post-W34 heads showing zero `provenance:synthetic|unknown` files; (ii) re-fire trigger named ("when any JSON in `docs/verification/` or `docs/delivery/` acquires `provenance:synthetic` or `provenance:unknown`"); (iii) detection scope at `build_release_manifest.py::_compute_cap` ~line 520. `cap_factors_active` correctly omits the rule. |
| **C-3** W35-T9 regression test | **VERIFIED M2 with caveat** | `tests/integration/test_run_manager_release_attempt_id_bump.py` (135 lines, 3 tests, 3/3 PASS). Structural assertions: `bumped.attempt_id != "initial-A"` AND `uuid.UUID(bumped.attempt_id).version == 4`; `bumped.parent_run_id == run_id`; `attempt_count` `2→3` AND `0→1`. Helper `_bump_attempt_id_on_release` extracted at `app.py:1218-1275`; `_rehydrate_runs` calls helper at `app.py:1410-1413`; mirror-update at `app.py:1417-1436` preserved. **Caveat**: in-memory `ManagedRun` mirror update is not asserted at this layer (team's acknowledged scope choice — "without spinning up the full FastAPI startup harness"). |
| **C-4** W35-T3 dev-side WARNING | **VERIFIED M2** | `tests/integration/test_run_manager_tenant_strict.py:181-223::test_dev_posture_body_tenant_id_mismatch_warns_and_uses_middleware`. Caplog `WARNING` assertion present at line 215-220 with both tenant ids named in the message; middleware-value-used assertion at line 207. Both directions (research-raises + dev-warns-and-uses-middleware) covered with explicit assertions. 8/8 tests PASS. |
| **§5.1** wave-ledger drift | **VERIFIED M2** | `current-wave.txt:1` and `recurrence-ledger.yaml:9` both `35`. `scripts/check_wave_consistency.py` extended with 5th source via new helper `_recurrence_ledger_current_wave()` at L64-L88; sources dict updated at L207-L213. Regression test `tests/integration/test_check_wave_consistency_ledger.py` (3 cases: drift-fails, agree-passes, missing-ledger-does-not-block). CI wired at `.github/workflows/release-gate.yml:213`. Self-documented at `recurrence-ledger.yaml:591-608` entry W32-D-recurrence with `current_closure_level: verified_at_release_head`. |
| **§5.2** captain artifacts | **VERIFIED M2 with asymmetry** | Path (a) chosen: re-rolled clean-env at intermediate HEAD `5b1e4d25`; arch-7×24 at `5ba9bb7`; T3 DEFERRED record at `6b817f8`. Final HEAD `ad521c07` carries no own evidence file (the `*ad521c07*` glob returns 0 hits). Final-HEAD divergence is **declared** in `wave35-signoff.json::evidence_exemption` block: `kind: "none"`, all 5 required fields populated. `scripts/check_signoff_evidence_exemption.py` enforces 5-field + enum + gov-only-gap reality check; CI wired at `release-gate.yml:379`. Live gate run: PASS exit 0. |

**Documentation lag** (not a contract defect): `docs/downstream-responses/2026-05-05-w35-corrective-response.md` still lists C-1..C-3 as IN-PROGRESS / TBD because the document has not been reissued post-track-land. Canonical artifacts (code at HEAD `ad521c07`, `score_caps.yaml`, signoff `cap_factors_active`) are the binding authority and they confirm closure.

---

## 2. Score-drop diagnosis (75.0 → 72.0)

| Wave | `cap_factors_active` | Calculation | Result |
|---|---|---|---|
| W35 ship `bd4d38d5` | `[soak_evidence_not_real]` | `min(75)` (with `gate_warn` warn-only) | **75.0** |
| W35-corrective-CLOSE `ad521c07` | `[t3_deferred, soak_evidence_not_real]` | `min(72, 75)` (with `gate_warn`) | **72.0** |

**Cause.** Corrective work touched hot-path code (`server/app.py` C-3 helper extraction; observability ADR additions in C-1). Per CLAUDE.md Rule 8, this requires fresh real-Volces evidence at the corrective HEAD. The team committed an explicit DEFERRED record (`docs/delivery/2026-05-06-6b817f8-t3-volces.json`, `provenance: shape_verified`, mode `"deferred"`, status `"deferred"`) per Rule 8 step 6 instead of running real-Volces (no API key available in the corrective window). The DEFERRED record immediately invokes `t3_deferred` cap=72 (per `score_caps.yaml:102-106`).

**Diagnosis.** Expected and correct cap behaviour. The cap would have been suspicious only if the score had stayed at 75.0 despite the new T3 deferral — that would indicate a cap not firing.

**Resolution path.** Cap clears when next manifest cycle records passing T3 with `provenance: real`. Named in `cap_factors_resolution.t3_deferred` field of the latest signoff.

---

## 3. W36 plan disposition

Three independent plan files published 2026-05-06 (force-added under gitignored `docs/superpowers/plans/`):

| RIA-HIGH | Plan | Coverage | Hidden findings surfaced |
|---|---|---|---|
| A3 Tier-1 retention 8 stores | `2026-05-06-wave-36-a3-tier1-retention-adoption.md` (14-day) | All 8 stores named: SQLiteEventStore, SQLiteRunStore, SQLiteGateStore, SqliteDecisionAuditStore, SqliteEvidenceStore, SQLiteKernelRuntimeEventLog, SQLiteDedupeStore+SQLiteDecisionDeduper (group), SQLiteRecoveryOutcomeStore+SQLiteTurnIntentLog (group). W35-T4 reference pattern fully adopted. Per-store metric `{tenant_id}` per C-1 policy. 7 acceptance criteria. | (a) `harness/evidence_store.py` 12-line deprecated shim → delete; (b) `sqlite_task_view_log.py` no instantiation site → day-1 investigation; (c) `SQLiteDedupeStore` missing `created_at` → migration; (d) `SqliteDecisionAuditStore` missing `tenant_id` → column-add or `# scope: process-internal` exemption. |
| A5 boot-time B1–B14 | `2026-05-06-wave-36-a5-boot-time-assertions.md` (14-day) | All 14 listed individually. Shared helper `assert_research_posture_required` extracted into `hi_agent/config/posture.py`. **B13 closure cross-references RIA G-RIA-13** with bilateral manifest_id + shared route inventory at `docs/platform/agent-server-northbound-contract-v1.md` + 24h coordinated landing window. | B14 sequencing: ~50 route-level tests pass `idempotency_facade=None`; shared `tests/conftest.py::stub_idempotency_facade` fixture migration sequenced before assertion lands. |
| A4 schema-shape lineage | `2026-05-06-wave-36-a4-schema-lineage-extensions.md` (4-phase) | All 5 dataclasses + 4 MEDIUMs. `StoredEvent` adds previously-missing `attempt_count` 4th field. Phased: additive → tighten → SSE e2e → RuntimeEvent + minors. Digest re-snapshot committed. | `_status_dict` (routes_runs_extended.py:92) and `event_facade.render_sse_chunk` (77-99) flagged as hand-built dict HIGH-risk wire-format sites. `RuntimeEvent` widening preferred over TenantContext extension. |

**No item renegotiated, deferred, or rejected.** Acceptance stated only in commit message `276917d8`: "ALL 9 RIA items accepted as binding (6 W35 corrective + 3 W36 HIGH). None violates G1; each strengthens contracts we already promised."

### 3.1 Three deliverables missing as plan artifacts

| Item | RIA W36 directive source | Status |
|---|---|---|
| 6h Linux soak plan | §5 | **MISSING** — 0 plan files match |
| Postgres equivalence plan | §2.4 | **MISSING** — 0 plan files match |
| §0 plan-index / W36 acceptance memo | §4.1 (9 binding items table) | **MISSING** — acceptance only in commit message |

These three become Supplement Asks S-1 / S-2 / S-3 in the outgoing directive.

### 3.2 Score-cap retirement targeting — honoured

Zero references to "soak", "cap retirement", or "soak_evidence_not_real" in the three published plan files. Soak measurement is not muddled with cap-retirement targeting, consistent with RIA's reaffirmed feasibility-only stance.

---

## 4. Hidden findings surfaced by hi-agent's W36 plans (7 items)

Hi-agent's plans surfaced 7 hidden findings beyond RIA's W36 entry directive enumeration:

| ID | Source | Severity | Disposition |
|---|---|---|---|
| HF-1 | A3 plan: `harness/evidence_store.py` deprecated shim | LOW | delete in W36 |
| HF-2 | A3 plan: `sqlite_task_view_log.py` no instantiation | UNKNOWN | day-1 investigation |
| HF-3 | A3 plan: `SQLiteDedupeStore` missing `created_at` | MEDIUM | migration day-1 |
| HF-4 | A3 plan: `SqliteDecisionAuditStore` missing `tenant_id` | HIGH | column-add or `scope: process-internal` |
| HF-5 | A4 plan: `RuntimeEvent` lacks lineage entirely | HIGH | Option A widening |
| HF-6 | A4 plan: `_status_dict` hand-built dict | HIGH | wire-format risk |
| HF-7 | A4 plan: `event_facade.render_sse_chunk` hand-built dict | HIGH | wire-format risk |

This is "edge of the audit" surfacing — 5 of 7 are HIGH severity and **all 7 are remediated in-scope** within the same plan that surfaces them. This is mature self-audit behaviour at W36-open, structurally identical to the W34-close 6-parallel-agent audit pattern, now applied at W36-open.

---

## 5. Eight-lens delta vs. 2026-05-05 audit

| Lens | 2026-05-05 | 2026-05-07 |
|---|---|---|
| L1 Tenant isolation | T1+T3 PASS; T3 dev-side test missing | **+ C-4 closed; symmetric coverage explicit** |
| L2 Functional idempotency | T4+T6+T8; label drift | **+ C-1 closed; 4 metrics align with run-lifecycle `{tenant_id}`; policy doc'd** |
| L3 High reliability | T1+T9 (T9 soft); A4 schema W36 | **+ C-3 closed; A4 plan published with phased rollout + 2 wire-format risks surfaced** |
| L4 High concurrency | W34 baseline maintained | **— soak/Postgres plans missing (regression vs W36 directive expectation)** |
| L5 Configurable development | T2+T7; A5 W36 | **+ A5 plan with 14 assertions + shared helper + B13↔G-RIA-13 bilateral coordination** |
| L6 Continuous intelligence evolution | T1+T9 transitively | Same as L3 (A4 plan published) |
| L7 7×24 architectural feasibility | T4 reference + 8 Tier-1 catalogued | **+ A3 plan with 8 stores all named + W35-T4 pattern adopted + 4 hidden findings remediated** |
| L8 Agent service to upper systems | T6+T8; C-1 pending | **+ C-1 closed; consumer-side dashboard naming-policy unblocked** |

**Largest positive delta**: A5 B13 explicitly cross-references RIA G-RIA-13 (`scripts/check_route_presence.py`) with bilateral manifest_id + shared route-inventory anchor + 24h coordinated landing window. This is the first concrete instance of bilateral architectural coordination written into a hi-agent plan document — both teams hardening the same architectural failure mode (silent route omission) from different sides simultaneously.

**Largest negative delta**: L4 — the W36 entry directive's binding 6h Linux soak + Postgres equivalence are not yet covered by any plan file. This is what the outgoing directive's S-1 / S-2 supplement asks address.

---

## 6. Engineering-team maturity assessment update

In our 2026-05-05 audit we still framed the platform team as a "newcomer team that previously made many engineering errors." That framing is **now out of date**. Three signals in the W35 corrective + W36 plan cycle:

1. **Three-part closure executed uniformly across 6 corrective items** without supervision-grade prompting. C-1 went beyond the directive's strict letter (added ADR-OBS-2 anchored in two places); §5.1 patched the gate scope hole (5th source + regression test) rather than just bumping the ledger value.
2. **Five parallel reconnaissance audits at W35-open** self-identified 91 hidden findings (38 closed in W35; 32 W36-bound; 17 W37+); the W36 plans surface 7 additional hidden findings without renegotiating any RIA-binding item.
3. **B13 closure cross-references RIA G-RIA-13 explicitly** with shared route inventory anchor and coordinated landing window. The platform team is writing bilateral coordination into its own plans without prompting.

This is execution-track mature work. RIA going forward describes the platform team as "execution-track mature with discipline that absorbs corrective directives without rebadging."

The bar the team is held to does not change — three-part closure, evidence honesty, naming-accretion-as-defect. What changes is the framing of the relationship: the corrective cycle is now a "delta refinement on a strong baseline" rather than "supervision over recurring drift."

---

## 7. Decision recommendation

The W35 corrective is M2 closed; the W36 plans for the 3 RIA-HIGH items are binding-as-written; three supplement asks (S-1 6h soak, S-2 Postgres, S-3 plan-index) are required before W36 binding ramp. RIA R-W1 sub-wave 1 has no remaining hi-agent dependency that blocks start:

- C-1 closure unlocks RIA Guard rail 3 (observability label form decided).
- A4 plan publication makes the schema-shape extension predictable enough that RIA `evolution_engine/postmortem.py` design can proceed.
- S-1 / S-2 missing plans are platform-side measurement deliverables; they do not affect RIA code paths.

**Recommendation: start RIA R-W1 sub-wave 1 immediately**, alongside the outgoing supplement directive. Sub-wave 1 lands K-stream doc sync, H-stream `real_agent_server` fixture, and 4 J-stream gates (G-RIA-10 / G-RIA-11 / G-RIA-12 / G-RIA-13).

---

## 8. Cross-references

| Document | Purpose |
|---|---|
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md` | outgoing directive (acceptance + supplement) |
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-directive-2026-05-05.md` | predecessor — corrective items |
| `D:\chao_workspace\research\docs\hi-agent-wave36-engineering-expectations-2026-05-05.md` | predecessor — W36 entry directive |
| `D:\chao_workspace\research\docs\ria\ria-engineering-plan-r-w1-2026-05-05.md` | RIA R-W1 plan (sub-wave 1 starting) |
| `D:\chao_workspace\hi-agent\docs\releases\wave35-signoff.json` | latest signoff at HEAD `ad521c07` |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-06-wave-36-a3-tier1-retention-adoption.md` | A3 plan |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-06-wave-36-a5-boot-time-assertions.md` | A5 plan |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-06-wave-36-a4-schema-lineage-extensions.md` | A4 plan |
| `D:\chao_workspace\hi-agent\docs\governance\score_caps.yaml` | cap factor canonical definitions |
| `D:\chao_workspace\hi-agent\docs\governance\recurrence-ledger.yaml` | drift gate self-doc at line 591-608 |

---

**Signed:** RIA team
**Audit head (RIA side):** `main` at 2026-05-07
**Platform head under audit:** `ad521c07` (hi-agent W35-corrective-CLOSE)
**Document maturity:** M1 — internally reviewed; not promoted to M2.
