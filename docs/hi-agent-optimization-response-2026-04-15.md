# hi-agent Optimization Response

**From:** hi-agent Team  
**To:** Research Intelligence Application Team  
**Date:** 2026-04-15  
**Re:** Optimization Requests (12 items + 5 open questions) — commit 42c9836

---

## Executive Summary

All 10 accepted requests across P0, P1, P2, and P3-1 have been implemented and are available as of commit 42c9836. Two items were declined or deferred with permanent reasoning below. All 5 open questions are answered in full.

---

## Delivery Table

| ID | Request | Status | Delivered API |
|---|---|---|---|
| P0-1 | Verified minimal run path | Delivered | `hi_agent.RunExecutorFacade` — `start(run_id, profile_id, model_tier, skill_dir)`, `run(prompt) -> RunFacadeResult`, `stop()` |
| P0-2 | Readiness contract | Delivered | `hi_agent.check_readiness() -> ReadinessReport` — `ready: bool`, `health: str`, `subsystems: dict` |
| P1-1 | profile_id-scoped isolation | Delivered | `LongTermMemoryGraph(profile_id=...)` — L3 path: `memory/L3/{profile_id}/graph.json`; all tiers are run-scoped by default |
| P1-2 | MemoryManager L0 + L1 | Delivered | `RawMemoryStore(run_id, base_dir)` — L0 JSONL at `logs/memory/L0/{run_id}.jsonl`, append-only; L1 `ShortTermMemoryStore` with `recall(query)` keyword-ranked |
| P1-3 | Formal SkillLoader contract | Delivered | `SkillDefinition.system_prompt_fragment` and `tool_specs` property aliases added; `SkillLoader.load(path)` accepts arbitrary directory |
| P1-4 | Execution strategies + restart policies | Delivered | `execute()` = sequential, `execute_graph()` = dynamic DAG, `execute_async()` = parallel; restart policy via `RestartPolicyEngine` constructor param (`reflect(N)` / `retry(N)` / `retry+escalate`) |
| P1-5 | Human Gate integration hook | Delivered | `RunExecutor.register_gate(gate_id, gate_type, phase_name, recommendation, output_summary)`; `RunExecutor.resume(gate_id, decision, rationale)`; `GateEvent` in `hi_agent.gate_protocol`; gate state persisted to session checkpoint |
| P2-1 | TierRouter | Delivered | `TierRouter` classifies by purpose + complexity, applies budget-pressure and skill-confidence downgrades; `TierAwareLLMGateway` wraps any `LLMGateway`; structured INFO log per decision: `{event, tier, model, purpose}` |
| P2-3 | Nested sub-Run dispatching | Delivered | `RunExecutor.dispatch_subrun(agent, profile_id, strategy, restart_policy) -> SubRunHandle`; `await_subrun(handle) -> SubRunResult`; sub-Run failure returns structured result, does not crash parent |
| P3-1 | SkillLoader A/B versioning | Delivered | `SkillLoader.get_skill(name, version="champion"\|"challenger"\|"v{N}")` — version-qualified lookup via `SkillVersionManager` |

---

## Declined / Deferred

### P2-2 (Neo4j) — Permanently Declined

The request asked for a Neo4j-backed L3 knowledge graph with Cypher query support. This is declined for the following reasons:

- `LongTermMemoryGraph` already implements all required operations: `add_node`, `add_edge`, `search`, `get_neighbors`, `get_subgraph(root, depth)`, and JSON persistence.
- Neo4j introduces a mandatory JVM + Docker service dependency. This violates our no-required-external-service constraint for the core runtime.
- At projected scale (hundreds to low thousands of nodes per project), the JSON graph handles all operations without performance degradation.
- Cross-project scoping by `profile_id` is already enforced via path namespacing (`memory/L3/{profile_id}/graph.json`).

The JSON-backed L3 graph is our permanent architecture. No Cypher API will be added. Teams needing graph query expressiveness can traverse the exported JSON.

### P3-2 (TierRouter `calibrate()`) — Deferred

`calibrate()` requires a quality signal: a definition of "acceptable quality for task class X." That signal is not yet defined. The Evolution Engine (P3 sprint) will design the quality scoring mechanism; `calibrate()` will be revisited once that mechanism produces a consumable signal. Deferral is indefinite until the quality scoring design is finalized.

---

## Open Questions Answered

