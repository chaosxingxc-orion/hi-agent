# hi-agent Optimization Requests

**From:** Research Intelligence Application Team  
**To:** hi-agent Team  
**Date:** 2026-04-15  
**Reference:** `docs/superpowers/specs/2026-04-15-research-intelligence-app-design.md`

---

## Background

The Research Intelligence Application depends on hi-agent as its Layer 2 TRACE Runtime. This document records the gaps between what the architecture requires and what hi-agent currently provides, along with a prioritized list of optimization requests.

---

## Architecture Requirement Summary

hi-agent must serve as the execution substrate for a multi-agent research pipeline:

- **PI Agent**: long-running, strong model, persists across entire project lifecycle, holds cross-project memory
- **Phase Agents** (Survey, Analysis, Experiment, Writing Team): sub-Runs dispatched by PI Agent, each with distinct model tier, execution strategy, and restart policy
- **Multi-project isolation**: concurrent projects share no runtime state; isolation is enforced by `profile_id`
- **Memory hierarchy**: L0 raw stream → L1 STM → L2 Dream consolidation → L3 knowledge graph
- **TierRouter**: dynamically routes to light/medium/strong model based on task complexity and cost/quality history

---

## Gap Analysis

### Current State

Based on the existing upstream tracker (`docs/hi-agent-upstream-tracker.md` as of 2026-04-11), the following remain open:

| ID | Requirement | Status |
|---|---|---|
| P0-1 | Minimal successful run path | open |
| P0-2 | Readiness contract | open |
| P1-1 | Skill discovery contract | open |
| P1-2 | MCP provider layer | open |
| P1-3 | Plugin system | open |
| P1-4 | Research capability bundles | open |

The architecture spec introduced since then adds further requirements not yet tracked.

### Full Requirement vs. Capability Matrix

| Capability | Required By Architecture | hi-agent Current State | Gap |
|---|---|---|---|
| TRACE Run lifecycle (start/stop/checkpoint) | PI Agent + all phase agents | Unknown | Needs verification |
| Nested sub-Run dispatching | Writing Team (6 sub-runs under PI) | Unknown | Needs verification |
| profile_id-scoped run isolation | Multi-project concurrency | Unknown | Likely missing |
| Concurrent run management | Parallel projects | Unknown | Likely missing |
| MemoryManager L0 (hot append-only stream) | All agents | Unknown | Likely missing |
| MemoryManager L1 (STM per run) | All agents | Unknown | Likely missing |
| MemoryManager L2 (dream consolidation) | PI Agent | Unknown | Likely missing |
| MemoryManager L3 (long-term knowledge graph) | PI Agent cross-project | Unknown | Likely missing |
| Cross-project memory persistence | PI Agent evolution (P1) | Unknown | Missing |
| SkillLoader with workspace path resolution | All agents | Partial (manifest-only) | Contract undefined |
| TierRouter (light/medium/strong dispatch) | All agents, cost optimization (P2) | Unknown | Likely missing |
| TierRouter self-improvement from history | P2 cost reduction | Unknown | Missing |
| Execution strategy: sequential | PI, Analysis, Experiment, Writing | Unknown | Needs verification |
| Execution strategy: parallel_dag | Survey Agent | Unknown | Likely missing |
| Restart policy: reflect(N) | PI, Analysis, Writing | Unknown | Likely missing |
| Restart policy: retry(N) | Survey, Experiment | Unknown | Likely missing |
| Restart policy: retry + escalate | Experiment Agent | Unknown | Likely missing |
| Human Gate integration hook | All phase transitions (Gate type D) | Unknown | Likely missing |
| LLMGateway with provider abstraction | All agents | Partial | Needs contract |
| SkillLoader A/B versioning (ChampionChallenger) | Evolution Engine (P1) | Missing | Missing |
| PostmortemAnalyzer hooks | Evolution Engine (P1) | Missing | Missing |

---

## Optimization Requests

