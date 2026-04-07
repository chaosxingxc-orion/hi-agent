# hi-agent

An enterprise-grade intelligent agent built on the **TRACE framework**: Task, Route, Act, Capture, Evolve.

## First Principles

- **P1**: The agent must continuously evolve
- **P2**: The cost of driving the agent must continuously decrease

## Quick Start

```bash
# Run a task via CLI
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# Start API server
python -m hi_agent serve --port 8080

# Resume a run from checkpoint
python -m hi_agent resume --checkpoint checkpoint_run-001.json

# Trigger memory Dream consolidation
curl -X POST http://localhost:8080/memory/dream

# Query knowledge
curl "http://localhost:8080/knowledge/query?q=revenue+trends&limit=5"

# Run tests
python -m pytest tests/ -v
```

## Architecture

```
TRACE = Task -> Route -> Act -> Capture -> Evolve

hi-agent (Agent Application Layer)
  |-- TRACE Runtime (Task View, Route Engine, CTS Stage Graph)
  |-- Context OS (Session, Memory, Knowledge, Skill)
  |-- Evolution Engine (Postmortem, Skill Extraction, Regression Detection)
  |-- Harness Orchestration (Dual-dimension governance)
  |
  v (durable contracts)
agent-kernel (Durable Runtime Substrate)
  |-- Run Lifecycle, Event Log, Checkpoint, Recovery
  |-- Temporal integration (optional)
  |
  v (execution requests)
agent-core (Capability Supply Layer)
  |-- Tools, Workflows, Retrieval, MCP
```

## Modules

### Context OS

| Module | Description |
|--------|-------------|
| **Session** (`session/`) | RunSession: unified state, compact boundary dedup, L0 JSONL persistence, checkpoint save/resume, CostCalculator. **Lifecycle: create→checkpoint→crash→resume→continue** |
| **Memory** (`memory/`) | Three-tier (short/mid/long-term). **Creation**: auto-build STM after each run. **Transfer**: Dream (short→mid) + Consolidation (mid→long). **Loading**: RetrievalEngine→routing context. **API**: `/memory/dream`, `/memory/consolidate`, `/memory/status` |
| **Knowledge** (`knowledge/`) | Wiki + user knowledge + graph + Mermaid. **Creation**: auto-ingest from session. **Transfer**: graph→wiki sync. **Loading**: four-layer retrieval (grep→BM25→graph→embedding). **API**: 6 endpoints (`/knowledge/ingest`, `/query`, `/sync`, `/lint`, `/status`) |
| **Skill** (`skill/`) | 5-stage lifecycle (Candidate->Provisional->Certified->Deprecated->Retired), registry, matcher (scope+preconditions), validator, usage recorder |

### TRACE Runtime

| Module | Description |
|--------|-------------|
| **Runner** (`runner.py`) | RunExecutor: S1->S5 stages, _execute_stage refactor, session resume from checkpoint, auto STM/knowledge creation, retrieval injection |
| **Route Engine** (`route_engine/`) | Rule-based, LLM-based, Hybrid, Skill-aware, Conditional routing. Context-aware prompts with stage summaries + fresh evidence |
| **Task View** (`task_view/`) | Layered context builder with token budgets, auto-compress trigger (snip->window->compress), context processor chain |
| **Contracts** (`contracts/`) | TaskContract (13 fields), PolicyVersionSet (6 versions), CTSBudget, TaskBudget |
| **Trajectory** (`trajectory/`) | Stage graph with reachability validation, dead-end detection, greedy optimizer |
| **State Machine** (`state_machine/`) | 6 formal TRACE state machines: Run, Stage, Branch, Action, Wait, Review |

### Governance & Evolution

| Module | Description |
|--------|-------------|
| **Harness** (`harness/`) | Dual-dimension governance (EffectClass + SideEffectClass), approval enforcement, evidence store |
| **Evolve** (`evolve/`) | Postmortem analyzer, LLM skill extraction, regression detector, champion/challenger comparison |
| **Failures** (`failures/`) | 10 frozen failure codes, FailureCollector, ProgressWatchdog, typed exceptions |
| **Human Gates** | Gate A (contract correction), B (route direction), C (artifact review), D (final approval) — auto-triggered |

### Infrastructure

