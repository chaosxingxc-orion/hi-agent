# Wave 36 Plan Index & Acceptance (§0 Disposition)

**Date:** 2026-05-07
**Wave:** W36 binding
**Reference:** RIA W36 entry directive §4.1 + supplement directive §2.3
**Status:** §0 disposition — promotes commit-message acceptance (276917d8) to citable artifact
**Predecessor (commit-only):** 276917d8 "ALL 9 RIA items accepted as binding"

> **Last refreshed:** 2026-05-07. HEAD `975b7911`.

---

## §0 — Wave 36 Acceptance Statement

We accept all 9 RIA-binding items for Wave 36 as binding-as-written. None violates G1
(capability-layer only); each strengthens contracts we already promised. The three
W36 supplement asks (S-1 / S-2 / S-3) issued in the 2026-05-07 supplement directive
are likewise accepted as binding; this document is itself S-3.

The acceptance statement previously lived only in commit message `276917d8`
("ALL 9 RIA items accepted as binding (6 W35 corrective + 3 W36 HIGH). None
violates G1; each strengthens contracts we already promised."). Per RIA
supplement directive §2.3 a commit message is not a citable artifact at the same
maturity level as a plan file; this document promotes the acceptance to a citable
artifact and indexes the owning plan-file for every binding item.

---

## Binding Items Table (W36 entry directive §4.1)

The 9 entry-directive items split into 6 W35 corrective carry-forwards (already
closed in the W35 corrective window at HEAD `ad521c07`) and 3 W36 HIGH
architectural items (plans published 2026-05-06).

| # | ID | Source directive | Plan file | Owner track | Disposition |
|---|---|---|---|---|---|
| 1 | C-1 corrective | W35 corrective directive §1 | (closed in W35-corrective-CLOSE) | TE | ACCEPTED — closed at HEAD `ad521c07` |
| 2 | C-2 corrective | §2 | (closed) | GOV | ACCEPTED — closed |
| 3 | C-3 corrective | §3 | (closed) | RO | ACCEPTED — closed |
| 4 | C-4 corrective | §4 | (closed) | RO | ACCEPTED — closed |
| 5 | §5.1 wave-ledger | §5.1 | (closed) | GOV | ACCEPTED — closed |
| 6 | §5.2 captain artifacts | §5.2 | (closed) | GOV | ACCEPTED — closed |
| 7 | A3 Tier-1 retention 8 stores | W36 entry §3.1 | docs/superpowers/plans/2026-05-06-wave-36-a3-tier1-retention-adoption.md | RO + TE + DX | ACCEPTED — plan published 2026-05-06 |
| 8 | A5 boot-time B1–B14 | W36 entry §3.2 | docs/superpowers/plans/2026-05-06-wave-36-a5-boot-time-assertions.md | DX + AS-RO + RO | ACCEPTED — plan published 2026-05-06 |
| 9 | A4 schema-shape lineage | W36 entry §3.3 | docs/superpowers/plans/2026-05-06-wave-36-a4-schema-lineage-extensions.md | AS-CO + CO + RO + DX | ACCEPTED — plan published 2026-05-06 |

The 6 corrective rows are documented at M2 in `docs/downstream-responses/2026-05-05-w35-corrective-response.md`
(reissued PASS) and verified by RIA in their 2026-05-07 acceptance audit.

---

## Supplement Items Table (W36 supplement directive 2026-05-07)

The supplement directive §2 named three additional asks. None is new scope; each
was named in the W36 entry directive but not yet covered by a plan-file artifact.
Acceptance below is binding-as-written; no item is renegotiated, deferred, or
rebadged as advisory.

| # | ID | Source | Plan file | Owner | Disposition |
|---|---|---|---|---|---|
| 10 | S-1 6h Linux soak | supplement §2.1 | docs/superpowers/plans/2026-05-07-wave-36-linux-soak.md | TE + GOV + DX | ACCEPTED — plan published 2026-05-07 |
| 11 | S-2 Postgres equivalence | supplement §2.2 | docs/superpowers/plans/2026-05-07-wave-36-postgres-equivalence.md | RO + GOV + TE | ACCEPTED — plan published 2026-05-07 |
| 12 | S-3 plan-index | supplement §2.3 | docs/superpowers/plans/2026-05-07-wave-36-plan-index.md (this file) | GOV | ACCEPTED — this document |

S-1 and S-2 acceptance carries the "not tuned for cap retirement" framing per
RIA supplement directive §2.1 — the 6h soak measures architectural feasibility,
not capacity, and the `soak_evidence_not_real` cap stays / retires / reframes
strictly per measured outcome.

---

## Hidden Findings Cross-Reference

The W35 systematic audit catalogued 91 hidden findings (`docs/governance/systematic-audit-w35-2026-05-05.md`).
RIA's 2026-05-07 acceptance audit §4 surfaced an additional 7 hidden findings
within the W36 plans themselves:

- **HF-1** A3 plan: `harness/evidence_store.py` deprecated shim — disposition: delete in W36.
- **HF-2** A3 plan: `sqlite_task_view_log.py` no instantiation site — disposition: day-1 investigation.
- **HF-3** A3 plan: `SQLiteDedupeStore` missing `created_at` — disposition: migration day-1.
- **HF-4** A3 plan: `SqliteDecisionAuditStore` missing `tenant_id` — disposition: column-add or `# scope: process-internal`.
- **HF-5** A4 plan: `RuntimeEvent` lacks lineage entirely — disposition: Option A widening.
- **HF-6** A4 plan: `_status_dict` hand-built dict — disposition: wire-format risk remediated in Phase 2.
- **HF-7** A4 plan: `event_facade.render_sse_chunk` hand-built dict — disposition: Phase 3 SSE end-to-end.

All 7 are remediated **in-scope within their owning W36 plan**; none expands W36
scope. Future hidden findings (HF-8..HF-N) surfaced by ongoing self-audits during
the W36 corrective cycle will be appended here as the plan revisions land. The
cross-reference is one-way: HF-1..HF-7 each cite the plan that owns them; the
plans cite this index as the canonical hidden-finding ledger for W36.

---

## Architectural Cohesion

The 12 items split into three architectural tracks:

- **Architectural-track plans (7-8-9 + carry-forwards 1-6):** A3 retention,
  A5 boot-time, A4 schema lineage, plus the six corrective items closed at
  HEAD `ad521c07`. These are the binding correctness deliverables.
- **Operations/release-track plans (10-11):** S-1 6h Linux soak and S-2
  Postgres equivalence. These are measurement deliverables — they do not
  change platform contracts; they verify the platform under a richer workload
  shape than CI provides.
- **Governance-track plan (12):** this plan-index. Promotes commit-message
  acceptance to a citable artifact and serves as the canonical hidden-finding
  ledger for W36.

This architectural split is the canonical W36 layering. Each plan is owned by
one primary track but acceptance criteria reach across tracks where coordination
is explicit (B13 ↔ G-RIA-13 is the cross-team coordination point — see A5 plan
§3.3).

---

## Disposition Discipline

Per the W36 entry directive §7 and Rule 15 closure taxonomy, every row in the
above tables carries:

- An owning plan-file (or "closed in W35-corrective-CLOSE" for the carry-forwards).
- A maturity level cited inside the plan (or signoff for closed items).
- A disposition that is one of `ACCEPTED` / `RENEGOTIATED with rationale` /
  `DEFERRED with rationale`. Zero items in W36 carry `RENEGOTIATED` or
  `DEFERRED`.
- The owner-track triple (e.g. `RO + TE + DX`) names the primary owner first;
  co-owners follow per CLAUDE.md ownership-tracks discipline.

A commit-message-only acceptance does not satisfy this discipline. This document
is the structural fix.

---

## Cross-References

| Document | Purpose |
|---|---|
| `docs/superpowers/plans/2026-05-06-wave-36-a3-tier1-retention-adoption.md` | A3 plan (item 7) |
| `docs/superpowers/plans/2026-05-06-wave-36-a5-boot-time-assertions.md` | A5 plan (item 8) |
| `docs/superpowers/plans/2026-05-06-wave-36-a4-schema-lineage-extensions.md` | A4 plan (item 9) |
| `docs/superpowers/plans/2026-05-07-wave-36-linux-soak.md` | S-1 plan (item 10) |
| `docs/superpowers/plans/2026-05-07-wave-36-postgres-equivalence.md` | S-2 plan (item 11) |
| `docs/upstream-directives/2026-05-07-hi-agent-w35-corrective-acceptance-and-w36-supplement-directive.md` | Source directive (S-1/S-2/S-3 issuance) |
| `docs/upstream-directives/2026-05-07-hi-agent-w35-corrective-acceptance-audit.md` | Source audit (W35 corrective M2 closure verification) |
| `docs/upstream-directives/2026-05-05-hi-agent-wave36-engineering-expectations.md` | W36 entry directive (items 7-8-9) |
| `docs/upstream-directives/2026-05-05-hi-agent-w35-corrective-directive.md` | W35 corrective directive (items 1-6) |
| `docs/downstream-responses/2026-05-05-w35-corrective-response.md` | W35 corrective response (PASS — items 1-6 evidence) |
| `docs/releases/wave35-signoff.json` | Latest signoff (manifest `2026-05-06-ad521c07`) |
| `docs/governance/recurrence-ledger.yaml` | Ledger entry W32-D-recurrence (§5.1 process change) |
| `docs/governance/systematic-audit-w35-2026-05-05.md` | W35 hidden-findings audit (91 findings) |

---

## Sign-off

hi-agent platform team, 2026-05-07. Document maturity M1 (in-progress); promotes
to M2 when mirrored into RIA's directive cycle and when all three supplement
plan files (S-1 / S-2 / S-3) carry their first round of measured-evidence updates.
