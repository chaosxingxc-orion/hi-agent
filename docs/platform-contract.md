# hi-agent Platform Contract

**Version**: 1.0 | **Date**: 2026-04-12 | **Status**: Production

---

## Overview

hi-agent is an enterprise-grade intelligent agent platform built on the TRACE framework (Task→Route→Act→Capture→Evolve). This document defines the platform contract between hi-agent and downstream integrators (research agents, application teams, external services).

---

## 1. Readiness Contract

### 1.1 Readiness Endpoint

```
GET /ready
```

**200 OK** — platform is ready to accept task submissions.
**503 Service Unavailable** — platform is not ready (see response body for details).

```json
{
  "ready": true,
  "models": [{"name": "heuristic-fallback", "tier": "light", "status": "ok"}],
  "skills": [{"name": "analyze_goal", "source": "builtin", "status": "certified"}],
  "mcp_servers": [],
  "plugins": [],
  "capabilities": ["analyze_goal", "search_evidence", "build_draft", "synthesize", "evaluate_acceptance"],
  "execution_mode": "local",
  "health": "ok"
}
```

### 1.2 CLI Readiness Check

```bash
python -m hi_agent readiness --local          # local mode
python -m hi_agent readiness --json           # machine-readable JSON
python -m hi_agent readiness                  # against running server
```

### 1.3 Readiness Levels

| Level | Condition | Behavior |
|-------|-----------|----------|
| **full** | LLM gateway + kernel reachable | Real execution, real model calls |
| **degraded** | No API key, local kernel | Heuristic-only execution, `_degraded=True` in results |
| **unavailable** | Kernel unreachable | 503, no task submissions accepted |

Integrators MUST check `/ready` before submitting tasks. A `200` with `"health": "ok"` guarantees the submission endpoint is accepting requests.

---

## 2. Task Submission Contract

### 2.1 Submit a Task

```
POST /runs
Content-Type: application/json

{
  "goal": "Summarize the TRACE framework in one paragraph",
  "config": {}     // optional overrides
}
```

**Response**: `{"run_id": "run-abc123", "state": "pending"}`

### 2.2 Poll for Completion

```
GET /runs/{run_id}
```

**Response**:
```json
{
  "run_id": "run-abc123",
  "state": "done",
  "result": "...",
  "stages_completed": 4,
  "tokens_used": 1240
}
```

### 2.3 Run Lifecycle States

```
pending → running → done
              ↘ failed → (retry → running | abort)
              ↘ escalated (human gate required)
```

### 2.4 Idempotency

Each `POST /runs` generates a unique `run_id`. Submitting the same goal twice creates two independent runs. The platform does **not** deduplicate by goal text.

---

## 3. Skill Contract

### 3.1 Skill Discovery

Skills are discovered from three directories in order:

1. **builtin**: `hi_agent/skills/builtin/` — shipped with platform, always available
2. **user_global**: `~/.hi_agent/skills/` — user-installed skills
3. **project**: `config.skill_storage_dir` — project-specific skills

### 3.2 Builtin Skills (Always Available)

| Skill | Description | Tier |
|-------|-------------|------|
| `analyze_goal` | Decompose goal into structured sub-tasks | light |
| `search_evidence` | Evidence gathering and source validation | medium |
| `synthesize` | Synthesize findings into coherent output | medium |

### 3.3 Skill API

```
GET  /skills/list              # list all discovered skills with source
POST /skills/evolve            # trigger skill evolution cycle
GET  /skills/{name}            # skill detail + eligibility criteria
```

### 3.4 SKILL.md Format

Skills are defined as Markdown files with YAML frontmatter:

```markdown
---
name: my_skill
version: 1.0.0
description: What this skill does
tier: medium
eligibility:
  - condition: goal contains "keyword"
---

## Instructions
...
```

---

## 4. MCP Contract

### 4.1 MCP Registry

hi-agent maintains its own MCP registry at the platform layer. MCP servers are registered, health-checked, and bound to capability invocations.

```
GET /mcp/status     # list registered MCP servers + health
GET /mcp/tools      # list all tools exposed by active MCP servers
```

### 4.2 MCP Registration (Programmatic)

```python
from hi_agent.mcp import MCPRegistry

registry = MCPRegistry()
registry.register_server("my-server", endpoint="http://localhost:9000", transport="http")
```

### 4.3 MCP Health

MCP servers are health-checked on registration and periodically thereafter. Unhealthy servers are automatically deregistered and their tools become unavailable.

---

## 5. Plugin Contract

### 5.1 Plugin Discovery

Plugins are discovered from `~/.hi_agent/plugins/` and `config.plugin_dir`. Each plugin directory must contain a `plugin.json` manifest.

### 5.2 Plugin Manifest Format

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "What this plugin does",
  "capabilities": ["web_search", "web_extract"],
  "hooks": ["on_run_start", "on_run_complete"],
  "entry_point": "my_plugin.loader:load"
}
```

### 5.3 Plugin API

```
GET /plugins/list      # list discovered plugins
GET /plugins/status    # plugin health + activation status
```

---

## 6. Capability Bundle Contract

### 6.1 Available Bundles

| Bundle | Capabilities | Use Case |
|--------|-------------|----------|
| `research` | web_search, web_extract, paper_parse, citation_capture, summarize_sources, literature_review | Research agent workflows |

### 6.2 Bundle Registration

```python
from hi_agent.capability.bundles import ResearchBundle

registry = CapabilityRegistry()
registry.register_bundle(ResearchBundle())
```

---

## 7. Failure Ownership

See `docs/failure-attribution.md` for the complete failure attribution matrix.

**Quick reference**:

| Error Class | Owner |
|-------------|-------|
| Platform crashes, 5xx on `/ready` | hi-agent platform team |
| LLM API errors, model timeouts | LLM provider / integrator (API key) |
| Skill not found, invalid SKILL.md | Integrator (skill authoring) |
| Task goal unparseable | Integrator (input validation) |
| MCP server unreachable | Integrator (MCP server ops) |

---

## 8. SLOs (Local Mode)

| Metric | Target |
|--------|--------|
| `/ready` response time | < 500ms |
| Task submission (POST /runs) | < 200ms |
| Stage execution (heuristic) | < 2s per stage |
| Full run (4 stages, heuristic) | < 10s |

Production mode SLOs depend on LLM provider latency and are defined separately per deployment.

---

## 9. Versioning

Platform version is available at:

```
GET /manifest
```

```json
{
  "platform": "hi-agent",
  "version": "1.0.0",
  "execution_mode": "local",
  "capabilities": [...],
  "skills": [...]
}
```

Breaking changes to this contract will increment the major version and be communicated with at least 30 days notice.

---

### Routes added 2026-04-22

**POST /runs/{id}/cancel**
- 200: run was live and cancellation was initiated
- 404: run_id unknown

**GET /ready**
Now includes additional readiness fields:
- `llm_mode`: "real" or "structural" — indicates whether a real LLM is configured
- `llm_provider`: provider name (e.g. "volces", "anthropic")