**Q1: Does hi-agent currently have any form of `profile_id` or tenant isolation? What is the migration path?**

Yes. `profile_id` flows through `TaskContract` → `ConfigBuilder._resolve_profile()` → `ProfileRuntimeResolver`, which scopes the stage graph, action routes, and capability registry per profile. As of commit 42c9836, L3 long-term memory is also path-namespaced by `profile_id`. L0 and L1 are per-run (inherently isolated). Migration path: pass `profile_id` in `TaskContract` or `RunExecutorFacade.start()`.

**Q2: What is the current state of MemoryManager? Is L0/L1 partially implemented or entirely absent?**

All 4 tiers are fully implemented:

- **L0** (`RawMemoryStore`): append-only; as of this commit also persists to JSONL at `logs/memory/L0/{run_id}.jsonl`.
- **L1** (`ShortTermMemoryStore` + `MemoryCompressor`): per-run, keyword-ranked recall.
- **L2** (`RunMemoryIndex`): compact pointer-based stage outcome index; dream consolidation via `AsyncMemoryCompressor`.
- **L3** (`LongTermMemoryGraph`): persistent JSON graph with keyword search, tag/type filtering, BFS subgraph traversal, and `LongTermConsolidator` for dream consolidation from L0 to L3.

**Q3: Does TierRouter exist as a concept in the current codebase, even without calibration logic?**

Yes, fully implemented. `TierRouter` classifies by purpose and complexity (simple/moderate/complex), applies budget-pressure downgrade, skill-confidence downgrade, and a multi-level fallback chain. `TierAwareLLMGateway` wraps any `LLMGateway` and routes automatically. As of this commit, routing decisions are logged at INFO level with `{event, tier, model, purpose}`.

**Q4: What is the planned API surface for Human Gate hooks — event-driven or polling-based?**

Event-driven with session persistence. `register_gate()` opens a gate and writes a `gate_registered` event to the session checkpoint. `resume()` fires a `gate_decision` event (approved/override/backtrack) via `_emit_observability` and also persists to checkpoint. A paused run survives process restart because gate state is in the checkpoint.

Note: the gate does not yet automatically block stage execution. The current implementation is a lifecycle notification API — the caller controls the pause/resume flow. Full blocking semantics (automatic stage suspension at gate points) are on the roadmap.

**Q5: Is Lean 4 execution planned as a built-in capability or an external tool call via MCP?**

External tool call via MCP. Lean 4 is a domain capability, not a TRACE runtime primitive. The Experiment Agent registers a Lean 4 MCP server via `MCPBinding` and invokes it through `CapabilityInvoker`. This keeps the TRACE runtime domain-agnostic and avoids coupling the kernel to any proof assistant.

---

## Next Steps for the Research Application Team

### Step 1 — P0 smoke test (start here)

Verify the run path is functional in your environment before writing any pipeline code:

```python
from hi_agent import RunExecutorFacade, check_readiness

# 1. Check readiness
report = check_readiness()
assert report.ready, f"Runtime not ready: {report.health}"

# 2. Execute a minimal round-trip
facade = RunExecutorFacade()
facade.start(run_id="smoke-001", profile_id="proj-test", model_tier="light", skill_dir=None)
result = facade.run("Summarize the TRACE framework in one sentence.")
facade.stop()
assert result.success
```

### Step 2 — P1 integration

Once P0 passes, wire in the research pipeline components:

1. **profile_id isolation**: pass `profile_id="proj-{name}"` in `start()` for every project; confirm L3 paths are distinct.
2. **SkillLoader**: call `SkillLoader.load(Path("projects/{name}/skills/"))` and inject `skill.system_prompt_fragment` into the system prompt.
3. **Memory**: confirm L0 JSONL is written after each run; validate `RawMemoryStore` append behavior.
4. **Human Gates**: implement `register_gate` / `resume` at each phase transition; test process-restart recovery via checkpoint.
5. **Sub-Run dispatching**: integrate `dispatch_subrun` / `await_subrun` for the Writing Team (6 sequential sub-Runs).

### Step 3 — P2 / P3 (after P1 is green)

- Enable `TierAwareLLMGateway` for cost routing; inspect INFO logs to validate tier assignments match expected agent profiles.
- Enable champion/challenger A/B versioning for skills entering the Evolution Engine sprint.
- Defer `calibrate()` until quality scoring is defined.
