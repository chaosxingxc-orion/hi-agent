# hi-agent Platform Response to Research Roadmap 2026-04-16

**Date**: 2026-04-24
**From**: hi-agent Platform Team
**To**: Research Intelligence App Team
**Re**: Strategic Roadmap (2026-04-16) — Platform Gap Response

---

## Executive Summary

Overall readiness has improved from 43% to 46% since the 2026-04-16 assessment. The primary gains are in Execution Engine (+5%) and Memory Infrastructure (+5%), driven by completion of the async path alignment work and memory scoping improvements delivered this sprint.

We formally accept all 7 platform gaps (P-1 through P-7) with the phasing described below. We maintain the Neo4j decline (P2-2) and TierRouter calibration deferral (P3-2) from our previous response.

---

## Gap Acceptance and Phasing

**P-1 (Provenance standard — HIGH)**: Accepted. We will design `RawMemoryEntry.provenance` and `CapabilitySpec.source_reference` in Phase 2 Q2. A design draft (`docs/specs/provenance-spec.md`) will be shared for review before implementation begins. P-5 confidence scoring will be co-designed in the same batch to avoid a second design round.

**P-2 (Reasoning trace storage — HIGH)**: Accepted. We will build a structured side-channel for stage LLM reasoning steps in Phase 2, after the P-1 provenance foundation is in place. The storage interface will be platform-owned; the research team defines what goes into the trace.

**P-3 (Cross-Run Project aggregation — HIGH)**: Accepted. Currently at 0% readiness. This is Phase 2 priority work. We will design a `project_id` scope model analogous to the existing `profile_id` pattern, enabling memory to span multiple runs under a single project. Design draft will be shared before implementation.

**P-4 (Dynamic re-planning API — MEDIUM)**: Accepted. Targeting Phase 3. The current TRACE loop is static by design; we need an API design pass before touching the state machine. `StageDirective(skip_to, insert_stage)` is the target contract.

**P-5 (Confidence scoring contract — MEDIUM)**: Accepted. Co-designed with P-1 in Phase 2. `Artifact.confidence: float` and `evidence_count` fields will be added to the output contract. Research team defines the scoring logic; platform owns the field contract.

**P-6 (Knowledge Graph inference layer — MEDIUM)**: Accepted with constraint. Targeting Phase 3. JSON-backed `LongTermMemoryGraph` will be extended to support transitive queries and conflict detection. Neo4j (P2-2) remains permanently declined — the JSON-backed implementation satisfies all required graph operations at our scale without introducing an external service dependency.

**P-7 (Feedback integration path — MEDIUM)**: Accepted. Targeting Phase 3. `EvolveEngine` hooks exist; we will wire `submit_run_feedback()` to the ingestion path. Research team defines the evaluation metrics; platform owns the ingestion interface.

---

## Capability Pattern Status

**PI-A (Multi-stage TRACE pipeline execution)**: Stable and supported. This is the production baseline all downstream runs use today.

**PI-B (PI-A + reflect_and_infer + restart_policy)**: Supported. The recursion guard (K-7) is under review in the current sprint; the pattern is usable with the existing depth limit.

**PI-C (PI-B + Human Gate)**: Supported. Gate lifecycle fixes were delivered in the most recent wave. `GatePendingError` + `continue_from_gate` round-trip is production-ready.

**PI-D (PI-B + dispatch_subrun + await_subrun_async)**: Supported. Async path parity was confirmed this sprint — `execute_async()` now correctly sets `_run_id` and initializes timing invariants. Sequential real-LLM runs 2 and 3 reuse the same gateway instance without `Event loop is closed` errors.

**PI-E (PI-C + PI-D combined)**: Supported. The combination of gate + subrun orchestration in a single run is the target for an end-to-end combination test (K-13) added to the backlog. No known integration failures; the gap is test coverage, not runtime behavior.

---

## What We Are Not Doing

**P2-2 (Neo4j-backed L3)**: Permanently declined. This was declined in our prior response and the position has not changed. JSON-backed `LongTermMemoryGraph` covers all required graph operations at current scale. Adding Neo4j would create an external service dependency without functional gain.

**P3-2 (TierRouter.calibrate())**: Indefinitely deferred. No quality-scoring mechanism exists to drive calibration. We will revisit when the feedback path (P-7) is operational.

---

## Next Milestone

Phase 2 kickoff: P-1 (Provenance), P-3 (Project aggregation), P-5 (Confidence scoring) design — target Q2 2026. We will send a design draft for review before implementation begins.

The authoritative gap tracking table is maintained at `docs/platform-gaps.md` and updated after each delivery wave.
