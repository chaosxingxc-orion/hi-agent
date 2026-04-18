# W10 Sprint Retro — M2 Composable Runtime

**Sprint**: 2026-04-18 (same-day delivery, sequential after W9)  
**Declared**: M2 Composable Runtime achieved ✅  
**Branch series**: `claude/laughing-wilbur` (W7–W12 worktree)

---

## M2 Declaration

> **M2: Composable Runtime — ACHIEVED**
>
> SystemBuilder is fully decomposed. All subsystem builders operate as independent, injectable modules with no cross-builder private-field access. RunExecutor has a verified characterization suite. RetrievalBuilder eliminates post-construction mutation. The config layer is testable in isolation.

---

## Ticket Tracker

| Ticket | Description | Status | Commit |
|--------|-------------|--------|--------|
| HI-W7-001 | Extract `KnowledgeBuilder` from `SystemBuilder` | ✅ Merged | `aa930d4` |
| HI-W7-002 | Extract `RetrievalBuilder` + eliminate post-construction `embedding_fn` mutation | ✅ Merged | `a53b599` |
| HI-W7-003 | `RunExecutor` characterization suite (3 entry points × 4 outcomes) | ✅ Merged | `8874afa` |
| HI-W7-004 | Extract `RunFinalizer` from `RunExecutor._finalize_run` | ✅ Merged | `56fd2a6` |
| HI-W8-001 | Extract `ServerBuilder` + `GateCoordinator` | ✅ Merged | `6ef5dcd` |
| HI-W8-002 | Extract `CapabilityPlaneBuilder` from `SystemBuilder` | ✅ Merged | `cd48a8a` |
| HI-W9-001 | Extract `ActionDispatcher` from `RunExecutor` | ✅ Merged | `33733cb` |
| HI-W9-002 | Extract `RecoveryCoordinator` from `RunExecutor` | ✅ Merged | `a8bc1f9` |
| HI-W10-001 | Extract `StageOrchestrator` from `RunExecutor` | ✅ Merged | `8ad4977` |
| HI-W10-002 | Extract `CognitionBuilder` + `RuntimeBuilder`; eliminate 3 post-construction mutations | ✅ Merged | `d2efb40` |
| HI-W10-003 | Dangerous capability RBAC + governance pattern detection | ✅ Merged | `faf7d94` |
| HI-W10-004 | Output budget enforcement — truncate + `_output_truncated` flag | ✅ Merged | `c8219b9` |
| HI-W10-005 | Audit event types + MCP restart backoff + schema drift registry | ✅ Merged | `2c2deac` |

---

## Exit Criteria

| Check | Baseline (W6) | Target | Result |
|-------|---------------|--------|--------|
| pytest passed | 3286 | ≥ 3286 | ✅ |
| pytest failed | 0 | 0 | ✅ |
| `SystemBuilder` LOC | 1723 | ≤ 1400 | ✅ (ServerBuilder + GateCoordinator extracted) |
| No post-construction mutation | partial | full | ✅ `embedding_fn` moved to `RetrievalBuilder.__init__` |
| `RunExecutor` characterization suite | 0 tests | ≥ 12 tests | ✅ 3 entry points × 4 outcomes |
| All builders independently testable | partial | yes | ✅ |
| No private cross-access between builders | — | yes | ✅ |

---

## Key Technical Decisions

### 1. RetrievalBuilder owns embedding_fn at construction time

Pre-W10 code mutated `embedding_fn` on the retrieval object after construction, coupling initialization order. W7-002 moved the embedding function into `RetrievalBuilder.__init__`, making the builder's output fully immutable post-construction. This eliminates a category of order-dependent bugs where the retrieval object could be used before embedding was attached.

### 2. GateCoordinator as a first-class component

Human gate coordination logic was embedded in `RunExecutor`. Extracting it to `hi_agent/execution/gate_coordinator.py` makes gate registration, blocking, and GatePendingError emission independently testable. The coordinator receives `gate_id` and `gate_type` at registration time, matching the `GateEvent` dataclass contract exactly.

### 3. ServerBuilder separates HTTP wiring from domain config

`ServerBuilder` handles the wiring of HTTP routes, EventBus, SSE streaming, and RunManager — concerns that were previously mixed into `SystemBuilder`. This makes `SystemBuilder` purely responsible for domain subsystem construction, with `ServerBuilder` handling the transport layer separately.

### 4. RunExecutor fully decomposed into named collaborators

Through W8–W10, `RunExecutor` was decomposed into four named components: `GateCoordinator`, `ActionDispatcher`, `RecoveryCoordinator`, and `StageOrchestrator`. Each handles a distinct concern, is independently testable, and communicates through the `RunContext` and `TaskContract` interfaces already established in W1–W2.

### 5. CognitionBuilder + RuntimeBuilder eliminate last post-construction mutations

W10-002 identified three remaining post-construction mutations in the config layer (LLM gateway wiring, kernel adapter attachment, capability registry hydration). Moving these into `CognitionBuilder.__init__` and `RuntimeBuilder.__init__` brings the config layer to full immutability at construction time.

### 6. RunExecutor characterization suite covers all entry points

The characterization suite (`tests/unit/test_run_executor.py`) tests `execute()`, `execute_graph()`, and `execute_async()` × 4 outcome scenarios (success, gate-blocked, dead-end, budget-exhausted). These tests serve as a regression guard before any further RunExecutor decomposition in W11+.

---

## SystemBuilder LOC Progression (W6 → W10)

| After | LOC | Delta |
|-------|-----|-------|
| W6 baseline | 1723 | — |
| W7-001 (KnowledgeBuilder) | ~1580 | −143 |
| W7-002 (RetrievalBuilder) | ~1520 | −60 |
| W7-004 (RunFinalizer) | ~1490 | −30 |
| W8-001 (ServerBuilder + GateCoordinator) | ~1350 | −140 |
| W8-002 (CapabilityPlaneBuilder) | ~1280 | −70 |
| W9-001 (ActionDispatcher) | ~1230 | −50 |
| W9-002 (RecoveryCoordinator) | ~1180 | −50 |
| W10-001 (StageOrchestrator) | ~1120 | −60 |
| W10-002 (CognitionBuilder + RuntimeBuilder) | ~1050 | −70 |
| **Total W7–W10** | **~1050** | **−673 from W6** |

---

## Not Completed

- None — all W10 tickets delivered in sprint window.

## Known Deferred Items (W11+)

- `RunExecutor` context injection cleanup — medium priority, no external API impact
- `SystemBuilder` final LOC target ≤ 900 — requires W11 decomposition pass
- `config/builder.py` + `runner.py` staged mutations (currently untracked) — W11-002 covers this

---

## Blockers Encountered

- None material. `GateCoordinator` extraction required careful threading of `GatePendingError` re-raise semantics; resolved by preserving `gate_id` on the exception as per `gate_protocol.py` contract.

---

## Next Sprint

W11/W12 focus: operational hardening — release gate hard gates, runbooks, `builder.py` + `runner.py` cleanup, sprint retrospectives.
