> **Mirrored from RIA on 2026-05-07.**
> Source: D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md
> Maturity in this repo: M2 (mirrored to docs/upstream-directives/).
> See `docs/superpowers/plans/2026-05-07-wave-36-plan-index.md` for hi-agent's W36 §0 disposition.
> No content changes from source other than this preamble.

# hi-agent W35 Corrective Acceptance + W36 Supplement Directive

**Date:** 2026-05-07
**From:** Research Intelligence Application (RIA) team — downstream platform consumer
**To:** hi-agent upstream engineering team
**Status:** Acceptance directive (M1 — internally reviewed; W35 corrective acceptance is binding; W36 supplement is binding once acknowledged)
**Position:** Successor to `hi-agent-w35-corrective-directive-2026-05-05.md` and `hi-agent-wave36-engineering-expectations-2026-05-05.md`. Closes the W35 corrective window and surfaces three supplement asks for the W36 binding ramp.

**Companion documents (RIA side, not binding on you):**
- `docs/hi-agent-w35-corrective-acceptance-audit-2026-05-07.md` — RIA-internal M1 audit (basis of this directive)

---

## 0. Standing on the W35 Corrective Window

The W35 corrective window opened with our 4 corrective items (C-1..C-4) plus 2 governance items (§5.1 wave-ledger drift; §5.2 release-captain artifacts at parent HEAD). Per the W35 corrective directive §6 reporting format, RIA cross-checked each row of your corrective response and your committed code at HEAD `ad521c07`.

### 0.1 Wave 35 Corrective Closure — full acceptance

All 6 corrective items are **CLOSED at M2** at HEAD `ad521c07` against measured / derived evidence. Per RIA §8 reporting format we cross-checked each:

| Corrective ID | Status | Evidence we cross-checked | Provenance |
|---|---|---|---|
| C-1 (Prometheus label revert) | **ACCEPTED** | `hi_agent/observability/idempotency_metrics.py:88,108,137,158` — all 4 metrics now `{tenant_id}` (raw); `tests/integration/test_idempotency_metrics.py:236-307::test_metric_label_set` uses frozenset for explicit drift guard; policy paragraph in both `docs/observability/idempotency-metrics.md:185-204` AND `hi_agent/observability/ARCHITECTURE.md:288-302` (ADR-OBS-2). `hi_agent_llm_tokens_total` correctly retained as documented W31 backwards-compat exception. | measured |
| C-2 (`provenance_unknown_or_synthetic` cap clarification) | **ACCEPTED** | `docs/governance/score_caps.yaml:147-152` carries the `lifecycle_note` declaring **reading (a) implicit-resolution** with verification grep evidence + re-fire trigger + detection scope. Latest `wave35-signoff.json` correctly omits the rule from `cap_factors_active`. | derived |
| C-3 (W35-T9 closure level + regression test) | **ACCEPTED** | `tests/integration/test_run_manager_release_attempt_id_bump.py` (3 tests, 3/3 PASS) — structural assertions on fresh uuid4 + `parent_run_id == run_id` + `attempt_count` increment with both populated and zero-baseline branches. `_bump_attempt_id_on_release` extracted at `hi_agent/server/app.py:1218-1275` for testability without semantic change. | measured |
| C-4 (W35-T3 dev-side symmetric test) | **ACCEPTED** | `tests/integration/test_run_manager_tenant_strict.py:181-223::test_dev_posture_body_tenant_id_mismatch_warns_and_uses_middleware` — caplog WARNING assertion + middleware-value-used assertion. Symmetry now structurally explicit on both research-raises and dev-warns directions. | measured |
| §5.1 (wave-ledger drift) | **ACCEPTED** | `current-wave.txt` and `recurrence-ledger.yaml::current_wave` both `35`. `scripts/check_wave_consistency.py` extended with 5th source (`recurrence_ledger_yaml`); 3-case regression in `tests/integration/test_check_wave_consistency_ledger.py`; CI wired at `.github/workflows/release-gate.yml:213`. Self-documented in `recurrence-ledger.yaml` entry W32-D-recurrence with `current_closure_level: verified_at_release_head`. | measured |
| §5.2 (release-captain artifacts at parent HEAD) | **ACCEPTED with asymmetry note** | Path (a) chosen — re-rolled evidence at intermediate corrective HEAD `5b1e4d25` (clean-env) / `5ba9bb7` (arch-7×24). The remaining 6-commit gap to final HEAD `ad521c07` is governance-only and declared in `wave35-signoff.json::evidence_exemption.kind: "none"` block with all 5 required fields populated. `scripts/check_signoff_evidence_exemption.py` enforces 5-field + enum + gov-only-gap reality check; CI wired at `.github/workflows/release-gate.yml:379`. | measured |

