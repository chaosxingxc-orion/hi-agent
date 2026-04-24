# hi-agent Engineering TODO

Last updated: 2026-04-24

## DONE (Wave 1-4, SA-1..SA-8, 2026-04-22/24)

- SA-1..SA-8 self-audit: profile_id scoping, async stage graph, store registry
- DF-33..DF-40: Rule 8 gate teeth, structural + volces gate evidence
- W1-4: LLM path attribution, env isolation, run-scoped fallback events, gate teeth
- K-1/K-2/K-3/K-6/K-9/K-10/K-15: CLOSED-incidental (triage confirmed)
- Rule 7: tier_router run_id attribution (WS-1)
- Rule 8 gate: llm_fallback_count assertion (WS-1)
- K-4/K-5/K-7/K-8: executor_facade + context + dream_scheduler fixes (WS-2/3)
- K-11/K-12/K-13/K-14: test honesty + Language Rule (WS-4)
- Platform positioning docs, Rule 10 response (WS-5)
- [x] Round-8 downstream response written (`docs/hi-agent-optimization-response-2026-04-15-round8.md`) — 2026-04-24

## PENDING — Phase 2 (P-1, P-3, P-5 Design)

- P-1 Provenance: `RawMemoryEntry.provenance` field, `CapabilitySpec.source_reference`
- P-3 Cross-Run Project aggregation: `project_id` scope model design
- P-5 Confidence scoring: `Artifact.confidence: float` field
- docs/specs/provenance-spec.md (design draft)

## PENDING — Phase 3 (P-4, P-6, P-7)

- P-4 Dynamic re-planning API: `StageDirective(skip_to, insert_stage)`
- P-6 KG inference: transitive query + conflict detection on LongTermMemoryGraph (JSON)
- P-7 Feedback path: `submit_run_feedback()` → EvolveEngine

## ONGOING — DF-46 CI gate enforcement

- CI plan for Rule 8 mechanical enforcement in `.github/workflows/` (tracked DF-46)

## WARNING DEBT (low priority)

- Python 3.14 Windows SQLite `PytestUnraisableExceptionWarning` in agent_kernel
