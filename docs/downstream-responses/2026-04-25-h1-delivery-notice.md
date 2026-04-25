# H1 Hardening Wave — Delivery Notice

**Date**: 2026-04-25
**Wave**: H1 (Hardening Pass 1, post-Wave 8)
**Platform team**: hi-agent (chaosxingxc-orion)
**Downstream**: Research Intelligence App team
**Branch**: claude/worktree-integration (HEAD 2bf3ded → merged to main)

---

## Governance gate

Intake decisions document: `docs/downstream-responses/2026-04-25-h1-intake-decisions.md`
That document is the authoritative ACCEPT / AMEND / DEFER / DECLINE record. This notice is
the delivery confirmation against those decisions.

---

## Summary of changes

| Track | Commits | Scope | Status |
|-------|---------|-------|--------|
| Track 0 — Governance doc | 498a4af | `docs/downstream-responses/2026-04-25-h1-intake-decisions.md`, `docs/TODO.md` | DELIVERED |
| Track 3 — /manifest extraction | 9f4f116 | `hi_agent/server/routes_manifest.py` (NEW), `app.py` | DELIVERED |
| Track 1 — Idempotency contract | 73d329f | `run_manager.py`, `routes_runs.py`, test, gate script, api-reference.md | DELIVERED |
| Track 2 — Tenant scope | edde591 | `routes_artifacts/knowledge/memory/tools_mcp/manifest/ops.py`, `app.py` | DELIVERED |
| Track 4 — Test honesty + DF-46 | 00b5357 | 9 test files, `check_t3_freshness.py`, `claude-rules.yml` | DELIVERED |
| Track 5 — Config-driven dev-ex | 2bf3ded | `builder.py`, `runtime_config_loader.py`, `profiles/loader.py`, `cli.py`, `routes_runs.py`, 2 docs | DELIVERED |

All 3 227 integration + golden tests pass (44 honestly skipped per Rule 4).
`ruff check .` exits 0. Import health check clean.

---

## Readiness delta (downstream's 7-dimension format)

| Dimension | Wave 8 | H1 | Delta | Driver |
|-----------|--------|-----|-------|--------|
| Execution Engine (TRACE) | 82% | 84% | +2% | Idempotency replay fixed; tenant isolation complete |
| Memory Infrastructure (L0–L3) | 78% | 78% | 0% | No change |
| Capability Plugin System | 70% | 75% | +5% | Config-dir override + JSON profiles + strict-mode gates |
| Knowledge Graph | 50% | 50% | 0% | No change |
| Planning & Re-planning | 40% | 40% | 0% | Deferred Wave 9 |
| Artifact / Output Contracts | 50% | 50% | 0% | No change |
| Evolution & Feedback | 35% | 35% | 0% | Deferred Wave 10 |
| Cross-Run State (Project) | 20% | 22% | +2% | project_id + profile_id strict-mode opt-in |
| Ops / Documentation | 55% | 65% | +10% | Tenant scope; /manifest; CI gate; docs |
| **Overall** | **56%** | **59%** | **+3%** | |

---

## PI-A through PI-E impact

| Pattern | H1 change |
|---------|-----------|
| PI-A | Idempotent run creation now correct (replay → 200, not 201) |
| PI-B | No change |
| PI-C | No change |
| PI-D | No change |
| PI-E | No change |

---

## Platform gap status changes

| Gap | Before H1 | After H1 |
|-----|-----------|----------|
| P-1 `project_id` contract | ADDRESSED (experimental) | **CLOSED** — strict-mode opt-in via `HI_AGENT_PROJECT_ID_REQUIRED=1` |
| P-3 `profile_id` required | ADDRESSED (experimental) | **CLOSED** — strict-mode opt-in via `HI_AGENT_PROFILE_ID_REQUIRED=1` |
| P-5 Idempotency contract | ADDRESSED (experimental) | **CLOSED** — replay returns 200 + cached snapshot |
| P-2, P-4, P-6, P-7 | Deferred | **Unchanged** — see Wave 9/10 schedule |

---

## DECLINE replies (forwarded to research team)

Three items from the 2026-04-25 foundation assessment were declined as business-layer:

1. **§4.2 ResearchProjectSpec DSL** — research-domain ontology is the research team's responsibility. Platform exposes `project_id` + free-form `metadata`. See intake-decisions doc §Decline replies.
2. **§4.3 Force capability outputs into ArtifactLedger** — research artifact policy is the research team's responsibility. Platform exposes `POST /artifacts`. See intake-decisions doc.
3. **Round 7 I-8 `on_exhausted='escalate'` default** — a policy preference, not a platform defect. Set `on_exhausted: "reflect"` in your profile JSON.

---

## Known-Defect Notice (T3 evidence)

T3 Rule 8 gate evidence is currently **DEFERRED — pending ARK API key rotation by the platform team owner**.

- Last recorded gate: `docs/delivery/2026-04-24-8c5395b-rule15-volces-v2.json` (7 commits ago)
- Hot-path changes since gate: Tracks 1–5 (all H1 commits)
- This branch is therefore tagged: **"requires gate before release"** — may merge to main for development consolidation, but MUST NOT be tagged as a production release until T3 is re-recorded at HEAD 2bf3ded.

**Required next step (platform team owner)**: rotate the ARK API key, then run:
```bash
HI_AGENT_LLM_MODE=real ARK_API_KEY=<rotated_key> \
    python scripts/rule15_volces_gate.py \
    --runs 3 \
    --record docs/delivery/2026-04-25-$(git rev-parse --short HEAD)-rule15-volces-v3.json
```
Record the output file and commit it before tagging a release.

---

## Deferred items (per intake decisions doc)

| Item | Target | Tracker |
|------|--------|---------|
| I-6/F-5/F-6 reflection-path silent-drop | H2 | `docs/TODO.md` DF-47 |
| P-2 reasoning trace | H2 | `docs/TODO.md` DF-48 |
| Rule 6 inline-fallback sweep | H2 | `docs/TODO.md` DF-49 |
| Gap 4 durable substrate (SQLiteRunQueue/Temporal) | W9 | `docs/platform-gaps.md` |
| P-4 dynamic re-planning | W9 | `docs/platform-gaps.md` |
| P-6 cost/budget governance | W9 | `docs/platform-gaps.md` |
| Gap 6 / P-7 evolution closed loop | W10 | `docs/platform-gaps.md` |

---

*Signed: chaosxingxc-orion, 2026-04-25.*
*Research team acknowledgement of DECLINE replies required before filing these as engineering backlog items.*
