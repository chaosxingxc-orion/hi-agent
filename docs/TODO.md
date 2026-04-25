# hi-agent Engineering TODO

Last updated: 2026-04-25 (H2 wave started)

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

## DONE (Wave H1, DF-46, 2026-04-25)

- [x] DF-46 CI gate enforcement: scripts/check_t3_freshness.py + .github/workflows/claude-rules.yml step — 2026-04-25

## DONE (Wave H2, 2026-04-25)

- [x] **DF-47** I-6/F-5/F-6 reflection-path regression pins — `tests/integration/test_reflection_path_regression.py`
- [x] **DF-48** reasoning trace persistence regression pin — `tests/integration/test_reasoning_trace_persistence.py`
- [x] **DF-49** Rule 6 inline-fallback sweep — 12 sites fixed across `runner.py`, `evolve/engine.py`, `task_mgmt/scheduler.py`, `knowledge/knowledge_manager.py`
- [x] **C1** broken test collection (`test_skill_runtime_factory.py` deleted)
- [x] **C2/C3** `routes_profiles.py` tenant scope + Rule 7 observability
- [x] **K-13** PI-C + PI-D combination test (`tests/integration/test_picd_combination.py`)

## DEFERRED — DF-50

- **DF-50** `CapabilityDescriptor` schema duplication: `hi_agent/capability/registry.py:14-33` and `hi_agent/capability/adapters/descriptor_factory.py:9-35` have different schemas. Defer to consolidation refactor (H3 candidate).

## OPEN — H2 First-Run Concurrency Gate Findings (2026-04-25)

Discovered when running concurrency gate for the first time (H1 never ran it):

- **DF-51** `finished_at` is `null` on failed runs — `run_manager.py` does not populate `finished_at` when a run fails due to `queue_full` or other non-exception terminal states. Affects observability and Rule 7 lifecycle completeness.
- **DF-52** Idempotency race condition under concurrent load — 5 concurrent requests with the same `Idempotency-Key` each created a distinct run (5 run_ids, 5 × 201). The idempotency store write is not atomic under concurrent requests. Affects HTTP contract correctness.
- **DF-53** Run manager capacity=4 limits concurrent gate — `HI_AGENT_RUN_MANAGER_CAPACITY` defaults to 4; 20 concurrent runs overflow to `queue_full` failures. Not a defect per se but limits the concurrency gate's meaningful pass criteria. Document default and override in `docs/api-reference.md`.

## WARNING DEBT (low priority)

- Python 3.14 Windows SQLite `PytestUnraisableExceptionWarning` in agent_kernel
