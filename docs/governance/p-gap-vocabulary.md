# P-N Platform Gap Vocabulary (canonical)

**Effective from**: Wave 31 (W31-D, 2026-05-03 — D-1' fix).
**Authoritative source**: `docs/downstream-responses/2026-05-03-w30-delivery-notice.md`
§"Platform Gap Status (P-1 through P-7)" lines 101-113.
**Mirror**: `docs/platform-gaps.md` §"P-1 through P-7 Gap Status".

This file defines the canonical P-N slot vocabulary used in delivery notices, the
platform-gaps document, and the platform-capability-matrix. All future references to
P-1..P-7 MUST use these labels. The pre-W31 alternate taxonomy is retired.

---

## Canonical P-N Slots (W30 schema, frozen as of W30 close)

| Slot | Canonical Label | One-line Description |
|---|---|---|
| **P-1** | Long-running task | Long-running task stability — durable RunQueue, RunStore, TeamRunRegistry, cross-process restart through full server boot. |
| **P-2** | Multi-agent team | Multi-agent team runtime — TeamRunSpec contract, AgentRole/TeamSharedContext, durable team registry, cross-tenant route isolation. |
| **P-3** | Evolution closed-loop | Evolution closed-loop — ProjectPostmortem, CalibrationSignal, on_project_completed lifecycle hook, ExperimentStore + EvolveEngine. |
| **P-4** | StageDirective wiring | Dynamic re-planning — `StageDirective(skip_to, insert_stage)` mid-run plan mutation, posture-aware fail-closed, spine event kinds. |
| **P-5** | KG abstraction | Knowledge graph abstraction — `KnowledgeGraphBackend` Protocol, JSON + SQLite implementations, posture-aware factory, transitive/conflict-detection at L3. |
| **P-6** | TierRouter | LLM tier routing — TierRouter + TierAwareLLMGateway, active calibration via ingest_calibration_signal feedback loop. |
| **P-7** | ResearchProjectSpec | Research workspace model — research-team business-layer concept; platform offers `TeamRunSpec` as platform-neutral equivalent. Active integration is out-of-scope per Rule 10 + 3-gate intake. |

---

## Status Vocabulary

Each P-N slot carries a status drawn from the L0–L4 maturity model (Rule 13) plus two
P-N-specific qualifiers:

- **L0** — demo / not yet wired
- **L1** — tested component, not default path
- **L2** — public contract, schema/API stable, full tests
- **L3** — production default under research/prod posture
- **L4** — ecosystem ready (third-party can register/extend/upgrade/rollback)
- **PARTIAL** (P-4 only) — some directives wired, others pending
- **FULL** (P-4 only) — all `StageDirective` kinds wired in run_linear, run_graph, run_resume

A `(per W30 notice)` suffix on a P-N row asserts that the status field is byte-equal to
the W30 delivery notice and was not subsequently changed without a corresponding manifest
+ delivery-notice entry.

---

## History — why this vocabulary changed

### Pre-W31 (W23 → W30) — fractured P-N taxonomy

`docs/platform-gaps.md` used a P-N taxonomy oriented around W8–W10 platform-gap items:

| Slot | Pre-W31 Label (retired) | Where used |
|---|---|---|
| P-1 | Provenance standard | platform-gaps.md only |
| P-2 | Reasoning trace storage | platform-gaps.md only |
| P-3 | Cross-Run Project aggregation | platform-gaps.md only |
| P-4 | Dynamic re-planning API | platform-gaps.md and W30 notice agree |
| P-5 | Confidence scoring contract | platform-gaps.md only |
| P-6 | Knowledge Graph inference layer | platform-gaps.md only |
| P-7 | Feedback integration path | platform-gaps.md only |

W27, W28, W29, W30 delivery notices independently introduced a different P-N taxonomy
oriented around the post-W23 readiness scorecard ("Long-running task", "Multi-agent
team", etc.). The two taxonomies coexisted from W23 through W30, producing the **D-1'
schema fracture** finding logged in W31.

### W31 — adoption of W30 schema as canonical

W31-D (D-1' fix) adopts the W30 notice taxonomy as canonical because:

1. The W30 notice taxonomy maps cleanly to the post-W23 readiness scorecard dimensions.
2. The pre-W31 platform-gaps taxonomy mixed contract concerns (P-1 Provenance, P-5
   Confidence) with capability concerns (P-2 Reasoning trace, P-6 KG inference) — the
   W30 schema separates these into the L0–L4 readiness scorecard rows.
3. The downstream Research Intelligence App team had already begun citing the W30
   taxonomy in their W31 directive (§6 cites P-7 ResearchProjectSpec).

### Forward-compatibility rule

If a future wave needs to introduce a new gap slot (P-8 onwards), the slot:

- MUST be added to this file with a one-line description and a history note,
- MUST appear in the next delivery notice's "Platform Gap Status" table,
- MUST appear in `docs/platform-gaps.md` with byte-equal status,
- MUST NOT reuse a retired pre-W31 label without an explicit history note disambiguating
  the slot.

If a future wave needs to retire an existing slot, the slot row in this file is moved
to a "Retired Slots" subsection with an effective-from-wave annotation.

---

## Related Files

- `docs/platform-gaps.md` — current P-1..P-7 status table (mirrors W30 notice).
- `docs/platform-capability-matrix.md` — broader L-level capability surface.
- `docs/governance/maturity-glossary.md` — L0–L4 maturity vocabulary.
- `docs/governance/closure-taxonomy.md` — closure-level vocabulary (Rule 15).
- `docs/downstream-responses/2026-05-03-w30-delivery-notice.md` — authoritative W30
  notice with P-N status table.
