# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repository is in **active implementation — core subsystems complete, integration in progress**. The `architecture-review/` directory contains the full design baseline (V2.0).

## Current Implementation

| Module | Description |
|---|---|
| `hi_agent/contracts/` | Enriched TaskContract, PolicyVersionSet, CTSBudget |
| `hi_agent/evolve/` | Evolve subsystem (postmortem, LLM skill extraction, regression, champion/challenger) |
| `hi_agent/task_decomposition/` | DAG decomposition, executor, feedback |
| `hi_agent/orchestrator/` | Task orchestrator, parallel dispatcher, result aggregator |
| `hi_agent/harness/` | Harness governance (dual-dimension, approval, evidence) |
| `hi_agent/memory/` | Three-tier memory (short/mid/long-term), Dream consolidation, auto-creation after run, retrieval→routing injection, MemoryLifecycleManager |
| `hi_agent/knowledge/` | Wiki (Karpathy), user knowledge, graph renderer (Mermaid), four-layer retrieval (grep→BM25→graph→embedding), auto-ingest from session, 6 API endpoints |
| `hi_agent/server/` | HTTP API server, CLI, RunManager, MemoryLifecycleManager, knowledge API, resume endpoint |
| `hi_agent/runner.py` | RunExecutor with session resume, _execute_stage refactor, auto STM/knowledge creation, retrieval injection |
| `hi_agent/runtime_adapter/` | Kernel adapter protocol, mock, resilient adapter (retry+circuit breaker), real KernelFacadeClient |
| `hi_agent/session/` | RunSession (unified state), compact boundary dedup, CostCalculator, checkpoint save/resume |
| `hi_agent/config/` | TraceConfig (95+ params), SystemBuilder (full wiring incl. memory/knowledge/resume) |
| `hi_agent/skill/` | 5-stage lifecycle (Candidate→Retired), registry, matcher, validator, recorder |
| `hi_agent/failures/` | 10 failure codes (enum), FailureCollector, ProgressWatchdog, typed exceptions |
| `hi_agent/state_machine/` | Generic StateMachine + 6 TRACE definitions (Run/Stage/Branch/Action/Wait/Review) |
| `hi_agent/capability/` | Capability registry, invoker, circuit breaker |
| `hi_agent/events/` | Event emitter and store |
| `hi_agent/recovery/` | Compensation and recovery orchestration |
| `hi_agent/replay/` | Deterministic replay engine |
| `hi_agent/trajectory/` | Stage graph, optimizers, dead-end detection |
| `hi_agent/state/` | Run state persistence |
| `hi_agent/task_view/` | Task view builder, token budgets, auto-compress trigger, context processor chain |
| `hi_agent/llm/` | LLM Gateway (protocol, HTTP/OpenAI, Anthropic), model router, budget tracker |
| `hi_agent/route_engine/` | Rule, LLM, Hybrid, Skill-aware, Conditional routing with context-aware prompts |
| `hi_agent/observability/` | Metrics, tracing, notifications |
| `hi_agent/auth/` | RBAC, JWT, SOC guard |
| `hi_agent/management/` | Operations, gates, SLOs, alerts, reconciliation |

## Quick Start

```bash
# Run a task via CLI
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# Start API server
python -m hi_agent serve --port 8080

# Resume a run from checkpoint
python -m hi_agent resume --checkpoint checkpoint_run-001.json

# Run tests
python -m pytest tests/ -v
```

## Test Coverage

1616 tests, all passing. Zero external dependencies.

## System Overview

**hi-agent** is an enterprise-grade single-agent system built around the **TRACE framework**:

```
TRACE = Task → Route → Act → Capture → Evolve
```

The three-repository architecture:

- `D:\chao_workspace\hi-agent` (this repo) — the sole intelligent agent, owns all cognitive logic
- `D:\chao_workspace\agent-kernel` — durable runtime substrate (run lifecycle, event log, LLM Gateway, idempotency)
- `D:\chao_workspace\external\agent-core` — reusable capability modules integrated into hi-agent (tools, retrieval, MCP, workflows)

