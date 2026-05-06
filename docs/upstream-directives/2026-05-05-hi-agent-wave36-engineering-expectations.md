> **Mirrored from RIA on 2026-05-05.**
> Source: D:\chao_workspace\research\docs\hi-agent-wave36-engineering-expectations-2026-05-05.md
> Maturity in this repo: M2 (mirrored to docs/upstream-directives/).
> See `docs/downstream-responses/2026-05-05-w35-corrective-response.md` for hi-agent's response.
> No content changes from source other than this preamble.

# hi-agent Wave 36 Engineering Expectations (Entry Directive)

**Date:** 2026-05-05
**From:** Research Intelligence Application (RIA) team — downstream platform consumer
**To:** hi-agent upstream engineering team
**Status:** W36 entry directive (M1 — internally reviewed; binding on the W36 plan once accepted)
**Position:** Successor to the W35 acceptance + W36 forward expectations directive (`hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md`) — promotes that document's pre-binding W36 forward expectations to binding, integrates the W35 corrective items (`hi-agent-w35-corrective-directive-2026-05-05.md`), and refines RIA's positioning informed by the W35 audit (`hi-agent-w35-acceptance-audit-2026-05-05.md`).

**Companion documents on the RIA side (informational, not binding on you):**
- `docs/ria/ria-architecture-v2.md` (v2.0.1; R-W1 wave underway, see §11 for the cross-team coordination implications)
- `docs/ria/ria-engineering-plan-r-w1-2026-05-05.md` (RIA-internal — describes the parallel RIA-side work)

---

## 0. Standing on Wave 35

The W35 ship is accepted. The eight named acceptance items (W35-T1 through W35-T8) and the hidden HIGH item (W35-T9) are closed in code at the release_head `bd4d38d5`. The W34 acceptance signed in the predecessor directive stands.

The W35 audit surfaced four corrective items (C-1 through C-4) and two governance items (§5.1 and §5.2 of the corrective directive). They are scheduled to close in the W35 corrective window (target: before W36 binding work begins). They do not invalidate the W35 ship.

This directive does the following:
- §1 — carries forward the standing engineering discipline rules.
- §2 — refines the eight-lens positioning given W35's actual outcomes (with the audit deltas).
- §3 — names the W36 binding work scope.
- §4 — integrates the W35 corrective carry-forwards (C-1..C-4 + §5 governance items).
- §5 — names the 6h Linux soak (per W34-LINUX-SOAK-ROADMAP) as a W36 measurement opportunity.
- §6 — lists out-of-scope items.
- §7 — reporting format for W36 closure.
- §8 — cross-references.

---

## 1. Engineering Discipline (Standing Reminders — Carried Forward)

These three rules continue from the W34/W35 directives unchanged.

### 1.1 No mock-based filtering as stub limitation

> When a test passes against a stub but breaks against the real component, that is a defect in the production component, not a stub limitation. The defect is fixed in the production component; the stub may then be tightened to match.

W35 honoured this rule. RIA's R-W1 wave (described in `docs/ria/ria-engineering-plan-r-w1-2026-05-05.md`) lands a session-scope `real_agent_server` fixture and forbids stubs in `tests/integration/**`, mirroring the discipline at the consumer boundary.

### 1.2 Naming / structure accretion is a defect

The W35 corrective C-1 (Prometheus label drift `{tenant_bucket}` vs. `{tenant_id}`) is the first concrete W35-era instance of this rule firing. The W35 audit confirms the principle remains binding: any naming change to a documented contract surface (metric labels, route names, contract field names, env var names) requires explicit announcement in a wave delivery notice and corresponding directive cohort, not silent drift under operational rationale (cardinality, telemetry cost, etc.).

### 1.3 Defect-vs-limitation discipline (three-part closure)

Honoured uniformly in W34. W35 introduced one closure-level overstatement (W35-T9 marked `verified_at_release_head` despite a missing regression test); corrective C-3 in the corrective directive addresses it. Carried forward; binding for W36.