**Three-part defect closure (Rule 15) was honoured for every C-item.** We confirm the `verified_at_release_head` closure level for C-1, C-2 (lifecycle_note as derived-evidence closure), C-3, C-4, §5.1, §5.2.

One documentation lag noted (not a contract defect): `docs/downstream-responses/2026-05-05-w35-corrective-response.md` still lists C-1..C-3 as IN-PROGRESS / TBD because it has not been reissued post-track-land. Canonical artifacts (`score_caps.yaml`, code at HEAD `ad521c07`, `cap_factors_active` in latest signoff) are the binding authority and they confirm closure. Please reissue the corrective-response document to `PASS` at the next governance-doc cycle.

### 0.2 Quality of the W35 corrective work

The W35 corrective is exemplary work. Three particular qualities:

1. **C-1 went beyond the directive's strict letter.** The directive asked for label revert + policy paragraph + regression test. You also added an ADR (ADR-OBS-2) recording the decision provenance and cross-referenced the policy from two places (`hi_agent/observability/ARCHITECTURE.md` AND `docs/observability/idempotency-metrics.md`). This is the right shape for a contract-level discipline reminder — the policy is now anchored in two places that cite each other, making rediscovery easy.

2. **§5.1 wave-ledger fix surfaced and patched the actual scope hole, not just the symptom.** The fix is not "bump ledger from 33 to 35"; the fix is "extend `check_wave_consistency.py` to read the ledger as a 5th source so future drifts in this same field are caught at CI time." That's the higher-leverage fix and it lands.

3. **§5.2 chose the harder path (path a — re-roll evidence) over the easier path (path b — full exemption with rationale).** The asymmetry to final HEAD `ad521c07` is honest: declared in the signoff with `evidence_exemption.kind: "none"` plus full `hot_path_audit` and accepted by the gate. This is exactly the "what is true, said plainly" discipline that makes governance signal trustworthy.

### 0.3 Score-drop diagnosis — `verified_readiness` 75.0 → 72.0

The drop is **`t3_deferred` cap (cap=72) firing for the first time** because corrective work touched hot-path code (`server/app.py` C-3 helper extraction; observability ADR additions). Per CLAUDE.md Rule 8, this requires fresh real-Volces evidence at the corrective HEAD; the team did not have a Volces API key available and committed an explicit DEFERRED record (`docs/delivery/2026-05-06-6b817f8-t3-volces.json`, `provenance: shape_verified`) per Rule 8 step 6.

This is **expected and correct cap behaviour**. The cap would have been suspicious only if the score had stayed at 75.0 despite the new T3 deferral — that would indicate a cap not firing. The drop **validates** the cap-firing logic.

Resolution: clears when the next manifest cycle records a passing real-Volces T3 with `provenance: real`.

### 0.4 Engineering-team maturity recognition

In our 2026-05-05 audit we still carried language describing the platform team as a "newcomer team that made many engineering errors." That language is now **out of date** and we are retiring it. Three signals:

1. **Three-part closure executed uniformly across 6 corrective items** without supervision-grade reminders.
2. **A1 / A2 / A3 / A4 / A5 reconnaissance audits at W35-open (5 parallel agents) self-identified 91 hidden findings** and the W36 plans surface 7 additional hidden findings without renegotiating any RIA-binding item.
3. **B13 silent-route-omission closure cross-references RIA G-RIA-13 explicitly** — the platform team is now writing bilateral architectural coordination into their own plans without prompting.

This is not "newbie" performance. RIA going forward describes the hi-agent platform team as "execution-track mature with discipline that absorbs corrective directives without rebadging." We will continue to apply the same standard to W36; that does not change. What changes is the framing of the relationship.

---

## 1. Wave 36 Plan Acceptance

Three independent plan files were published 2026-05-06:

- `docs/superpowers/plans/2026-05-06-wave-36-a3-tier1-retention-adoption.md` (A3 Tier-1 retention 8 stores; 14-day plan)
- `docs/superpowers/plans/2026-05-06-wave-36-a5-boot-time-assertions.md` (A5 boot-time B1–B14; 14-day plan)
- `docs/superpowers/plans/2026-05-06-wave-36-a4-schema-lineage-extensions.md` (A4 schema-shape lineage; 4-phase plan)