**Key principle**: `agent-core` is not a peer system — it is a capability module library integrated inside hi-agent. `agent-kernel` is not a peer system — it is the runtime substrate below hi-agent.

## Internal Structure

hi-agent is organized into three faces:

1. **TRACE Agent Runtime** — the agent itself:
   - Task Runtime, Route Engine, Context OS
   - Memory System, Knowledge System, Skill System
   - Evolution Engine, Harness Orchestrator

2. **Integrated Capability Modules** — selectively pulled from agent-core:
   - session, context resources, tool, workflow, sys_operation, retrieval, service_api, mcp, asset access

3. **Runtime Adapter** — thin adapter layer to agent-kernel:
   - `start_run / signal_run / query_run / query_trace_runtime`
   - `record_task_view / bind_task_view_to_decision`
   - `open_stage / mark_stage_state`
   - `open_branch / mark_branch_state / open_human_gate`

## 10 First-Class Concepts

| Concept | Definition |
|---|---|
| **Task** | A formal task contract, not raw user input |
| **Run** | A durable long-running task execution entity |
| **Stage** | A formal phase in task progression |
| **Branch** | A logical trajectory in the exploration space (semantic object, not a child run) |
| **Task View** | Minimal sufficient context rebuilt before each model call |
| **Action** | An external operation executed via Harness |
| **Memory** | What the agent has experienced — three tiers: short-term (session), mid-term (daily/dream), long-term (graph) |
| **Knowledge** | What the agent stably knows — wiki (text), user profile, knowledge graph (structured), four-layer retrieval |
| **Skill** | A reusable process unit crystallized from quality traces |
| **Feedback** | Optimization signals from results, evaluations, and experiments |

## CTS: Constrained Trajectory Space

The core runtime mechanism. Two layers:
- **Stage Graph** — defines allowed phases, transitions, permitted actions per stage, when to backtrack, when to trigger Human Gates
- **Trajectory Tree** — records actual branches explored in a run

Default stage sequence: S1 Understand → S2 Gather → S3 Build/Analyze → S4 Synthesize → S5 Review/Finalize

## Responsibility Boundaries

**hi-agent owns:**
- Task Contract semantics, CTS/Stage Graph definition, Route Policy
- Task View selection strategy
- Memory/Knowledge semantics, Skill lifecycle
- Evaluation logic, Evolution (Evolve) logic
- Harness semantic orchestration

**agent-kernel owns (hi-agent must NOT duplicate):**
- Run lifecycle, durable runtime, wait/resume/callback/recovery
- Event log, projection, replay metadata
- LLM Gateway, harness execution governance
- Idempotency, arbitration, policy version pinning

**agent-core provides (hi-agent integrates selectively):**
- session, context resources, tools, workflows, sys_operations, retrieval, service APIs, MCP, asset access
- Does NOT own: routing, task view selection, evolve logic, runtime truth

## Key Design Documents

All in `architecture-review/`. Documents marked [implemented] have corresponding code in `hi_agent/`.

- `2026-04-05-trace-architecture-design-v2.0.md` — authoritative design baseline [implemented]
- `2026-04-05-trace-spec-contracts-and-interfaces-v2.0.md` — interface contracts and specs [implemented]
- `2026-04-05-trace-runtime-arbitration.md` — callback/timeout/recovery arbitration rules [implemented]
- `2026-04-05-trace-contract-mapping.md` — contract mapping to agent-kernel APIs [implemented — mock adapter]
- `2026-04-05-agent-kernel-systematic-assessment.md` — gap analysis of agent-kernel [reference]
- `2026-04-05-agent-kernel-negotiation-review.md` — negotiation outcomes with kernel team [reference]

## Human Gate Types

- **Gate A** (`contract_correction`) — modify task contract mid-run
- **Gate B** (`route_direction`) — guide path selection
- **Gate C** (`artifact_review`) — review/edit outputs
- **Gate D** (`final_approval`) — gate high-risk final actions

## Standard Failure Codes

`missing_evidence`, `invalid_context`, `harness_denied`, `model_output_invalid`, `model_refusal`, `callback_timeout`, `no_progress`, `contradictory_evidence`, `unsafe_action_blocked`, `budget_exhausted`
