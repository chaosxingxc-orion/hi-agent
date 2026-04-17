# hi-agent

`hi-agent` is an enterprise agent system built around the **TRACE** loop:

- `T`: Task understanding
- `R`: Route decision
- `A`: Action execution
- `C`: Capture memory/evidence
- `E`: Evolve skills

It provides orchestration, middleware, routing, memory, knowledge, skill evolution, and server APIs.  
Durable runtime behaviors are backed by `agent-kernel`.

## Quick Start

```bash
git submodule update --init --recursive
python -m pip install -e ".[dev]"
```

Run locally:

```bash
python -m hi_agent run --goal "Analyze quarterly revenue data" --local
```

Start API server:

```bash
python -m hi_agent serve --host 127.0.0.1 --port 8080
```

## CLI

```bash
python -m hi_agent --help
```

Main commands:

- `serve`: start API server
- `run`: execute a task
- `status`: query run status
- `health`: check system health
- `readiness`: platform readiness summary
- `tools`: list/call registered tools
- `resume`: resume from checkpoint

## Core HTTP Endpoints

- `POST /runs`
- `GET /runs`
- `GET /runs/{run_id}`
- `POST /runs/{run_id}/signal`
- `POST /runs/{run_id}/resume`
- `GET /runs/{run_id}/events` (SSE)
- `GET /health`
- `GET /ready`
- `GET /manifest`
- `GET /metrics`
- `GET /metrics/json`
- `GET /cost`
- `POST /knowledge/ingest`
- `POST /knowledge/ingest-structured`
- `GET /knowledge/query`
- `GET /knowledge/status`
- `POST /knowledge/lint`
- `POST /knowledge/sync`
- `POST /memory/dream`
- `POST /memory/consolidate`
- `GET /memory/status`
- `GET /skills/list`
- `GET /skills/status`
- `POST /skills/evolve`
- `GET /skills/{skill_id}/metrics`
- `GET /skills/{skill_id}/versions`
- `POST /skills/{skill_id}/optimize`
- `POST /skills/{skill_id}/promote`
- `GET /context/health`
- `POST /replay/{run_id}`
- `GET /replay/{run_id}/status`
- `GET /management/capacity`
- `GET /tools`
- `POST /tools/call`
- `GET /mcp/status`
- `POST /mcp/tools`
- `POST /mcp/tools/list`
- `POST /mcp/tools/call`
- `GET /plugins/list`
- `GET /plugins/status`
- `GET /artifacts`
- `GET /artifacts/{artifact_id}`
- `GET /runs/{run_id}/artifacts`

## Project Layout

```text
hi_agent/
  capability/        # capability registry/invocation
  config/            # TraceConfig and SystemBuilder
  context/           # context manager and budgeting
  contracts/         # core data contracts
  evolve/            # postmortem/skill extraction/regression checks
  harness/           # execution governance and permission controls
  knowledge/         # wiki/graph/retrieval
  llm/               # LLM gateways, tier routing, failover, streaming
  memory/            # multi-tier memory and compression
  middleware/        # Perception/Control/Execution/Evaluation pipeline
  route_engine/      # rule, llm, hybrid, skill-aware routing
  runtime_adapter/   # adapters to kernel runtime
  server/            # HTTP application and managers
  skill/             # skill lifecycle
  task_mgmt/         # scheduling, restart, budget, reflection
  task_view/         # compact task-view builder
  trajectory/        # trajectory/stage graph and optimization
```

## Quality Checks

```bash
python -m ruff check hi_agent tests scripts examples
python -m pytest -q --maxfail=1
```

Latest local verification during this refresh:

- `ruff`: pass
- `pytest`: `3059 passed, 5 skipped`

## More Docs

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [docs/](./docs)