### 1.1 Per-plan acceptance — all 3 RIA-HIGH plans BINDING

| RIA-HIGH | Plan disposition | Acceptance |
|---|---|---|
| A3 Tier-1 retention 8 stores | All 8 stores named explicitly; W35-T4 reference pattern adopted (`purge_expired` + lifespan loop + 16 env vars per `HI_AGENT_<STORE>_RETENTION_DAYS / _PURGE_INTERVAL_S` convention + per-store `{tenant_id}` metric + 10K disk-shrink regression test); 7 acceptance criteria stated; 4 hidden findings surfaced (deprecated shim, dead-code candidate, missing `created_at`, missing `tenant_id`) and remediated in-scope. | **BINDING** as written |
| A5 boot-time B1–B14 | All 14 assertions listed individually; shared helper `assert_research_posture_required` extracted into `hi_agent/config/posture.py`; **B13 closure explicitly cross-references RIA G-RIA-13** with bilateral manifest_id + shared route inventory anchor at `docs/platform/agent-server-northbound-contract-v1.md` + 24h coordinated landing window. B14 sequencing acknowledges shared-fixture migration prerequisite. | **BINDING** as written |
| A4 schema-shape lineage | All 5 dataclasses listed (`RunResponse` / `RunStatus` / `RunStream` / `StoredEvent` / `ReasoningTrace`) + 4 MEDIUM minor sites; `StoredEvent` adds the previously-missing `attempt_count` 4th field; phased rollout (additive → tighten → SSE e2e → RuntimeEvent + minors); contract digest re-snapshot committed; 2 hand-built-dict wire-format risks (`_status_dict`, `event_facade.render_sse_chunk`) flagged with HIGH-risk widening discipline. | **BINDING** as written |

### 1.2 No renegotiation, no rebadging

The W36 plans accept all 9 RIA binding items (6 W35 corrective carry-forwards + 3 W36 HIGH) per commit `276917d8`'s message ("ALL 9 RIA items accepted as binding (6 W35 corrective + 3 W36 HIGH). None violates G1; each strengthens contracts we already promised."). Zero items are renegotiated, deferred, or rejected.

This is the correct disposition shape.

---

## 2. W36 Supplement Asks (THREE)

The W36 plan set is missing three deliverables that the RIA W36 entry directive explicitly named as binding. These are **supplement asks**, not new scope: each was named in `hi-agent-wave36-engineering-expectations-2026-05-05.md` and is not yet covered by a plan artifact in `docs/superpowers/plans/`.

### 2.1 Supplement S-1 — 6h Linux Soak Plan (HIGH)

**Source.** `hi-agent-wave36-engineering-expectations-2026-05-05.md` §5 + W34-LINUX-SOAK-ROADMAP.

**Required deliverable.** A standalone plan at `docs/superpowers/plans/2026-05-*-wave-36-linux-soak.md` covering:

- Workload: `ubuntu-latest` (4 vCPU / 16 GB RAM) at N=50/M=5; 30s chaos cadence; 6h duration.
- Provenance: `real` — actual run, not simulated.
- Two OS-limited chaos scenarios participate: `signal_storm`, `fd_exhaustion_recovery`. Both move from `runtime_partial` to `real`.
- Outcome reporting: per RIA's reaffirmed framing, the soak measures **architectural feasibility**, not capacity. A clean 6h soak and a 6h soak that surfaces a defect are both successful deliverables.
- Cap disposition rule: `soak_evidence_not_real` cap stays / retires / reframes per measured outcome — **not tuned for cap retirement**.
- `arch-7x24` 5/5 re-run at the soak HEAD.

**Acceptance criterion.**
- Plan exists at the named path with the workload parameters above.
- Plan explicitly states "not tuned for cap retirement" or equivalent language.
- Three-part closure (Rule 15) scaffolding present: code path (CI workflow), regression-prevention check (workflow validates outputs), process change (delivery-notice template extension).

### 2.2 Supplement S-2 — Postgres Equivalence Plan (HIGH)

**Source.** `hi-agent-wave36-engineering-expectations-2026-05-05.md` §2.4.

**Required deliverable.** A standalone plan at `docs/superpowers/plans/2026-05-*-wave-36-postgres-equivalence.md` covering:

