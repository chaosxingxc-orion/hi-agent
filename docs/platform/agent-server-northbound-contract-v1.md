# Agent Server Northbound Contract — v1

**Status:** RELEASED (W22; freeze JSON: docs/governance/contract_v1_freeze.json)
**Schema version:** 1.0
**Effective from:** Wave 22
**Owner tracks:** AS-CO, AS-RO
**Frozen-after-v1:** YES — see §9

---

## Overview

The `agent_server` package exposes a versioned northbound facade over `hi_agent` internals. Downstream consumers (the Research Intelligence Application team) interact exclusively through this contract; they never import `hi_agent` directly.

This document is the single authoritative specification for:
- What primitives are available
- What each primitive guarantees
- What this surface explicitly does NOT provide

---

## 1. Run Lifecycle Primitives

Downstream can start, monitor, stream, cancel, resume, and list runs.

| Primitive | Method | Path | Description |
|-----------|--------|------|-------------|
| start | POST | /v1/runs | Create and enqueue a new run; returns RunResponse |
| status | GET | /v1/runs/{run_id} | Fetch current run state and metadata |
| stream | GET | /v1/runs/{run_id}/stream | SSE stream of run events |
| cancel | POST | /v1/runs/{run_id}/cancel | Request graceful cancellation |
| resume | POST | /v1/runs/{run_id}/resume | Resume a paused run with input |
| list-by-scope | GET | /v1/runs | List runs filtered by tenant_id + optional project_id/profile_id |

All paths require `tenant_id` in request context (header or body). Responses carry `run_id`, `tenant_id`, `state`, `current_stage`, `started_at`, `finished_at`.

---

## 2. Skill Registry Primitives

Downstream can register, retrieve, list, version-pin, and A/B skills.

| Primitive | Method | Path | Description |
|-----------|--------|------|-------------|
| register | POST | /v1/skills | Register a skill with version and handler |
| get | GET | /v1/skills/{skill_id} | Retrieve skill metadata |
| list | GET | /v1/skills | List skills for a tenant |
| version-pin | POST | /v1/skills/{skill_id}/pin | Pin a skill to a specific version |

---

## 3. Memory Primitives (L0–L3)

Memory is keyed by `(tenant_id, project_id, profile_id, run_id)`. Four tiers:

| Tier | Scope | Persistence |
|------|-------|-------------|
| L0 | single run, in-process | ephemeral |
| L1 | single run, compressed | run-duration |
| L2 | project-scoped index | project-duration |
| L3 | long-term knowledge graph | persistent (SQLite WAL) |

Primitives: read by `MemoryReadKey`; write by `MemoryWriteRequest`.

---

## 4. Workspace — Content-Addressable File Tree

Each run operates in a tenant-scoped, content-addressed workspace.

| Primitive | Method | Path | Description |
|-----------|--------|------|-------------|
| put | PUT | /v1/workspace/{tenant_id}/{path} | Upload object; returns ContentHash |
| get | GET | /v1/workspace/{tenant_id}/{path} | Retrieve by path or content hash |
| list | GET | /v1/workspace/{tenant_id}/ | List workspace objects |
| version | GET | /v1/workspace/{tenant_id}/{path}/versions | List content-addressed versions |

Objects are identified by SHA-256 content hash (`BlobRef`).

---

## 5. Pause-on-Token / Resume-with-Input Substrate

When a run reaches a pause point, it emits a `PauseToken`. Downstream can resume by posting a `ResumeRequest` with that token.

This substrate does NOT implement Human Gate D semantics (research-layer concern). It provides only the raw pause/resume signaling mechanism.

| Primitive | Method | Path | Description |
|-----------|--------|------|-------------|
| pause (emitted) | — | — | PauseToken emitted in run event stream |
| resume | POST | /v1/runs/{run_id}/resume | ResumeRequest with PauseToken + input |

---

## 6. LLM Gateway Proxy

Routes LLM requests through hi_agent's posture-aware gateway. Model selection is governed by the active posture; downstream does not choose the model directly.

| Primitive | Method | Path | Description |
|-----------|--------|------|-------------|
| complete | POST | /v1/llm/complete | Submit an LLMRequest; returns LLMResponse |

Fallback counters are exposed on `/metrics`. Any run with `llm_fallback_count > 0` is not considered successful for delivery purposes.

---

## 7. Multi-Tenancy / Quota / Audit / Cost-Envelope

Every request carries `tenant_id`. The platform enforces:
- **Quota**: per-tenant concurrency cap and rate limit
- **Audit**: structured event for every privileged action
- **Cost-envelope**: per-tenant LLM cost budget tracked against `/metrics`

Quota violations return HTTP 429. Cost-envelope breaches return HTTP 402.

---

## 8. Streaming Logs / Events

All run events are queryable by `(run_id, trace_id)` via the event stream endpoint.

| Primitive | Method | Path | Description |
|-----------|--------|------|-------------|
| stream events | GET | /v1/runs/{run_id}/stream | SSE stream filtered by EventFilter |
| query events | GET | /v1/events | Paginated event log by run_id + trace_id |

Events carry `tenant_id`, `run_id`, `trace_id`, `event_type`, `payload`, `created_at`.

---

## 9. Frozen-After-v1 Policy (R-AS-3)

Once this document reaches `Status: RELEASED`:

- The 8 contract files under `agent_server/contracts/` are **frozen**: no field additions, removals, or type changes without a new major version.
- `check_contract_freeze.py` CI gate enforces this after the v1 release notice is published.
- Migrations to v2 require: (a) a `v2/` sub-package with the new contracts, (b) a migration guide, (c) a dual-version compatibility window of at least 2 waves.

---

## 10. Forbidden Domain Types (R-AS-2)

The following types from the research business layer are **never** present in `agent_server/contracts/**`:

`Paper`, `Phase`, `Hypothesis`, `Theorem`, `PIAgent`, `Survey`, `Analysis`, `Experiment`, `Writing`, `Author`, `Reviewer`, `Editor`, `Backtrack`, `Citation`, `Lean`, `Dataset`

`check_no_domain_types.py` CI gate enforces this.

---

## 11. L-Level Matrix per Surface Group

| Surface | Current L-Level | Acceptance bar for L3 |
|---------|----------------|----------------------|
| Run lifecycle | L2 (schema stable, docs+tests) | posture-aware + observability |
| Skill registry | L1 (tested component) | schema stable + docs |
| Memory L0/L1 | L2 | persistence survival tests |
| Memory L2/L3 | L1 | L1/L2 store implementation (W25) |
| Workspace | L1 | content-addressed CAS store (W25) |
| Pause/Resume | L2 | — |
| LLM gateway proxy | L2 | — |
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
