# hi-agent

TRACE agent platform — capability layer for autonomous agent execution. Provides the runtime
kernel, versioned northbound HTTP facade, and execution substrate used by the research team's
intelligence applications.

**TRACE** = Task -> Route -> Act -> Capture -> Evolve

---

## Overview

hi-agent is an enterprise agent platform built around three cooperating packages in this
repository:

| Package | Role |
|---|---|
| `agent_server/` | Versioned northbound HTTP facade (v1 contract frozen); stable API for downstream teams |
| `hi_agent/` | Agent brain: LLM gateway, runner, memory, knowledge, skills, config, observability |
| `agent_kernel/` | Execution substrate: run lifecycle, event log, idempotency, durable persistence |

The platform enforces a hard boundary between platform-layer logic (this repo) and
business-layer logic (research team). All downstream integration goes through `agent_server/`
routes only; direct imports of `hi_agent.*` from downstream code are not supported.

---

## Quickstart

**Requirements:** Python 3.12+

### Install

```bash
pip install -e ".[llm,dev]"
```

### Start the northbound API server

```bash
agent-server serve --host 0.0.0.0 --port 8000
```

To use a real LLM provider and fail-closed research posture:

```bash
export HI_AGENT_POSTURE=research
export HI_AGENT_LLM_MODE=real
export OPENAI_API_KEY=<your-key>
agent-server serve
```

### Submit a run

```bash
agent-server run --goal "summarise quarterly results" --profile default
```

Or via HTTP:

```bash
curl -s -X POST http://localhost:8000/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"goal": "summarise quarterly results", "profile_id": "default", "project_id": "proj-1"}'
```

### Cancel a run and stream events

```bash
agent-server cancel <run_id>
agent-server tail-events <run_id>
```

### Run the test suite

```bash
pytest -m "not live_api and not network and not requires_secret"
```

Current baseline: 9,091 passed (Wave 27, default-offline profile, 2026-05-01).

---

## Project Status

Current wave: **28**. Verified readiness: **94.55**. 7x24 operational readiness: **65.0**
(24h soak deferred to W28 by explicit decision).

| Capability | Level | Notes |
|---|---|---|
| Run execution (TRACE S1-S5) | L3 | Long-lived process, real LLM, durable queue |
| TierRouter | L3 | Active calibration, signal-weight routing (P-6 closed W27) |
| ExtensionRegistry | L4 | Full lifecycle, rollback, third-party registration (C12 closed W27) |
| PostmortemEngine | L2 | Wired into RunManager; `on_project_completed` hook |
| StageDirective wiring | L3 | `skip_to` + `insert_stage` + `replan` wired (P-4 closed W27) |
| Multi-agent team | L2 | `TeamRunSpec`; registry; not production-default |
| Knowledge graph | L2 | SQLite backend; four-layer retrieval |
| Evolution closed-loop | L2 | `ExperimentStore` rollback; recurrence-ledger observable |
| MCP tools | L2 | `StdioMCPTransport`; plugin-registered |
| Observability spine | L2 | `RunEventEmitter` (12 event types); real provenance deferred to W28 |

Maturity levels: L0 demo | L1 tested component | L2 public contract | L3 production default | L4 ecosystem ready

---

## Key Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `HI_AGENT_POSTURE` | `dev` | Execution posture: `dev` permissive, `research`/`prod` fail-closed |
| `HI_AGENT_LLM_MODE` | `heuristic` | `real` routes to actual LLM provider |
| `HI_AGENT_ENV` | `dev` | `prod` enables fail-fast 503 on missing credentials |
| `HI_AGENT_KERNEL_BASE_URL` | — | Routes kernel RPC to a detached `agent_kernel` service |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | — | LLM provider credentials |

Full environment variable reference: `docs/deployment-env-matrix.md`

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full arc42-aligned architecture document,
including system context diagram, building block view, runtime sequence, and deployment view.

The existing codebase reference document is at `docs/architecture-reference.md`.

---

## Contributing

Owner tracks govern review responsibilities:

| Track | Scope |
|---|---|
| CO | Contracts, schemas, posture |
| RO | Execution, state machines, persistence |
| DX | CLI, config, developer tooling |
| TE | Artifacts, observability, evolution |
| GOV | CI, delivery governance, CLAUDE.md |
| AS-CO | `agent_server` contracts (v1 frozen) |
| AS-RO | `agent_server` routes, facades, CLI |

Every PR must declare its owner track in the commit body. Hot-path changes require T3 gate
evidence at `docs/delivery/`. See [CLAUDE.md](CLAUDE.md) for the full seventeen engineering
rules enforced by CI.

---

## License

Proprietary — internal platform use only. Not for external distribution.