Requests are ordered by priority. P0 blocks any execution; P1 blocks research pipeline; P2 enables full product capabilities; P3 enables evolution/self-improvement.

---

### P0 — Execution Blockers

#### P0-1: Verified Minimal Run Path

**What we need:** A documented, tested path to create a TRACE Run, execute a single LLM call, and return a result. Must include:
- `RunExecutor.start(run_id, profile_id, model_tier, skill_dir)` API
- `RunExecutor.run(prompt)` → structured result
- `RunExecutor.stop()` teardown

**Why it's blocking:** Nothing in the research pipeline can be developed or tested without a working run path. All smoke tests are currently skipping on this gap.

**Acceptance criteria:**
- `hi_agent.RunExecutor` can complete a round-trip call in a test environment
- A passing integration test exists in hi-agent's own test suite
- API surface is documented in hi-agent's public interface

---

#### P0-2: Readiness Contract

**What we need:** A formal readiness check API that the research application can call at startup to verify the TRACE runtime is healthy:
- Model provider reachable
- Memory backend initialized
- Skill storage accessible

**Why it's blocking:** Without this, the research application cannot gate-check before dispatching agents, leading to silent mid-pipeline failures.

**Acceptance criteria:**
- `hi_agent.check_readiness() -> ReadinessReport` returns structured status per subsystem
- Unhealthy subsystems raise typed errors, not generic exceptions

---

### P1 — Research Pipeline Enablers

#### P1-1: profile_id-Scoped Run Isolation

**What we need:** Each `RunExecutor` instance is bound to a `profile_id`. All state (memory, skill context, logs) is scoped to that `profile_id`. Two concurrent runs with different `profile_id` values share zero runtime state.

**Why it's needed:** The research application runs multiple independent research projects in parallel. Without isolation, project A's knowledge graph and memory can contaminate project B.

**Acceptance criteria:**
- `RunExecutor(profile_id="proj-A")` and `RunExecutor(profile_id="proj-B")` produce independent memory namespaces
- Verified by an integration test that confirms no state leakage between profile IDs

---

#### P1-2: MemoryManager L0 + L1

**What we need:**
- **L0**: Append-only JSONL stream per run, persisted to the project's `logs/memory/L0/` path. No random-access writes — append only.
- **L1**: Short-term memory scoped to a single run. Cleared on run end. Supports `recall(query)` → top-K relevant entries.

**Why it's needed:** All agents need L1 for within-run context retention. PI Agent needs L0 as the raw experience record for later Dream consolidation.

**Acceptance criteria:**
- L0 log file exists and is append-only after run completes
- L1 `recall()` returns results ranked by semantic relevance
- L0 entries are structured JSONL (timestamp, run_id, content, metadata)

---

#### P1-3: Formal SkillLoader Contract

**What we need:** A defined interface for how skills are loaded at run start:
- `SkillLoader.load(skill_dir: Path) -> list[Skill]`
- Each `Skill` exposes: `name`, `description`, `system_prompt_fragment`, `tool_specs`
- Skills from the workspace `skills/` directory and from `projects/{name}/skills/` are both loadable

**Why it's needed:** Every agent in the research pipeline loads domain skills at startup. Currently skill loading is manifest-only — there is no execution-side binding.

**Acceptance criteria:**
- `SkillLoader` can load SKILL.md files from an arbitrary directory path
- Loaded skills can be injected into a RunExecutor's system prompt
- Loading an invalid SKILL.md raises a typed error with the file path

---

#### P1-4: Execution Strategies: sequential + parallel_dag + restart policies

**What we need:**
- `strategy="sequential"`: steps execute in order; failure stops the run
- `strategy="parallel_dag"`: steps with no dependency edges execute concurrently
- `restart_policy="reflect(N)"`: on failure, the agent receives a reflection prompt and retries up to N times
- `restart_policy="retry(N)"`: on failure, restart from last checkpoint up to N times
- `restart_policy="retry+escalate"`: retry N times; on exhaustion, surface to PI Agent for re-instruction

