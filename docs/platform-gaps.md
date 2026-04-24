# hi-agent Platform Gaps — Response to Research Roadmap 2026-04-16

**Last updated**: 2026-04-24
**Source**: research/docs/hi-agent-strategic-roadmap-2026-04-16.md
**Contact**: hi-agent platform team

---

## Overview

hi-agent is the **capability platform layer**. The research team is the **business application layer**. This document formally responds to each platform gap identified in the 2026-04-16 roadmap using downstream's vocabulary.

---

## P-1 through P-7 Gap Status

| Gap | Research Priority | hi-agent Status | Target Phase |
|---|---|---|---|
| **P-1** Provenance standard — `RawMemoryEntry.provenance` field, `CapabilitySpec.source_reference` contract | HIGH | **Accepted**. Design spec to be written in Phase 2 (docs/specs/provenance-spec.md). Implementation in Phase 2 Q2. P-5 confidence scoring will be co-designed in the same batch. | Phase 2 |
| **P-2** Reasoning trace storage — structured side-channel for stage LLM reasoning steps | HIGH | **Accepted**. Phase 2 design after P-1 foundation is laid. | Phase 2 |
| **P-3** Cross-Run Project aggregation — `project_id` scope alongside `profile_id`; memory spanning multiple runs | HIGH | **Accepted**. Currently 0% readiness. Phase 2 priority work. Will design `project_id` scope model (analogous to existing `profile_id` pattern). | Phase 2 |
| **P-4** Dynamic re-planning API — `StageDirective(skip_to, insert_stage)` mid-run plan mutation | MEDIUM | **Accepted**. Phase 3. TRACE loop currently static; API design needed first. | Phase 3 |
| **P-5** Confidence scoring contract — `Artifact.confidence: float`, `evidence_count` fields | MEDIUM | **Accepted**. Co-designed with P-1 (provenance). Phase 2. | Phase 2 |
| **P-6** Knowledge Graph inference layer — transitive queries, conflict detection on `LongTermMemoryGraph` | MEDIUM | **Accepted** (JSON-backed only; Neo4j permanently declined per P2-2 precedent). Phase 3. | Phase 3 |
| **P-7** Feedback integration path — `submit_run_feedback()` API wired to `EvolveEngine`/`HybridRouteEngine` | MEDIUM | **Accepted**. Phase 3. `EvolveEngine` hooks exist; ingestion path TBD. | Phase 3 |

---

## Readiness Delta (2026-04-16 → 2026-04-24)

| Dimension | 2026-04-16 | 2026-04-24 | Delta | Driver |
|---|---|---|---|---|
| Execution Engine (TRACE) | 75% | 80% | +5% | K-defects resolved, async parity (K-2/K-3/K-15) confirmed fixed |
| Memory Infrastructure (L0–L3) | 70% | 75% | +5% | profile_id scoping hardened (SA-1..SA-3, K-9/K-10 confirmed) |
| Capability Plugin System | 65% | 67% | +2% | Rule 7 observability improved (tier_router run_id attribution) |
| Knowledge Graph | 35% | 35% | 0% | No changes this wave |
| Planning & Re-planning | 40% | 40% | 0% | No changes this wave |
| Artifact / Output Contracts | 30% | 30% | 0% | No changes this wave |
| Evolution & Feedback | 20% | 20% | 0% | No changes this wave |
| Cross-Run State (Project) | 0% | 0% | 0% | P-3 planned for Phase 2 |
| **Overall** | **43%** | **46%** | **+3%** | |

---

## PI-A through PI-E Pattern Support

| Pattern | Description | Status |
|---|---|---|
| PI-A | Multi-stage TRACE pipeline execution | Supported (stable) |
| PI-B | PI-A + reflect_and_infer + restart_policy | Supported (K-7 recursion guard in review) |
| PI-C | PI-B + Human Gate (GatePendingError + continue_from_gate) | Supported (gate lifecycle fixed in Wave 3-4) |
| PI-D | PI-B + dispatch_subrun + await_subrun_async | Supported (async path parity confirmed K-2/K-3/K-15) |
| PI-E | PI-C + PI-D (gate + subrun orchestration) | Supported (combination test K-13 added to backlog) |

---

## Permanently Declined

| Ask | Reason |
|---|---|
| P2-2: Neo4j-backed L3 with Cypher | Permanently declined. JSON-backed `LongTermMemoryGraph` satisfies all required graph operations at our scale. Neo4j adds external service dependency without functional gain. |
| P3-2: `TierRouter.calibrate()` | Indefinitely deferred pending quality-scoring mechanism. |