---

## 2. Cross-Layer Positioning Refresh — Eight Lenses, Post-W35-Audit

### 2.1 Tenant Isolation (Lens 1)

**W35 closed.** T3 INVERTED posture (auth-authoritative + anti-forgery cross-check); T1 spine validation extended to 53 contract dataclasses including the original 13 RIA-named.

**W35 corrective.** C-4 dev-side symmetric test on the T3 cross-check (closes test asymmetry).

**W36 binding scope.** No new lens-1 scope added by this directive — RIA's R-W1 wave is the consumer-side complement.

### 2.2 Functional Idempotency (Lens 2)

**W35 closed.** T4 TTL purge + T6 four observability metrics + T8 boot-time MCP idempotency assertion.

**W35 corrective.** C-1 label revert (`{tenant_bucket}` → `{tenant_id}` for the four new metrics) — required before W36 binding ramp.

**W36 binding scope.** The W35 retention pattern is the **reference implementation**; the eight A3 Tier-1 stores (per `docs/governance/retention-roadmap.md`) adopt the same pattern in W36. See §3.1 below.

### 2.3 High Reliability (Lens 3)

**W35 closed.** T1 spine validation across 53 dataclasses; T9 re-lease attempt_id bump (code path).

**W35 corrective.** C-3 W35-T9 closure level downgraded to `code-fix-only` until the regression test (`tests/integration/test_run_manager_release_attempt_id_bump.py`) lands.

**W36 binding scope.**
- A4 schema-shape lineage extensions on `RunResponse` / `RunStatus` / `RunStream` / `StoredEvent` / `ReasoningTrace` so attempt-chain fields are exposed at the wire/SSE level. See §3.3.
- A4 minor 4 sites: `OpHandle` parent_run_id/attempt_id/phase_id, `ManagedRun` replayed-stub lineage, `StoredEvent` runtime-event default, `event_bus` `RuntimeEvent` silent default. Severity MEDIUM — closure expected in W36 if not earlier.

### 2.4 High Concurrency (Lens 4)

**W35 closed.** No new W35 work; W34 baselines (P50=77.5ms / P95=200.4ms at N=50/M=5; P50=28.0ms / P95=51.8ms at N=10/M=1) preserved.