**Why it's needed:**
- Survey Agent uses `parallel_dag` to search multiple sources concurrently
- PI/Analysis/Writing use `reflect(N)` to self-correct before escalating
- Experiment Agent uses `retry+escalate` so PI Agent can adjust parameters on failure

**Acceptance criteria:**
- Strategy and restart policy are configurable per RunExecutor instance
- `reflect(N)` appends the failure trace + reflection prompt to context before retry
- `retry+escalate` produces a structured escalation event consumed by the parent Run

---

#### P1-5: Human Gate Integration Hook

**What we need:** A blocking hook in the run lifecycle that pauses execution at a defined gate point, surfaces structured output to the human console, and resumes only on human approval or override:

```
RunExecutor.register_gate(gate_id, gate_type="final_approval")
# ... run executes ...
# At gate point, run pauses and emits GateEvent
# Human Console receives GateEvent, human approves/overrides/backtracks
# RunExecutor.resume(gate_id, decision)
```

**Why it's needed:** Every phase transition in the research pipeline has a Human Gate D (final_approval). PI Agent synthesizes a recommendation; human confirms. Without this hook, the pipeline is fully automated with no human oversight.

**Acceptance criteria:**
- Run execution pauses at registered gate points
- Gate state is persisted so a paused run can survive process restart
- `GateEvent` includes: phase name, PI Agent recommendation, phase output summary
- Human approval / override / backtrack decisions are logged to the run record

---

### P2 — Full Product Capabilities

#### P2-1: TierRouter

**What we need:** Automatic routing of LLM calls to the appropriate model tier based on task classification:
- `light`: fast, cheap, simple extraction tasks
- `medium`: analysis tasks requiring moderate reasoning
- `strong`: planning, judgment, proof-level reasoning

Routing decisions are logged with cost and quality outcome data for later optimization.

**Why it's needed:** The architecture's P2 principle (cost continuously decreases) requires that not every call goes to the strongest model. Survey Agent uses `light→medium`; PI Agent uses `strong`; Experiment Agent uses `medium`.

**Acceptance criteria:**
- TierRouter classifies tasks and selects model accordingly
- Every routing decision is logged: task_id, tier_selected, cost, latency
- Tier can be overridden per RunExecutor config

---

#### P2-2: MemoryManager L2 (Dream Consolidation) + L3 (Knowledge Graph)

**What we need:**
- **L2 Dream**: Periodic batch job that reads L0 stream and consolidates into structured memories in L1. Runs between phases (triggered by PI Agent).
- **L3 Knowledge Graph**: Persistent, queryable graph of entities and relations. Backed by Neo4j. Supports Cypher queries. Survives project end and is available for cross-project retrieval.

**Why it's needed:** PI Agent's cross-project research intuition (P1 evolution principle) requires L3. Without memory consolidation, PI Agent's context window fills with raw logs rather than structured knowledge.

**Acceptance criteria:**
- L2 Dream job accepts a `run_id` and produces consolidated memory entries from L0
- L3 graph supports `add_node`, `add_edge`, `query(cypher)` operations
- L3 graph data persists to the project's `memory/` directory
- Cross-project L3 access is scoped by `profile_id`; Global Layer has its own namespace

---

#### P2-3: Nested Sub-Run Dispatching

**What we need:** A parent Run (PI Agent) can dispatch child Runs (phase agents) and collect their results:
```
pi_run.dispatch_subrun(
    agent="writing-team-author",
    profile_id=shared_profile_id,
    strategy="sequential",
    restart_policy="reflect(2)"
) -> SubRunHandle
result = pi_run.await_subrun(handle)
```

Sub-Runs share the parent's `profile_id` (and thus team shared memory/skills) but have their own run-scoped L1 memory.

