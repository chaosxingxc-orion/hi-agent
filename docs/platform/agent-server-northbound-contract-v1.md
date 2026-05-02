# Agent Server Northbound Contract — v1

**Status:** RELEASED (W22; freeze JSON: docs/governance/contract_v1_freeze.json)
**Schema version:** 1.0
**Effective from:** Wave 22
**Owner tracks:** AS-CO, AS-RO
**Frozen-after-v1:** YES — see §9

---

## 1. Status

The v1 surface as of 2026-05-03 includes only the routes listed under §2 "Released routes" below. Routes previously named in §3..§8 of earlier revisions but never decorated under `agent_server/api/routes_*.py` have been moved to the §13 "v1.1 — not yet implemented" backlog (W31-N7 reconciliation). Backlog routes are NOT part of the RELEASED v1 surface and downstream MUST NOT depend on them.

The `agent_server` package exposes a versioned northbound facade over `hi_agent` internals. Downstream consumers (the Research Intelligence Application team) interact exclusively through this contract; they never import `hi_agent` directly.

This document is the single authoritative specification for:
- What primitives are available (§2)
- What this surface explicitly does NOT provide (§12)
- What is planned but NOT yet implemented (§13)

---

## 2. Released routes (v1 RELEASED surface, decorated at HEAD)

| Method | Path | Module | Description |
|--------|------|--------|-------------|
| GET | /v1/health | `agent_server.api.__init__` | Liveness probe; returns `{"status":"ok","api_version":"v1"}` |
| POST | /v1/runs | `routes_runs` | Create and enqueue a new run; returns RunResponse |
| GET | /v1/runs/{run_id} | `routes_runs` | Fetch current run state and metadata |
| POST | /v1/runs/{run_id}/signal | `routes_runs` | Send a signal (e.g. cancel) to a live run |
| POST | /v1/runs/{run_id}/cancel | `routes_runs_extended` | Request graceful cancellation |
| GET | /v1/runs/{run_id}/events | `routes_runs_extended` | SSE stream of run events |
| GET | /v1/runs/{run_id}/artifacts | `routes_artifacts` | List artifacts produced by a run |
| GET | /v1/artifacts/{artifact_id} | `routes_artifacts` | Retrieve a single artifact by id |
| POST | /v1/artifacts | `routes_artifacts` | Register a new artifact (HD-4 closure path) |
| GET | /v1/manifest | `routes_manifest` | Per-posture capability availability matrix |
| GET | /v1/mcp/tools | `routes_mcp_tools` | List MCP tools for the requesting workspace (L1 stub) |
| POST | /v1/mcp/tools/{tool_name} | `routes_mcp_tools` | Invoke an MCP tool by name (L1 stub) |
| POST | /v1/skills | `routes_skills_memory` | Register a skill for this tenant (L1 stub) |
| POST | /v1/memory/write | `routes_skills_memory` | Write a value to the memory tier (L1 stub) |
| POST | /v1/gates/{gate_id}/decide | `routes_gates` | Record an approval/rejection decision for a gate |

All paths require `X-Tenant-Id` in the request header. Mutating routes additionally accept (and under research/prod posture require) `Idempotency-Key`. Responses carry `tenant_id` plus the relevant subset of `{run_id, state, current_stage, started_at, finished_at}`.

---

## 3. Run Lifecycle Primitives

| Primitive | Method | Path | Status |
|-----------|--------|------|--------|
| start | POST | /v1/runs | RELEASED |
| status | GET | /v1/runs/{run_id} | RELEASED |
| signal | POST | /v1/runs/{run_id}/signal | RELEASED |
| cancel | POST | /v1/runs/{run_id}/cancel | RELEASED |
| stream events | GET | /v1/runs/{run_id}/events | RELEASED (SSE) |
| stream | GET | /v1/runs/{run_id}/stream | v1.1 backlog (§13) |
| resume | POST | /v1/runs/{run_id}/resume | v1.1 backlog (§13) |
| list | GET | /v1/runs | v1.1 backlog (§13) |

All released paths require `tenant_id` in request context (header). Responses carry `run_id`, `tenant_id`, `state`, `current_stage`, `started_at`, `finished_at`.

---

## 4. Skill Registry Primitives

| Primitive | Method | Path | Status |
|-----------|--------|------|--------|
| register | POST | /v1/skills | RELEASED (L1 stub) |
| get | GET | /v1/skills/{skill_id} | v1.1 backlog (§13) |
| list | GET | /v1/skills | v1.1 backlog (§13) |
| version-pin | POST | /v1/skills/{skill_id}/pin | v1.1 backlog (§13) |

---

## 5. Memory Primitives (L0–L3)

Memory is keyed by `(tenant_id, project_id, profile_id, run_id)`. Four tiers:

| Tier | Scope | Persistence |
|------|-------|-------------|
| L0 | single run, in-process | ephemeral |
| L1 | single run, compressed | run-duration |
| L2 | project-scoped index | project-duration |
| L3 | long-term knowledge graph | persistent (SQLite WAL) |

| Primitive | Method | Path | Status |
|-----------|--------|------|--------|
| write | POST | /v1/memory/write | RELEASED (L1 stub) |

Read primitives are exposed via the kernel-internal `MemoryReadKey` contract; a `GET /v1/memory/read` route is on the v1.1 backlog (§13).

---

## 6. Workspace — Content-Addressable File Tree

The workspace primitives are entirely on the v1.1 backlog (§13). No `/v1/workspace/*` route is decorated under `agent_server/api/` at HEAD.

---

## 7. Pause-on-Token / Resume-with-Input Substrate

When a run reaches a pause point, it emits a `PauseToken`. The pause emit path is wired through the run-events SSE stream (released in §3); the resume route is on the v1.1 backlog.