**W36 binding scope.**
- 6h Linux soak per W34-LINUX-SOAK-ROADMAP at the W36 head, on `ubuntu-latest` (4 vCPU / 16 GB RAM) at N=50/M=5 with 30s chaos cadence — see §5.
- Persistence equivalence Postgres leg PASS with `HI_AGENT_TEST_POSTGRES_DSN` configured in CI — closes the W34 SQLite-only PASS gap.
- N raised toward N=100/M=10 if CI runner stability allows (per the methodology document's W34 forward note).

### 2.5 Configurable Development (Lens 5)

**W35 closed.** T2 WEAK_PARITY 12+8 sites; T7 deferred with documented v2-contract-scoping rationale.

**W36 binding scope.**
- A5 boot-time assertions B1–B14 (per `docs/governance/boot-time-assertions-roadmap.md`) — see §3.2. **B13 silent route omission** is structurally identical to RIA's R-RIA-9 outbound seam concern and must cross-reference the RIA G-RIA-13 gate (`scripts/check_route_presence.py`) when implemented.
- 4-variable env-var allowlist in `scripts/check_env_var_routing.py` reviewed for completeness; any new policy-sensitive var landing in W35 (none observed) added.

### 2.6 Continuous Intelligence Evolution (Lens 6)

**W35 closed transitively.** T1 + T9 close the construction-site validation surface for postmortem reconstruction.

**W36 binding scope.**
- A4 schema-shape lineage extensions (covered in §2.3 / §3.3) — directly enables RIA's `evolution_engine/postmortem.py` real implementation in R-W1.
- Phase 3 read routes (`/v1/skills/{skill_id}/versions`, `/v1/runs?since=...&limit=N`, `/v1/skills/{skill_id}/runs?since=...`, `/v1/kg/query?tenant_id=...&q=...`) — RIA does **not** request these in W36; we reaffirm the W35 forward-expectations §4.4 stance that they will be scoped via a separate routes-extension directive once R-W1 is far enough along to know exact shapes.

### 2.7 Long-Running 7×24 (Lens 7) — Reaffirmed Position

**Position carried forward verbatim from RIA at 2026-05-05:**

> "我们只关注是否具备可行性而不关注具体能力" — "we only care about whether it is feasible, not specific capability".

**Operational meaning unchanged.** Architectural feasibility is the standard; specific measured soak duration is not a capability claim. The `arch-7x24` 5/5 PASS check is the structural indicator. The `soak_evidence_not_real` cap persists for the right reason.

**W35 closed.** T4 TTL purge as the retention reference implementation.

**W35 audit refinement.** The W35 audit confirmed that 8 of the 24 unbounded-growth stores (Tier-1 in `docs/governance/retention-roadmap.md`) currently carry **0 retention code**; the W35-T4 reference is the only store with retention. The Lens 7 architectural-feasibility position holds, but the magnitude of the architectural counter-example is now visible.

**W36 binding scope.**
- A3 Tier-1 retention adoption across the 8 stores — see §3.1.
- 6h Linux soak per W34-LINUX-SOAK-ROADMAP — see §5. **Reaffirmed**: the soak measures feasibility; cap disposition is whatever the measured outcome justifies. The soak is **not** tuned for cap retirement.

### 2.8 Agent Service to Upper Systems (Lens 8)

**W35 closed.** T6 metrics + T8 boot reject for MCP idempotency coverage.

**W35 corrective.** C-1 label revert applies to this lens too (consumer dashboards rely on label consistency).

**W36 binding scope.** No new scope — RIA's R-W1 wave brings up `ria/api/{http,mcp}/` as the consumer-side surface; the platform-side served surface is sufficient for that work given W35 closure.

---

## 3. Wave 36 Binding Scope (RIA-HIGH Priority Signals)

Three items carry **HIGH** RIA priority; they intersect the eight-lens positioning at structural points.

### 3.1 A3 Tier-1 Retention — 8 Stores (RIA priority: HIGH)

**Why HIGH.** Lens 7 architectural-feasibility class: every unbounded-growth store is an architectural counter-example to "this system can run continuously". W35-T4 closed one (idempotency). The W35 audit confirmed 8 more in Tier-1 currently have **0 retention code**:

1. `hi_agent/server/event_store.py` (SQLiteEventStore)
2. `hi_agent/server/run_store.py` (SQLiteRunStore)
3. `hi_agent/management/gate_store.py` (SQLiteGateStore)
4. `hi_agent/route_engine/decision_audit_store.py` (SqliteDecisionAuditStore)
5. `hi_agent/runtime/harness/evidence_store.py` and `hi_agent/harness/evidence_store.py` (SqliteEvidenceStore)
6–8. `agent_kernel/kernel/persistence/sqlite_*.py` triplet (event_log, dedupe_store, task_view_log) plus 3 unnumbered (turn_intent_log, recovery_outcome_store, decision_deduper)

**RIA expectation for W36 closure:**
- Each Tier-1 store acquires a `purge_expired(now=...) -> int` method following the W35-T4 reference pattern.
- Each store wires a background lifespan task using the documented `HI_AGENT_<STORE>_RETENTION_DAYS` / `HI_AGENT_<STORE>_PURGE_INTERVAL_S` env-var convention (the convention is currently documentation-only; W36 makes it real).
- Disk-growth regression test per store (10K records → purge → byte size shrinks).
- Three-part closure (Rule 15) per store.
- Per-store Prometheus metric `hi_agent_<store>_purged_total{tenant_id}` (label per the W35 corrective C-1 policy).

**Acceptance criterion for W36 binding.**
- 8 Tier-1 stores each have closed retention with the structural test and metric.
- `docs/governance/retention-roadmap.md` updated to reflect Tier-1 closure.
- Three-part closure (Rule 15) per store.

### 3.2 A5 Boot-time Assertions B1–B14 (RIA priority: HIGH)

**Why HIGH.** Configurable-development class (Lens 5) and structurally aligned with RIA's R-RIA-9 outbound seam concern. The most architecturally risky in this set:

- **B13 silent route omission**: `agent_server.api.build_app(event_facade=None, artifact_facade=None, manifest_facade=None, ...)` boots successfully and silently omits routes; downstream gets 404 only on first traffic. **RIA's R-W1 wave introduces `scripts/check_route_presence.py` (G-RIA-13) on the consumer side**, asserting that the `tests/integration/conftest.py::real_agent_server` fixture probes a documented route inventory before yielding. The W36 closure of B13 should cross-reference G-RIA-13 in the closure documentation so both teams' implementations are coherent.
- **B6–B10**: `hi_agent/server/app.py` mounting routes for memory_manager / retrieval_engine / slo_monitor / session_store / feedback_store without backing resources — same silent-route-omission class.
- **B1–B5, B11–B12, B14**: catalogued in `docs/governance/boot-time-assertions-roadmap.md`; assertions per the roadmap text.

**RIA expectation for W36 closure:**
- All 14 HIGH-severity boot-time gaps closed with posture-aware boot-time assertions.
- B13 closure documentation cross-references the RIA G-RIA-13 gate.
- Three-part closure (Rule 15) per assertion.
- A regression test fixture that constructs a deliberately-incomplete `build_app` invocation and asserts boot-time failure under research/prod posture.

### 3.3 A4 Schema-shape Lineage Extensions (RIA priority: HIGH)

**Why HIGH.** Lens 3 + Lens 6 transitively. RIA's `evolution_engine/postmortem.py` (R-W1 deliverable) reconstructs attempt trees from platform reads; without `attempt_id` / `parent_run_id` / `attempt_count` / `phase_id` exposed at the schema level on `RunResponse` / `RunStatus` / `RunStream` / `StoredEvent` / `ReasoningTrace`, RIA either does inference (incorrect for non-trivial cases) or queries an internal-only field (R-RIA-1 violation).

**RIA expectation for W36 closure:**
- All five schema dataclasses gain optional or required attempt-chain fields per the audit doc §A4 spec.
- `agent_server/contracts/` digest re-snapshot in the W36 delivery notice.
- Construction-site `__post_init__` posture-aware validation (consistent with W35-T1 pattern).
- Three-part closure (Rule 15).

---

## 4. W35 Corrective Carry-forwards

The four corrective items (C-1, C-2, C-3, C-4) and the two governance items (§5.1, §5.2) named in `hi-agent-w35-corrective-directive-2026-05-05.md` are carried forward as W36-binding **only if** they have not been closed in the W35 corrective window. The corrective directive expects them to close before W36 binding ramp; this directive treats them as "due-by-W36-entry" rather than "W36-fresh".

### 4.1 Disposition table

| Item | Original location | W36 disposition |
|---|---|---|
| C-1 (label revert) | corrective directive §1 | due before W36 binding ramp; if not closed, W36 binding (Lens 2 + Lens 8) |
| C-2 (provenance cap clarification) | corrective directive §2 | due before W36 binding ramp; if not closed, W36 binding (governance) |
| C-3 (W35-T9 closure level) | corrective directive §3 | due before W36 binding ramp; if not closed, W36 binding (Lens 3) |
| C-4 (W35-T3 dev-side test) | corrective directive §4 | due before W36 binding ramp; if not closed, W36 binding (Lens 1) |
| §5.1 wave-ledger drift | corrective directive §5.1 | due before W36 binding ramp; if not closed, W36 binding (governance) |
| §5.2 captain artifacts at parent HEAD | corrective directive §5.2 | due before W36 binding ramp; if not closed, W36 binding (governance) |

---

## 5. 6h Linux Soak (per W34-LINUX-SOAK-ROADMAP)

**Required parameters.** `ubuntu-latest` 4 vCPU / 16 GB RAM; N=50/M=5; 30s chaos cadence; 6h duration; `provenance: real`.

**RIA's reaffirmed framing.**

| What RIA wants | What RIA does NOT want |
|---|---|
| The soak runs as a measurement opportunity at the W36 head | The soak tuned for cap retirement |
| Outcome reported with provenance, regardless of cap-disposition implication | A specific RSS/CPU envelope as SLA |
| The two OS-limited chaos scenarios (`signal_storm`, `fd_exhaustion_recovery`) participate | A new chaos cadence or workload increase beyond the methodology baseline |

**Cap disposition rule.** The `soak_evidence_not_real` cap stays, retires, or reframes — driven by the soak's measured outcome, not by a cap-target. A clean 6h soak and a 6h soak that surfaces an architectural defect are **both** successful W36 deliverables.

**Acceptance criterion.**
- Soak ran as specified at the W36 head with provenance `real`.
- Outcome reported in W36 delivery notice.
- Cap disposition (retire / stay / reframe) reasoned from the soak data.
- `arch-7x24` 5/5 re-run at the soak HEAD.

---

## 6. Out of Scope for Wave 36 (Explicitly Not Asking)

- **No new v1 contract routes added by this directive.** Phase 3 read routes named in W35 forward §4.4 remain "tracked for a separate routes-extension directive once R-W1 is mature".
- **No platform v2 contract work.** RIA pins `agent_server v1`.
- **No new chaos scenarios beyond the two OS-limited ones already in the soak roadmap.**
- **No defense-in-depth shims on the RIA side** (per AP-9). RIA's R-W1 wave does not mask any W36 carryover with workarounds; tests stay red and surface in `docs/ria/red-status/<sha>.json`.
- **No additional acceptance criteria beyond what is already in the W35 plan + this directive's §3.** RIA does not introduce new HIGH-priority items in this directive that did not appear in the W35 audit's W36-binding list.

---

## 7. Reporting Format (For Wave 36 Closure Notice)

When you close W36, the delivery notice should include the following structured section so we can verify mechanically:

```
## Wave 36 Closure Evidence

| Acceptance ID | Status | Evidence path | Provenance | RIA designation |
|---|---|---|---|---|
| W35 corrective C-1..C-4 + §5.1, §5.2 | PASS / IN-W35-CORRECTIVE-WINDOW | <paths> | measured | corrective carry-forward |
| W36-A3-T1 (Tier-1 retention 8 stores) | PASS | <per-store paths + roadmap update> | measured | HIGH (Lens 7) |
| W36-A5-B1..B14 (boot-time assertions) | PASS | <per-assertion paths + roadmap update + B13/G-RIA-13 cross-ref> | measured | HIGH (Lens 5) |
| W36-A4-LINEAGE (schema-shape extensions) | PASS | <5 dataclass diffs + digest re-snapshot> | measured | HIGH (Lens 3 + Lens 6) |
| W36-A4-MINOR (4 sites) | PASS | <paths> | measured | MEDIUM |
| W36-LINUX-SOAK | PASS | <docs/verification/<head>-linux-soak-6h.json + arch-7x24 re-run> | real | binding |
| W36-POSTGRES-EQUIV | PASS | <test result with HI_AGENT_TEST_POSTGRES_DSN> | measured | binding |
| Default-offline clean-env at HEAD | PASS | <docs/verification/<final-head>-default-offline-clean-env.json> | measured | RIA standard |
| arch-7x24 fresh evidence at HEAD | PASS | <docs/verification/<final-head>-arch-7x24.json> | measured | RIA standard |
| Real T3 (Volces) at HEAD | PASS | <docs/delivery/<date>-<final-head>-t3-volces.json> | real | RIA standard |
```

**Critical reporting requirement.** All `<final-head>` placeholders in the table above MUST resolve to the W36 release_head (per W35 corrective §5.2 disposition). A repeat of the W35 parent-HEAD-evidence pattern will be flagged.

**Three-part defect closure documentation.** Required for every HIGH item, every Tier-1 retention closure (8 of them), and every boot-time-assertion closure (14 of them). Format unchanged from W34/W35 directives:

```
### W36-<ID> closure (three-part)
(a) Code fix: <commit SHA + file:line>
(b) Recurrence-prevention check: <gate script + CI integration commit>
(c) Process change: <ARCHITECTURE.md or governance-doc section + line>
```

---

## 8. Cross-References

| Document | Purpose |
|---|---|
| `D:\chao_workspace\research\docs\hi-agent-w35-acceptance-audit-2026-05-05.md` | RIA audit (the basis for this directive's positioning) |
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-directive-2026-05-05.md` | corrective directive (companion to this entry directive) |
| `D:\chao_workspace\research\docs\hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md` | predecessor — W35 acceptance + W36 forward expectations |
| `D:\chao_workspace\research\docs\hi-agent-wave34-engineering-expectations-2026-05-04.md` | W34 directive (historical) |
| `D:\chao_workspace\research\docs\ria\ria-engineering-plan-r-w1-2026-05-05.md` | RIA-internal R-W1 engineering plan (companion; describes the consumer-side parallel work) |
| `D:\chao_workspace\hi-agent\docs\downstream-responses\2026-05-05-w35-delivery-notice.md` | W35 delivery notice |
| `D:\chao_workspace\hi-agent\docs\releases\wave35-signoff.json` | W35 signoff (release_head `bd4d38d5`) |
| `D:\chao_workspace\hi-agent\docs\governance\retention-roadmap.md` | A3 24 unbounded-growth stores; Tier-1 W36 binding |
| `D:\chao_workspace\hi-agent\docs\governance\boot-time-assertions-roadmap.md` | A5 22 boot-time gaps; B1–B14 W36 binding |
| `D:\chao_workspace\hi-agent\docs\governance\systematic-audit-w35-2026-05-05.md` | W35 audit (A4 lineage findings) |

---

## 9. Acknowledgement

The W35 ship demonstrates the maturity to absorb four corrective items and two governance items in a corrective window without retracting the ship — the natural shape of a deeper code-level audit on a strong wave delivery. The W36 binding scope below is large (8 retention closures + 14 boot-time assertions + 5 schema-shape extensions + 4 minor lineage sites + 6h Linux soak + Postgres equivalence) but each item already has a reference implementation pattern from W35 (T4 retention; T8 boot-time assertion; T1/F.3 spine validation) and a concrete catalogue (retention-roadmap, boot-time-assertions-roadmap). The work is execution-track; the design is established.

The cross-team coordination on B13 ↔ G-RIA-13 (silent-route-omission) is the structurally interesting item: it is the first concrete instance where a hi-agent W36-binding item has a parallel, non-coincidental RIA implementation in the same wave. Both teams hardening the same architectural failure mode from different sides simultaneously is a significant signal of cooperative legibility.

The escalations and forward expectations in this directive are not a comment on the quality of W35. They are the natural shape of the work that follows from the W35 audit's enumerated closure-cohort and the W36 binding scope already self-identified by the platform team's own audit.

---

**Signed:** RIA team
**Audit head (RIA side):** `main` at 2026-05-05
**Platform head under audit:** `bd4d38d5` (hi-agent W35 release_head per signoff)
**Document maturity:** M1 — internally reviewed; promotes to M2 when mirrored into hi-agent's `docs/upstream-directives/`.

---

**End of W36 Engineering Expectations.**
