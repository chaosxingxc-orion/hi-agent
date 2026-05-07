> **Mirrored from RIA on 2026-05-07.**
> Source: D:\chao_workspace\research\docs\hi-agent-w36-supplement-acceptance-and-s1-amendment-2026-05-07.md
> Maturity in this repo: M2 (mirrored to docs/upstream-directives/).
> See `docs/superpowers/plans/2026-05-07-wave-36-plan-index.md` for hi-agent's W36 §0 disposition.
> No content changes from source other than this preamble.

# hi-agent W36 Supplement Acceptance + S-1 Amendment

**Date:** 2026-05-07 (afternoon)
**From:** Research Intelligence Application (RIA) team — downstream platform consumer
**To:** hi-agent upstream engineering team
**Status:** Acceptance directive (M1 — internally reviewed; binding on the W36 supplement ramp). Closes the morning's W36 supplement directive cycle for S-2 / S-3 / reissued corrective response / 13-runbook hidden-fix; opens a 48h S-1 amendment window.
**Position:** Successor to `hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md`.

---

## 0. Standing on the W36 supplement cycle

This morning we issued the W36 supplement directive with three asks (S-1 6h Linux soak plan; S-2 Postgres equivalence plan; S-3 W36 §0 plan-index). Within the same business day hi-agent published all three plan files (commit `19a70c91`), reissued the W35 corrective-response document to PASS (same commit), and self-identified + closed 13 missing-runbook entries on top of the supplement work (commit `7ee6acaa`). RIA cross-checked each artifact at HEAD `7ee6acaa` against the supplement directive's acceptance criteria.

This turnaround speed plus the depth of the 13-runbook self-found work is **execution-track-mature work**. The retired "newcomer team" framing from our 2026-05-07 morning audit holds; this cycle reinforces the framing.

---

## 1. W36 supplement closure matrix

| Item | Status | Evidence cross-checked | Provenance |
|---|---|---|---|
| **S-2** Postgres equivalence plan | **ACCEPTED — compliant** | Plan at `docs/superpowers/plans/2026-05-07-wave-36-postgres-equivalence.md`. (a)–(d) all PASS with file:line citations: `HI_AGENT_TEST_POSTGRES_DSN` in `.github/workflows/postgres-equivalence.yml`; SQLite + Postgres legs at N=10/M=1 in `tests/integration/test_concurrency_persistence_swap.py`; deterministic terminal-state with `result: equal | divergent` per `concurrency-methodology-v1.md` §7; optional N=100 marked NOT-required. Three-part closure scaffolded (CI workflow + `check_postgres_equivalence_evidence.py` + methodology v1.1 §7.1+§7.2). | derived |
| **S-3** W36 §0 plan-index | **ACCEPTED — compliant** | Plan at `2026-05-07-wave-36-plan-index.md`. All 9 binding items present (6 W35 corrective + 3 W36 HIGH); all 12 rows ACCEPTED disposition (no RENEGOTIATED, no DEFERRED); §0 promotes commit `276917d8` message verbatim to citable artifact; cross-references all 5 plan files (A3 / A4 / A5 / S-1 / S-2). Additive content (Supplement-items table, HF-1..HF-7 hidden-findings ledger, three-track architectural-cohesion classification) is in-spirit with the directive, not scope creep. | derived |
| **W35 corrective-response reissue** | **ACCEPTED — clean** | `docs/downstream-responses/2026-05-05-w35-corrective-response.md` edited in-place; status now PASS for all 6 items (C-1, C-2, C-3, C-4, §5.1, §5.2); **C-3 closure level explicitly elevated from `code-fix-only` to `verified_at_release_head`**; M2 self-declared. Docs-only-gap exemption between manifest HEAD `ad521c07` and reissue HEAD `975b7911` declared via `check_doc_consistency.py` — clean, not concealed. No new defect / erratum surfaced. | measured |
| **13 missing-runbook hidden-fix** | **ACCEPTED — substantive** | Commit `7ee6acaa` adds 13 runbooks under `docs/runbooks/` (W28-A..G + W32-D/L/N/T + P0-W29 cycle + meta `wave-label-drift-in-recurrence-ledger.md`). Each runbook 42–90 lines, six grounded sections (what / when / diagnose / remediate / prevent / refs). Discharges Rule 15 three-part-closure debt: ledger `runbook_path` fields had pointed at vapor since W28/W32. **Runbook #13 is the META self-reflective entry on the W32-D scope hole that RIA W35 §5.1 surfaced** — exactly the self-policing artifact discipline RIA has asked for. | measured |

S-2, S-3, the reissue, and the 13-runbook addition close the supplement cycle for those four items. The W36 binding ramp can begin on those items immediately.

---

## 2. S-1 Amendment (48h SLA)

S-1 (6h Linux soak plan) is **PARTIAL** — strong on most criteria but contains one material renegotiation and one pre-authorization that exceeds the directive's stated scope. RIA requires three specific amendments before S-1 binds.

### 2.1 Amendment A-S-1-1 — `M=5 → M=1` renegotiation: explicit naming required

**Finding.** Plan L26 maps RIA's directive `N=50/M=5` (= 250 tenant/project workload pairs) onto `--projects-per-tenant 1` (= 50 pairs) by re-defining M from a workload knob ("projects per tenant") into a derived measurement ("M=5 average measured per-tenant via concurrency saturation"). The plan flags this as an interpretation choice rather than burying it; that is honest. But it is still a renegotiation of the directive's stated workload, and per Engineering Discipline 1.3 the right shape is to **name it as a deviation, not as compliance**.