This substrate does NOT implement Human Gate D semantics (research-layer concern).

| Primitive | Method | Path | Status |
|-----------|--------|------|--------|
| pause (emitted) | — | — | RELEASED (event payload) |
| resume | POST | /v1/runs/{run_id}/resume | v1.1 backlog (§13) |

---

## 8. LLM Gateway Proxy

The HTTP gateway proxy is on the v1.1 backlog (§13). At v1, downstream invokes the LLM via the run lifecycle (`POST /v1/runs` with a profile that selects a model) and observes outcomes through `/v1/runs/{id}/events`. Fallback counters remain exposed on `/metrics`.

---

## 9. Multi-Tenancy / Quota / Audit / Cost-Envelope

Every request carries `tenant_id`. The platform enforces:
- **Quota**: per-tenant concurrency cap and rate limit
- **Audit**: structured event for every privileged action
- **Cost-envelope**: per-tenant LLM cost budget tracked against `/metrics`

Quota violations return HTTP 429. Cost-envelope breaches return HTTP 402.

---

## 10. Streaming Logs / Events

| Primitive | Method | Path | Status |
|-----------|--------|------|--------|
| stream events (per-run) | GET | /v1/runs/{run_id}/events | RELEASED (SSE) |
| query events (cross-run) | GET | /v1/events | v1.1 backlog (§13) |

Events carry `tenant_id`, `run_id`, `trace_id`, `event_type`, `payload`, `created_at`.

---

## 11. Frozen-After-v1 Policy (R-AS-3)

Once this document reaches `Status: RELEASED`:

- The 8 contract files under `agent_server/contracts/` are **frozen**: no field additions, removals, or type changes without a new major version.
- `check_contract_freeze.py` CI gate enforces this after the v1 release notice is published.
- Migrations to v2 require: (a) a `v2/` sub-package with the new contracts, (b) a migration guide, (c) a dual-version compatibility window of at least 2 waves.

W31-N (N.5) added `GateDecisionRequest` to `agent_server/contracts/gate.py` as an additive new class (no field changes to existing PauseToken/ResumeRequest/GateEvent). The freeze digest was re-snapshotted at the same wave.

---

## 12. Forbidden Domain Types (R-AS-2)

The following types from the research business layer are **never** present in `agent_server/contracts/**`:

`Paper`, `Phase`, `Hypothesis`, `Theorem`, `PIAgent`, `Survey`, `Analysis`, `Experiment`, `Writing`, `Author`, `Reviewer`, `Editor`, `Backtrack`, `Citation`, `Lean`, `Dataset`

`check_no_domain_types.py` CI gate enforces this.

---

## 13. v1.1 — not yet implemented (backlog, NOT part of v1 RELEASED surface)

**These routes are NOT decorated at HEAD and downstream MUST NOT depend on them.** They are tracked in the v1.1 backlog and will land in a follow-up wave with their own delivery notice. Adding any of them to the v1 surface would require re-snapshotting the contract freeze and updating §2 above.

| Method | Path | Notes |
|--------|------|-------|
| GET | /v1/runs | List runs filtered by tenant_id + optional project_id/profile_id |
| GET | /v1/runs/{run_id}/stream | Alias for /events with EventFilter; v1 uses /events directly |
| POST | /v1/runs/{run_id}/resume | Resume a paused run with input |
| GET | /v1/skills | List skills for a tenant |
| GET | /v1/skills/{skill_id} | Retrieve skill metadata |
| POST | /v1/skills/{skill_id}/pin | Pin a skill to a specific version |
| PUT | /v1/workspace/{tenant_id}/{path} | Upload object; returns ContentHash |
| GET | /v1/workspace/{tenant_id}/{path} | Retrieve by path or content hash |
| GET | /v1/workspace/{tenant_id}/ | List workspace objects |
| GET | /v1/workspace/{tenant_id}/{path}/versions | List content-addressed versions |
| POST | /v1/llm/complete | Submit an LLMRequest; returns LLMResponse |
| GET | /v1/events | Cross-run paginated event log by run_id + trace_id |

---

## 14. L-Level Matrix per Surface Group

| Surface | Current L-Level | Acceptance bar for L3 |
|---------|----------------|----------------------|
| Run lifecycle | L2 (schema stable, docs+tests) | posture-aware + observability |
| Skill registry | L1 (tested component) | schema stable + docs |
| Memory L0/L1 | L2 | persistence survival tests |
| Memory L2/L3 | L1 | L1/L2 store implementation (W25) |
| Workspace | L0 (backlog only at v1) | content-addressed CAS store (W25/v1.1) |
| Pause/Resume | L1 (pause emits at v1; resume is backlog) | full v1.1 release |
| LLM gateway proxy | L0 (backlog at v1) | — |
| Multi-tenancy | L1 | quota + audit + cost-envelope (W25) |
| Streaming events | L2 | — |

---

## What This Surface Does NOT Provide

The following are explicitly outside the agent_server northbound contract:

- Research-domain orchestration (Phase pipeline, Paper Archive, Lean Library, Dataset Registry)
- Application user identity management
- Citation validation or anti-hallucination
- Human Gate D semantics (research-layer concern)
- Multi-region deployment coordination
- Auto-calibration of TierRouter
- Neo4j as a bundled backend (KG Protocol v1 in W25 allows external Neo4j without forking core)

---

## Cross-References

- Architecture reference: `docs/architecture-reference.md`
- Platform capability matrix: `docs/platform-capability-matrix.md`
- Posture reference: `docs/posture-reference.md`
- Contract dataclasses: `agent_server/contracts/` (stdlib-only, no pydantic)
- OpenAPI spec: `docs/platform/agent-server-openapi-v1.yaml` (generated in W23)