**Why it's needed:** Writing Team = 6 sequential sub-Runs under PI Agent. Analysis Agent dispatches Lean 4 proof sub-Runs. Without nested dispatch, PI Agent cannot coordinate the team.

**Acceptance criteria:**
- Sub-Run inherits parent's `profile_id` and skill context
- Sub-Run failure does not crash the parent Run; it returns a structured failure result
- PI Agent can inspect sub-Run output before deciding to proceed or backtrack

---

### P3 — Evolution and Self-Improvement

#### P3-1: SkillLoader A/B Versioning (ChampionChallenger)

**What we need:** Skills have versioned identifiers (`paper-reading@v2` vs `paper-reading@v1`). The runtime can load two versions for the same agent role and route a percentage of runs to the challenger version. Outcome data (cost, quality score) is collected per version.

**Why it's needed:** The Evolution Engine promotes improved skills after each project. Without A/B infrastructure, skill improvements cannot be validated before global promotion.

**Acceptance criteria:**
- `SkillLoader.load(name, version="champion"|"challenger"|"v{N}")` resolves to correct version
- Challenger routing percentage is configurable (e.g., 20% of new runs)
- Outcome data is logged per (skill_name, version, run_id)

---

#### P3-2: TierRouter Self-Improvement from Historical Data

**What we need:** TierRouter reads its historical routing log and adjusts tier thresholds based on observed cost/quality outcomes. Specifically:
- If `light` tier produces acceptable quality for task class X, stop routing X to `medium`
- If `medium` tier consistently fails task class Y, auto-escalate Y to `strong`

**Why it's needed:** P2 (cost continuously decreases) cannot be achieved without adaptive routing. Manual tier configuration degrades over time as model capabilities improve.

**Acceptance criteria:**
- TierRouter has a `calibrate()` method that reads historical routing log and updates thresholds
- Updated thresholds are persisted and survive restart
- Calibration produces a diff report: which task classes changed tiers and why

---

## Summary Table

| ID | Title | Priority | Blocks |
|---|---|---|---|
| P0-1 | Verified minimal run path | P0 | All development |
| P0-2 | Readiness contract | P0 | Startup reliability |
| P1-1 | profile_id-scoped isolation | P1 | Multi-project |
| P1-2 | MemoryManager L0 + L1 | P1 | All agents |
| P1-3 | Formal SkillLoader contract | P1 | All agents |
| P1-4 | Execution strategies + restart policies | P1 | Pipeline execution |
| P1-5 | Human Gate integration hook | P1 | Human oversight |
| P2-1 | TierRouter | P2 | Cost optimization (P2 principle) |
| P2-2 | MemoryManager L2 + L3 | P2 | PI Agent intelligence |
| P2-3 | Nested sub-Run dispatching | P2 | Writing Team, Analysis |
| P3-1 | SkillLoader A/B versioning | P3 | Evolution Engine |
| P3-2 | TierRouter self-improvement | P3 | P2 cost principle automation |

---

## Recommended Delivery Sequence

```
Sprint 1: P0-1 + P0-2  →  unblocks local smoke tests
Sprint 2: P1-1 + P1-2 + P1-3  →  unblocks agent execution
Sprint 3: P1-4 + P1-5  →  unblocks pipeline execution with human gates
Sprint 4: P2-1 + P2-3  →  unblocks full pipeline + cost routing
Sprint 5: P2-2  →  unblocks PI Agent memory + cross-project intelligence
Sprint 6+: P3-1 + P3-2  →  evolution engine
```

---

## Open Questions for hi-agent Team

1. Does hi-agent currently have any form of `profile_id` or tenant isolation? What is the migration path to per-project isolation?
2. What is the current state of MemoryManager? Is L0/L1 partially implemented or entirely absent?
3. Does TierRouter exist as a concept in the current codebase, even without calibration logic?
4. What is the planned API surface for Human Gate hooks — event-driven or polling-based?
5. Is Lean 4 execution planned as a built-in capability or an external tool call via MCP?