**Disposition.** RIA **accepts** the concurrency-saturation reframe as an M-equivalent interpretation. We do not require `--projects-per-tenant 5` (the wall-clock cost would push the 6h band into infeasibility under GitHub `ubuntu-latest` constraints; the lock-contention / queue-depth observability under 50×1 with full 50-way concurrency is reasonably equivalent to 50×5 sequential traversal of 250 pairs).

**Required action.** Plan must update L26 (and all downstream sections that frame M=5) to explicitly read **"RIA-approved deviation per `hi-agent-w36-supplement-acceptance-and-s1-amendment-2026-05-07.md` §2.1: workload runs at `--projects-per-tenant 1` (50 pairs) rather than the directive's literal 50×5=250; rationale is concurrency-saturation equivalence under runner constraint."** The plan must NOT claim "matches directive" or treat M=5 and M=1 as semantically identical without the deviation marker.

**Acceptance criterion.** Plan revision lands a deviation marker citing this acceptance review by docs-link; downstream §"Workload Parameters" tables reflect M=1 explicitly, with M-equivalent (concurrency-saturation derived) reported separately.

### 2.2 Amendment A-S-1-2 — 4h fallback pre-authorization rejected

**Finding.** Plan §10 Risk-1 (L193) pre-authorizes a fallback to a 4h `provenance: real (240m)` band if GitHub free-tier billing ceiling is hit, without RIA approval. This embeds a degraded-outcome path inside the plan's contract.

**Disposition.** **REJECT the pre-authorization.** Whether to ship 4h instead of 6h is a feasibility-vs-capacity bandwidth decision and belongs to RIA, not to the plan. We do not anticipate the constraint will trigger — but if it does, the plan halts, RIA decides.

**Required action.** Plan must update §10 Risk-1 to read **"If GitHub `ubuntu-latest` budget ceiling is hit during the 6h band, halt the soak and request explicit RIA approval (48h SLA) before falling back to a 4h band. Do not ship `provenance: real (240m)` as W36-S-1 closure without this approval."**

**Acceptance criterion.** Plan §10 Risk-1 reads as above; CI workflow does not silently downgrade duration without an explicit operator gate.

### 2.3 Amendment A-S-1-3 — filename realignment

**Finding.** Plan L36 / §4.1 names the 6h band's evidence file `-soak-240m.json` (240m = 4h). Plan flags this as an open question for RIA — appropriate handling.

**Disposition.** **Rename.** The 6h band emits `-soak-6h.json` (or `-soak-360m.json` for full minute consistency); the 4h fallback band emits `-soak-240m.json`. Name-and-content alignment.

**Required action.** Plan updates evidence-filename convention. CI workflow + `check_soak_evidence.py` updated to match.

**Acceptance criterion.** Plan + workflow + check script all use `-soak-6h.json` for the primary band; `-soak-240m.json` reserved for the 4h fallback only.

---

## 3. Path-forward acceptance criteria

- **48h SLA for S-1 amendment landing**: target 2026-05-09. Three amendments above (A-S-1-1 / A-S-1-2 / A-S-1-3) closed in a single commit on the supplement track; plan revision republished in-place with a `Reissued: 2026-05-09 (S-1 amendment)` header.
- **Once S-1 amendments land**: RIA accepts S-1 as compliant; W36 binding ramp begins on A3 / A4 / A5 / S-1 / S-2 simultaneously.
- **`t3_deferred` cap clearance**: independent of this cycle. Cap clears at the next manifest cycle that records passing real-Volces with `provenance: real`. We do not require it to clear before the binding ramp; we expect it to clear naturally during the binding-ramp first manifest cycle.

---

## 4. Acknowledgement

The supplement cycle delivered:

1. **3 plan files in same business day** — S-1 / S-2 / S-3 published within hours of the directive landing.
2. **Reissued corrective response** with C-3 closure level explicitly upgraded to `verified_at_release_head` after the regression test landed — discipline-aligned promotion, not closure-claim inflation.
3. **13 self-identified runbook fillings** (Rule 15 three-part-closure debt from W28 / W32) including a META self-reflective entry on the W32-D scope hole that we surfaced in W35 §5.1. The platform team is now **discharging IOUs we did not know existed**.

The single S-1 amendment is not a comment on the supplement quality. It is a naming-discipline reminder (A-S-1-1) plus a feasibility-vs-capacity boundary clarification (A-S-1-2) plus a low-stakes rename (A-S-1-3). All three resolve in a single revision commit.

---

## 5. Cross-references

| Document | Role |
|---|---|
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md` | predecessor — supplement directive (issued morning of 2026-05-07) |
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-audit-2026-05-07.md` | predecessor — RIA-internal corrective acceptance audit |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-07-wave-36-linux-soak.md` | S-1 plan (subject of amendment §2) |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-07-wave-36-postgres-equivalence.md` | S-2 plan (ACCEPTED §1) |
| `D:\chao_workspace\hi-agent\docs\superpowers\plans\2026-05-07-wave-36-plan-index.md` | S-3 plan (ACCEPTED §1) |
| `D:\chao_workspace\hi-agent\docs\downstream-responses\2026-05-05-w35-corrective-response.md` | reissued corrective response (ACCEPTED §1) |
| `D:\chao_workspace\hi-agent\docs\runbooks\` | 13 new runbooks (ACCEPTED §1) |

---

**Signed:** RIA team
**Audit head (RIA side):** `main` at 2026-05-07 (afternoon)
**Platform head under audit:** `7ee6acaa` (hi-agent W36-supplement + 13-runbook hidden-fix)
**Document maturity:** M1 — internally reviewed; promotes to M2 when the S-1 amendment closes and binding ramp begins.

---

**End of W36 Supplement Acceptance + S-1 Amendment.**
