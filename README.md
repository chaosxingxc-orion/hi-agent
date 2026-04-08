# hi-agent

An enterprise-grade intelligent agent built on the **TRACE framework**: Task, Route, Act, Capture, Evolve.

## First Principles

- **P1**: The agent must continuously evolve
- **P2**: The cost of driving the agent must continuously decrease

## Quick Start

```bash
# Run a task
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# Start API server
python -m hi_agent serve --port 8080

# Resume from checkpoint
python -m hi_agent resume --checkpoint checkpoint_run-001.json

# Memory & knowledge management
curl -X POST http://localhost:8080/memory/dream
curl "http://localhost:8080/knowledge/query?q=revenue+trends"
curl -X POST http://localhost:8080/skills/evolve

# Run tests
python -m pytest tests/ -v
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    hi-agent Architecture                      │
│                                                              │
│  Model-Driven Management                                      │
│  ┌──────────────────────────────────────────────────┐        │
│  │ ModelRegistry (gateway-registered, capability tags)│        │
│  │ TierRouter (purpose→strong/medium/light)          │        │
│  │ ModelSelector (budget-aware, downgrade/upgrade)    │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
│  Middleware Layer (independent contexts, ~86% cost savings)    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │Perception│→│ Control  │→│Execution │→│Evaluation│        │
│  │ (light)  │ │ (medium) │ │ (dynamic)│ │ (light)  │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│  5-phase lifecycle: pre_create→pre_execute→execute→          │
│                     post_execute→pre_destroy                  │
│  Extensible: add/replace/remove middlewares + custom hooks    │
│                                                              │
│  Task Management                                              │
│  ┌──────────────────────────────────────────────────┐        │
│  │ TaskScheduler (Superstep + Yield/Resume)          │        │
│  │ TaskCommunicator (notifications + signals)        │        │
│  │ TaskMonitor (heartbeat + deadlock detection)      │        │
│  │ TrajectoryGraph (chain/tree/DAG/general)          │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
│  Context OS                                                   │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐       │
│  │Context │ │Session │ │Memory  │ │Knowledge│ │Skill │       │
│  │Manager │ │+Resume │ │3-tier  │ │Wiki+    │ │Evolve│       │
│  │4-level │ │Chkpoint│ │+Dream  │ │Graph+   │ │A/B   │       │
│  │thresh. │ │        │ │        │ │4L-Retr. │ │Test  │       │
│  └────────┘ └────────┘ └────────┘ └────────┘ └──────┘       │
└──────────────────────────────────────────────────────────────┘
```

## Three Management Domains

### 1. Model-Driven Management

Models are **registered at runtime by LLM gateways**, not hardcoded. Each model carries capability tags (tier, cost, speed, context window, capabilities).

```
Gateway registers: claude-opus-4 (strong, $15/Mtok), gpt-4o-mini (light, $0.15/Mtok)
                         │
TierRouter maps:   perception→light, control→medium, execution→dynamic, evaluation→light
                         │
ModelSelector:     budget=$10 → select cheapest in tier → auto-downgrade if over budget
```

**Cost savings: ~81%** vs all-strong model usage.

### 2. Middleware Layer

Four middlewares with **independent context windows** (no shared LLM context):

| Middleware | Tier | Context | Responsibility |
|-----------|------|---------|----------------|
| Perception | light (~3K tok) | Input + session summary | Multimodal parse, entity extraction, summarization |
| Control | medium (~5K tok) | Request + capabilities | Decompose → TrajectoryGraph, resource binding |
| Execution | dynamic (~5K tok) | Current node + loaded resources | Retrieve skills/memory/knowledge, execute idempotently |
| Evaluation | light (~2K tok) | Result + quality criteria | Quality assess, reflection→Execution, escalation→Control |

**5-phase lifecycle** per middleware: `pre_create → pre_execute → execute → post_execute → pre_destroy`

Hook actions: CONTINUE, MODIFY, SKIP, BLOCK, RETRY

**Cost savings: ~86%** vs single shared context window.

### 3. Task Management

```
TrajectoryGraph (task execution plan)
    │
TaskScheduler (Superstep model)
    ├─ Find ready nodes → dispatch parallel
    ├─ Node B needs Node C → yield_task(B, blocked_by=[C])
    │   └─ Save B's session snapshot
    │   └─ Schedule C
    │   └─ C completes → resume_task(B, {C: result})
    └─ All terminal → ScheduleResult
```

- **TaskCommunicator**: Notifications (state changes) + Signals (commands) + Broadcast
- **TaskMonitor**: Heartbeat tracking, timeout-based stuck detection, DFS deadlock detection

## Context OS

### Session (checkpoint/resume)

```
Run → checkpoint every Stage (JSON) → crash → resume → skip completed → continue
```

### Memory (three-tier with Dream)

```
Run ends → auto-build ShortTermMemory
POST /memory/dream → DreamConsolidator → DailySummary
POST /memory/consolidate → LongTermConsolidator → Graph nodes
Next Run → RetrievalEngine (4-layer) → routing context
```

### Knowledge (wiki + graph + four-layer retrieval)

```
Run ends → auto-ingest findings→wiki, facts→graph, feedback→user profile
Query → L1:grep → L2:BM25 → L3:graph traverse+Mermaid → L4:embedding(optional)
POST /knowledge/sync → graph→wiki pages + rebuild index
```

### Skill (evolution pipeline)

```
SKILL.md discovery → SkillLoader (token-budget binary search: full/compact)
Execution → SkillObserver (async JSONL) → SkillMetrics
Analysis → SkillEvolver: textual gradient→new prompt / pattern→new skill
Deploy → SkillVersionManager: challenger@v1.3 (10% traffic) vs champion@v1.2
```

## API Endpoints (20+)

```
Tasks:      POST /runs, GET /runs/{id}, POST /runs/{id}/resume, GET /health
Memory:     POST /memory/dream, POST /memory/consolidate, GET /memory/status
Knowledge:  POST /knowledge/ingest, /ingest-structured, GET /query, POST /sync, /lint, GET /status
Skills:     GET /skills/list, /skills/{id}/metrics, /skills/{id}/versions,
            POST /skills/evolve, /skills/{id}/optimize, /skills/{id}/promote, GET /skills/status
Context:    GET /context/health
```

## Configuration

All 95+ parameters configurable via three methods:

```python
config = TraceConfig(compress_snip_threshold=100, default_model="claude-sonnet-4")
config = TraceConfig.from_file("production.json")
config = TraceConfig.from_env()  # HI_AGENT_* prefix
```

## Stats

| Metric | Value |
|--------|-------|
| Source files | 238 |
| Test files | 193 |
| Source LOC | 32,317 |
| Tests | 1,975 passing |
| Modules | 29 |
| External deps | 0 |
| Config params | 95+ |
| API endpoints | 20+ |

## Documentation

| Document | Description |
|----------|-------------|
| `architecture-review/` | Architecture design baseline (V2.0) |
| `docs/module-evolution-analysis.md` | Module gap analysis against P1/P2 principles |
| `docs/agent-kernel-integration-proposal.md` | 6-point kernel integration plan |