- `HI_AGENT_TEST_POSTGRES_DSN` configured in CI (the W34 SKIP gate now flips to PASS).
- Persistence-equivalence test exercises both SQLite leg and Postgres leg at N=10/M=1 minimum (matching the W34 baseline workload).
- Output: deterministic terminal-state distribution under both backends; failure signal if distributions diverge beyond the equivalence-window stated in `docs/perf/concurrency-methodology-v1.md`.
- (Optional) target N raised toward N=100/M=10 if CI runner stability allows; not required.

**Acceptance criterion.**
- Plan exists at the named path.
- CI workflow runs Postgres leg at W36 head with `provenance: measured` evidence.
- Three-part closure (Rule 15) scaffolding.

### 2.3 Supplement S-3 — W36 Plan-Index / §0 Disposition (MEDIUM)

**Source.** RIA W36 entry directive §4.1 (six W35 corrective carry-forwards + three W36 HIGH = 9 binding items).

**Problem.** Acceptance of the 9 binding items currently lives **only in commit message `276917d8`**. There is no top-level W36 plan-index or §0 disposition document that:
- enumerates all 9 binding items in a per-row table,
- names each item's owning plan-file (or "no plan needed — done in corrective window"),
- records the disposition (ACCEPTED / RENEGOTIATED with rationale / DEFERRED with rationale).

A commit message is not a citable artifact at the same maturity level as a plan file.

**Required deliverable.** A document at `docs/superpowers/plans/2026-05-*-wave-36-plan-index.md` or `docs/governance/wave36-acceptance.md`:

- Table of all 9 binding items with owning plan-file references.
- Disposition cell per item.
- §0 acceptance statement promoted from commit message to citable artifact.
- Cross-reference to the three published plan files (A3/A5/A4) plus S-1/S-2 plans (when published).

**Acceptance criterion.**
- Document exists.
- Each of the 9 items has a row.
- Document is mirrored / linked from the W36 delivery notice when shipped.

### 2.4 Supplement timeline

We expect S-1 / S-2 / S-3 plans published by **2026-05-10** (3 days from this directive). This is sufficient runway for the W36 plan-execution start without delaying the 14-day binding-track timelines on A3/A5/A4. Plan publication is structurally cheap; we are not asking for the soak or Postgres work to complete by that date — only the plan to exist.

If any supplement asks is materially harder than we estimate, please name the constraint in your response within 48 hours and propose a revised timeline; we will negotiate. We will not interpret silence past 2026-05-10 as a deferral.

---

## 3. Remaining minor items (informational, non-blocking)

These items are minor enough not to warrant supplement status but are worth surfacing for W36 hygiene:

- **Corrective-response document IN-PROGRESS / TBD lag.** `docs/downstream-responses/2026-05-05-w35-corrective-response.md` should be reissued to `PASS` at the next governance-doc cycle.
- **C-3 in-memory `ManagedRun` mirror update untested.** The team's scope choice (avoid full FastAPI lifespan harness) is reasonable. If a future wave introduces an end-to-end fixture, the mirror-update assertion can be added without scope expansion. Not a W36 ask.
- **A3 plan dead-code investigation result.** A3 plan day-1 investigates `sqlite_task_view_log.py` (no instantiation site found). When resolved, please record the finding in the W36 delivery notice's hidden-findings table.

---

## 4. Wave 36 Acceptance Criteria (CI-Verifiable, Endorsed)

Per the W36 entry directive §7 reporting format, plus the three supplement asks above:

| Acceptance ID | Criterion | RIA designation |
|---|---|---|
| W35-C-1..C-4 closure formal report | Reissue `2026-05-05-w35-corrective-response.md` to PASS | Carry-forward |
| W36-A3-T1 (8 stores) | Per published plan | **HIGH (Lens 7)** |
| W36-A5-B1..B14 | Per published plan; B13 cross-ref G-RIA-13 in delivery notice | **HIGH (Lens 5)** |
| W36-A4-LINEAGE | Per published plan; digest re-snapshot in delivery notice | **HIGH (Lens 3+6)** |
| W36-A4-MINOR (4 sites) | Per published plan | MEDIUM |
| W36-S-1 (6h Linux soak) | Plan published by 2026-05-10; soak run with `provenance:real` at W36 head | **HIGH** |
| W36-S-2 (Postgres equivalence) | Plan published by 2026-05-10; Postgres leg PASS in CI at W36 head | **HIGH** |
| W36-S-3 (Plan-index / §0) | Document published as citable artifact | MEDIUM |
| Default-offline clean-env at HEAD | Per RIA standard | RIA standard |
| arch-7x24 fresh evidence at HEAD | Per RIA standard | RIA standard |
| Real T3 (Volces) at HEAD | Re-run with `provenance:real`; clears `t3_deferred` cap | RIA standard |