| Module | Description |
|--------|-------------|
| **LLM Gateway** (`llm/`) | Provider-decoupled: OpenAI HTTP, Anthropic native, mock. Model router, budget tracker |
| **Runtime Adapter** (`runtime_adapter/`) | 17-method protocol, MockKernel, KernelFacadeClient (direct+HTTP), resilient adapter (retry+circuit breaker+event buffer) |
| **Config** (`config/`) | TraceConfig (95+ params, JSON/env/code), SystemBuilder (full wiring incl. memory/knowledge/resume) |
| **Server** (`server/`) | HTTP API (stdlib), RunManager, MemoryLifecycleManager, knowledge API, resume endpoint, CLI |
| **Orchestrator** (`orchestrator/`) | Task decomposition DAG, parallel dispatcher (ThreadPoolExecutor), result aggregator |

## Key Design Decisions

### Three-Tier Memory (P1 + P2)

```
Run ends ──→ auto-build STM ──→ ShortTermMemory (JSON)
                                       │
POST /memory/dream ─────────────→ DreamConsolidator ──→ DailySummary (JSON)
                                                              │
POST /memory/consolidate ──────→ LongTermConsolidator ──→ Graph nodes (JSON)
                                                              │
Next Run ──→ RetrievalEngine (4-layer) ──→ routing context ←──┘
```

**Lifecycle closed loop:**
- **Creation**: Auto-build STM after each run (success or failure)
- **Transfer**: Dream (short→mid, daily cron) + Consolidation (mid→long, weekly)
- **Loading**: RetrievalEngine injects knowledge into routing context per-stage
- **API**: `POST /memory/dream`, `POST /memory/consolidate`, `GET /memory/status`

### Four-Layer Retrieval (P2)

```
Query --> L1: grep (0 cost) --> L2: BM25 (0 cost) --> L3: Graph expand (0 model cost) --> L4: Embedding (optional)
          ~50 candidates        ~10 ranked            Mermaid + summaries               cosine rerank
```

99% of retrievals cost zero LLM calls. Embedding only for final ~8 candidates when API key available.

### Context Compression Pipeline (P2)

```
Stage start --> AutoCompressTrigger --> Snip/Window/Compress --> mark compact boundary
            --> build_context_for_llm() --> only fresh content + L1 summaries (deduped)
            --> route_engine.propose() --> LLM sees full history without duplication
```

Inspired by claude-code's three-layer lazy compaction (snip -> microcompact -> autocompact).

### Knowledge System (P1 + P2)

Three knowledge types with three representation layers:
- **Storage**: Graph (nodes + edges + confidence) -- for computation
- **LLM Interface**: Wiki (Markdown + `[[wikilinks]]` + YAML frontmatter) -- for LLM read/write
- **Visualization**: Mermaid (auto-generated flowcharts/mindmaps) -- for human understanding

**Lifecycle closed loop:**
- **Creation**: Auto-ingest from session (findings→wiki, facts→graph, feedback→user profile)
- **Transfer**: `POST /knowledge/sync` (graph→wiki pages + rebuild index)
- **Loading**: Four-layer retrieval (grep→BM25→graph→embedding) injected into routing
- **Health**: `POST /knowledge/lint` (orphan pages, broken links, stale content)
- **API**: 6 endpoints (`/knowledge/ingest`, `/ingest-structured`, `/query`, `/sync`, `/lint`, `/status`)

### Session Resume (P2)

```
Run executing ──→ checkpoint saved every Stage (JSON)
     │
  crash / stop
     │
  python -m hi_agent resume --checkpoint <path>
  POST /runs/{id}/resume
     │
  load checkpoint ──→ restore L0/L1/events/costs/boundaries
     │
  skip completed stages ──→ continue from interruption point
     │
  finalize (STM + knowledge + evolve) ──→ done
```

## Stats

| Metric | Value |
|--------|-------|
| Source files | 212 |
| Test files | 184 |
| Source LOC | 25,108 |
| Tests | 1,616 passing |
| Modules | 26 |
| External deps | 0 |
| Config params | 95+ (all configurable) |

## Configuration

All parameters configurable via three methods:

```python
# Code
config = TraceConfig(compress_snip_threshold=100, default_model="claude-sonnet-4")

# JSON file
config = TraceConfig.from_file("production.json")

# Environment variables (HI_AGENT_ prefix)
# HI_AGENT_DEFAULT_MODEL=claude-sonnet-4
config = TraceConfig.from_env()
```

## Documentation

| Document | Location |
|----------|----------|
| Architecture design (V2.0) | `architecture-review/` |
| Module evolution analysis | `docs/module-evolution-analysis.md` |
| Agent-kernel integration proposal | `docs/agent-kernel-integration-proposal.md` |

## License

See LICENSE file.