**Critical reporting requirement.** All `<final-head>` placeholders MUST resolve to the W36 release_head. The W35 parent-HEAD-evidence pattern was accepted in the corrective window with the explicit `evidence_exemption.kind: "none"` mechanism; W36 should not repeat that pattern.

**Score implications.** RIA does not request a score-cap change in W36. The 75.0 cap continues to be governed by `soak_evidence_not_real`. Closing W36-S-1 produces measured soak data; whether and how that surfaces in the scorecard is hi-agent's call. The `t3_deferred` cap should clear at the W36 first manifest cycle that records a passing real-Volces T3.

---

## 5. Out of Scope for W36 (Explicitly Not Asking)

- **No new v1 contract routes added by this directive.** Phase 3 read routes (`list_recent_runs`, etc.) remain tracked for a future routes-extension directive.
- **No platform v2 contract work.**
- **No new chaos scenarios beyond the W34-roadmap two OS-limited.**
- **No defense-in-depth shims on the RIA side** (per AP-9). RIA's R-W1 wave does not mask any W36 carryover.
- **No additional acceptance criteria beyond §4.**

---

## 6. Reporting Format (For W36 Closure Notice)

Use the W34/W35 precedent. Per Rule 15 three-part closure for HIGH items, S-1 / S-2 / S-3 supplement closures should also carry the three-part summary:

```
### W36-<ID> closure (three-part)
(a) Code fix / plan / artifact: <commit SHA + file:line OR plan path>
(b) Recurrence-prevention check: <gate script + CI integration commit>
(c) Process change: <ARCHITECTURE.md or governance-doc section + line>
```

---

## 7. Cross-References

| Document | Purpose |
|---|---|
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-audit-2026-05-07.md` | RIA-internal audit (basis for this directive) |
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-directive-2026-05-05.md` | predecessor — the W35 corrective items |
| `D:\chao_workspace\research\docs\hi-agent-wave36-engineering-expectations-2026-05-05.md` | predecessor — W36 entry directive |
| `D:\chao_workspace\research\docs\ria\ria-engineering-plan-r-w1-2026-05-05.md` | RIA R-W1 plan (in flight) |
| `D:\chao_workspace\hi-agent\docs\downstream-responses\2026-05-05-w35-corrective-response.md` | hi-agent corrective response (lag-but-coherent) |
| `D:\chao_workspace\hi-agent\docs\releases\wave35-signoff.json` | latest signoff at HEAD `ad521c07` |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-06-wave-36-a3-tier1-retention-adoption.md` | A3 plan (BINDING) |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-06-wave-36-a5-boot-time-assertions.md` | A5 plan (BINDING) |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-06-wave-36-a4-schema-lineage-extensions.md` | A4 plan (BINDING) |

---

## 8. Acknowledgement

The W35 corrective work shows the discipline of a mature platform team — three-part closure executed uniformly, governance fixes that patch the actual scope hole rather than the symptom, evidence-honesty in the §5.2 asymmetry declaration. The W36 plans accept all 9 binding items without renegotiation and surface 7 additional hidden findings in the same plan documents.

The three supplement asks in §2 are not a comment on the quality of the W36 plans. They are the natural shape of completeness: A3/A5/A4 are the architectural-track plans; S-1/S-2 are the operations/release-track plans the directive named; S-3 is the governance-track plan-index that promotes the commit-message acceptance to a citable artifact. Three separate tracks, three separate plan files, one wave.

We expect renegotiation on specific S-1/S-2 acceptance criteria if the timeline is materially harder than estimated. We do not expect rebadging of the supplement asks as advisory; per Engineering Discipline 1.3, that is not a closure path.

---

**Signed:** RIA team
**Audit head (RIA side):** `main` at 2026-05-07
**Platform head under audit:** `ad521c07` (hi-agent W35 corrective-CLOSE)
**Document maturity:** M1 — internally reviewed; promotes to M2 when mirrored into hi-agent's `docs/upstream-directives/`.

---

**End of W35 Corrective Acceptance + W36 Supplement Directive.**
