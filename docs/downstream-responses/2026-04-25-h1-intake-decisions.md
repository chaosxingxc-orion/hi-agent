# H1 Hardening Wave — Intake Decisions (G1/G2/G3 Governance)

**Date**: 2026-04-25
**Wave**: H1 (Hardening Pass 1, post-Wave 7)
**Platform team**: hi-agent (chaosxingxc-orion)
**Downstream**: Research Intelligence App team
**Branch**: claude/worktree-integration (HEAD a4c4da8)

---

## Purpose

This document is the **normative intake decision record** for the H1 Hardening Wave. No code change enters execution until it has passed the Three-Gate Demand Intake (CLAUDE.md §Three-Gate Demand Intake):

- **G1 Positioning** — is the request a capability-layer concern (runtime, memory, LLM routing, observability, HTTP contract)? Business-layer requests (research-domain modeling, domain UX, project taxonomies) are **declined** and redirected to the research team.
- **G2 Abstraction** — can it be satisfied by composing existing capabilities without new code? If yes, we ship a composition recipe, not new code.
- **G3 Verification** — when new code is unavoidable, a Rule 4 three-layer test plan + Rule 8 gate plan must be in place before delivery authorization.

Platform positioning (memory `project_positioning.md`): hi-agent is the **capability layer**. It owns runtime, memory, LLM routing, observability, and the HTTP contract surface. Coupling to business logic is forbidden. The research team owns research domain semantics, research artifact policy, and research UX.

If this document and the plan file `D:\.claude\plans\clever-soaring-naur.md` disagree, **this document wins**.

---

## Architectural impact summary

Before the item matrix, the high-level positioning check:

| Question | Answer |
|----------|--------|
| Does H1 require a new core abstraction? | No. Every ACCEPT/AMEND composes with current contracts. |
| Does H1 couple us to research-domain semantics? | No. Two requests that would do so are DECLINED (§4.2, §4.3). |
| Does H1 break any existing downstream API contract? | No. `project_id`/`profile_id` strictness is opt-in via env flags; all other changes are additive or correctness fixes. |
| Does H1 expand the platform into business logic? | No. DECLINE replies redirect the two business-layer asks back to the research team. |
| Does H1 preserve Rule 8 T3 evidence? | Track 6 re-records T3 at HEAD after all code changes merge; this closes the current 7-commit gap. |

---

## Intake matrix

Legend:
- **ACCEPT** — ship in H1 wave; Track N implements it.
- **AMEND** — ship in H1 with scope limited to the platform layer; scope notes inline.
- **DEFER** — legitimate capability-layer ask, explicitly not in H1 scope; target wave named.
- **DECLINE** — business-layer; redirect reply provided in §Decline replies below.
- **CLOSED** — already fixed at HEAD (verified); no work needed; cite in Track 4 regression tests.

### Self-identified defects (platform audit)

| ID | Description | Verdict | Track / Target |
|----|-------------|---------|----------------|
| SELF-1 | Idempotency replay returns `201 + new body` instead of `200 + cached snapshot`; `mark_complete` is never called | **ACCEPT** | Track 1 |
| SELF-2 | `routes_artifacts.py`, `routes_knowledge.py`, `routes_memory.py` have no `require_tenant_context`; cross-tenant leakage risk | **ACCEPT** | Track 2 |
| SELF-3 | `/manifest` accessible without auth; leaks model list, plugin paths, deployment topology | **ACCEPT** | Track 2 |
| SELF-4 | `/manifest` returns hardcoded version `"0.1.0"`, hardcoded endpoint list, capability names only (no schemas) | **ACCEPT** | Track 3 |
| SELF-5 | `config/tools.json` and `config/mcp_servers.json` paths hardcoded to repo root in `builder.py:275,526`; wheel-installed users cannot configure | **ACCEPT** | Track 5 |
| SELF-6 | `hi_agent_config.json` referenced in `api-reference.md:109` and `extension-guide.md:90` but no loader exists | **ACCEPT** | Track 5 |
| SELF-7 | `ProfileRegistry.register` is Python-only; no JSON path for downstream-defined profiles | **ACCEPT** | Track 5 |
| SELF-8 | `docs/extension-guide.md:33` documents `GET /capabilities` (endpoint does not exist; real is `GET /tools`) | **ACCEPT** | Track 5 |
| SELF-9 | Five integration tests use `result.status in ("completed", "failed", ...)` — accepts failure as success | **ACCEPT** | Track 4 |
| SELF-10 | Four integration tests `MagicMock` the SUT (executor, kernel, route_engine) — violate Rule 4 | **ACCEPT** | Track 4 |
| SELF-11 | DF-46: CI mechanical enforcement of Rule 8 T3 invariance never implemented | **ACCEPT** | Track 4 |
| SELF-12 | T3 evidence stamped at `8c5395b`; HEAD `a4c4da8` is 7 hot-path commits ahead | **ACCEPT** | Track 6 |

### Round 4–8 optimization requests

| ID | Description | Verdict | Track / Target |
|----|-------------|---------|----------------|
| K-1 | Logger NameError on deadline path (`runner.py`) | **CLOSED** | Verified: `runner.py` Grep `[^_]logger.` → 0 matches |
| K-2 | `execute_async()` never sets `executor._run_id` | **CLOSED** | Verified: `runner.py:2294` (`executor._run_id = run_id  # K-2`) |
| K-3 | `start_run()` signature mismatch | **CLOSED** | Verified: `runner.py:2289` positional `executor.contract.task_id` |
| K-15 | `_run_start_monotonic` not initialized | **CLOSED** | Verified: `runner.py:2295` |
| K-6 | `gate_resolved` check missing | **CLOSED** | Verified: `runner.py:1894-1908` |
| K-11 | J5 sub-run journey test uses `MagicMock` on internal boundary (Rule 4 / P3) | **AMEND** | Track 4 — cite K-11 in mock-on-SUT cleanup commit |
| G-4 | Outer `except Exception` swallows `GatePendingError` from retry path | **CLOSED** | Verified: re-raise filter in `stage_orchestrator.py:273`, `gate_coordinator.py:207`, `recovery_coordinator.py:476`, `action_dispatcher.py:83` |
| H-3 | `_run_terminated` backtrack flag is dead code | **CLOSED** | Verified: extracted to `recovery_coordinator.py:160` |
| H-5 | `execute()` / `execute_graph()` re-run completed stages on resume | **CLOSED** | Verified: `stage_orchestrator.run_resume():161-175` filters `completed_stages` |
| I-7 | `build_memory_lifecycle_manager()` creates non-profile-scoped stores | **CLOSED** | Verified: `builder.py:727-745` (`profile_id` keyword-only required); `:1167` passes scoped stores |
| I-6 | `ShortTermMemoryStore.save()` silently drops reflection session IDs | **DEFER (H2)** | G1 platform; isolated to reflection path (pairs with P3-2 TierRouter.calibrate, also deferred). Track in `docs/TODO.md` DF-47. |
| I-8 | Default `on_exhausted='escalate'` policy prevents `reflect_and_infer()` | **DECLINE** | G1: this is a research-team **policy preference**, not a platform defect. Platform already exposes `on_exhausted` as a configurable field. Reply: set `on_exhausted='reflect'` in your profile (see §Decline replies). |
| F-5 | `reflect_and_infer()` skipped in async context | **DEFER (H2)** | G1 platform; pairs with I-6 reflection-path family. |
| F-6 | `reflect_and_infer(attempts=[])` hardcoded empty | **DEFER (H2)** | Residual of H-1 (closed); H2 with I-6/F-5. |
| D-2 / P3-2 | `TierRouter.calibrate()` deferred | **DEFER (W10)** | Explicitly locked to Wave 10 (evolution closed loop, Gap 6) per `2026-04-25-foundation-assessment-response.md`. |

### Foundation assessment 2026-04-25

| Section | Description | Verdict | Track / Target |
|---------|-------------|---------|----------------|
| §4.1 | `project_id` not first-class in TaskContract + HTTP | **AMEND (H1)** | Track 5: (a) document `project_id` as top-level body field in `api-reference.md`; (b) add opt-in strict mode env flag `HI_AGENT_PROJECT_ID_REQUIRED=1` that upgrades `X-Project-Warning: unscoped` → `400 missing_project_id`. Back-compat default: off. Closes P-1. |
| §4.2 | ResearchProjectSpec DSL (literature-review vs experiment vs survey types) | **DECLINE** | G1 BUSINESS — domain ontology. Platform exposes `project_id` + free-form `metadata`; research team builds ResearchProjectSpec in their app layer. (See §Decline replies.) |
| §4.3 | Force all capability outputs into ArtifactLedger | **DECLINE** | G1 BUSINESS — research-team artifact policy, not platform infrastructure. Platform exposes `POST /artifacts`; whether every output becomes a research artifact is the research team's policy. (See §Decline replies.) |
| §4.4 | Long-running task durability (SQLiteRunQueue default-on, Temporal main path) | **DEFER (W9)** | G1 platform. Already accepted for W9 per `2026-04-25-foundation-assessment-response.md` Gap 4. |
| §4.5 | Platform contract for `hi_agent_global/` profile namespace | **AMEND (H1)** | Track 3: ensure `/manifest.profiles[]` includes the `hi_agent_global` descriptor with its capability list. No behavior change, only contract-surface exposure. |
| §4.6 | Evolution closed loop (postmortem + skill A/B + feedback→routing) | **DEFER (W10)** | G1 platform. Already accepted for W10 per `2026-04-25-foundation-assessment-response.md` Gap 6. |

### Strategic roadmap 2026-04-16

| Gap | Description | Verdict | Track / Target |
|-----|-------------|---------|----------------|
| P-1 | `project_id` contract | **AMEND (H1, Track 5)** | Same as §4.1 above. Closes P-1. |
| P-3 | `profile_id` required | **AMEND (H1, Track 5)** | Env flag `HI_AGENT_PROFILE_ID_REQUIRED=1` flips `record_fallback("missing_profile_id")` at `routes_runs.py:140-150` to `400`. Default off (back-compat), opt-in strict. Closes P-3. |
| P-5 | Idempotency contract | **ACCEPT (H1, Track 1)** | Track 1 fixes replay path and wires `mark_complete`. Closes P-5. |
| P-2 | Reasoning trace expansion | **DEFER (H2)** | G1 platform. Larger capability-layer expansion; bundling with H1 violates CLAUDE.md Rule 2 anti-bundle clause. |
| P-4 | Dynamic re-planning / `StageDirective` | **DEFER (W9)** | G1 platform. Strategic; already deferred per foundation response. |
| P-6 | Cost/budget governance | **DEFER (W9)** | G1 platform. Strategic. |
| P-7 | Feedback integration (feedback → routing) | **DEFER (W10)** | G1 platform. Pairs with §4.6 evolution loop. |

---

## Decline replies

The following items are declined as business-layer concerns. The text below is the platform team's written reply for forwarding to the downstream team.

### Reply to §4.2 — ResearchProjectSpec DSL

> The platform does not build research-domain ontologies. `ResearchProjectSpec` (literature review, experiment, survey) is your team's domain model, not a platform contract. Our interface: `project_id` (string identifier, already top-level) plus `metadata` (free-form dict, no schema constraint). You build `ResearchProjectSpec` in your application layer and serialize what matters to hi-agent's `project_id` + `metadata`. We will not couple the hi-agent HTTP contract or runner to research-type semantics — that would violate our capability-layer positioning and require changes every time your domain model evolves.

### Reply to §4.3 — Force capability outputs into ArtifactLedger

> Whether every capability output constitutes a research artifact is your policy, not ours. The platform exposes `POST /artifacts` with provenance fields (`producer_run_id`, `producer_capability`, `content_hash`, `evidence_count`). The policy of "a run must produce ≥1 artifact to count as a research contribution" belongs in your application layer. You can enforce it from your middleware by inspecting `GET /runs/{id}/artifacts` after completion. We will not gate run completion on artifact creation — that would embed research workflow policy in the platform runtime.

### Reply to Round 7 I-8 — `on_exhausted='escalate'` default

> The `on_exhausted` field is a configurable parameter in your profile spec. Set `on_exhausted: "reflect"` in your profile JSON to route exhausted runs through `reflect_and_infer`. The current default `"escalate"` is not a defect; it is the platform's safe default for workflows that have not expressed a preference. Change it in your configuration, not in the platform code.

---

## Deferred items tracker

Items deferred to future waves. The platform team will update these entries when the wave lands.

| ID | Description | Target | Tracker |
|----|-------------|--------|---------|
| I-6 / F-5 / F-6 | Reflection-path silent-drop family | H2 | `docs/TODO.md` DF-47 (to be created) |
| P-2 | Reasoning trace expansion | H2 | `docs/TODO.md` DF-48 (to be created) |
| Rule 6 inline-fallback sweep (~20 sites in runner.py, evolve/engine.py) | H2 | `docs/TODO.md` DF-49 (to be created) |
| §4.4 / Gap 4 | Long-running task durability (SQLiteRunQueue, Temporal) | W9 | `docs/platform-gaps.md` P-gap-durable |
| P-4 | Dynamic re-planning / StageDirective | W9 | `docs/platform-gaps.md` P-4 |
| P-6 | Cost/budget governance | W9 | `docs/platform-gaps.md` P-6 |
| §4.6 / P-7 / D-2 | Evolution closed loop + feedback routing + TierRouter.calibrate | W10 | `docs/platform-gaps.md` P-7 |

---

## Track cross-reference

| Track | Scope | Items addressed |
|-------|-------|-----------------|
| Track 0 (this doc) | Governance gate | All intake decisions |
| Track 1 | Idempotency contract correctness | SELF-1, P-5 |
| Track 2 | Tenant scope universal | SELF-2, SELF-3 |
| Track 3 | Manifest as discovery contract | SELF-4, §4.5 (hi_agent_global) |
| Track 4 | Test honesty + CI DF-46 | SELF-9, SELF-10, SELF-11, K-11 |
| Track 5 | Config-driven dev-ex | SELF-5..8, §4.1/P-1, P-3 |
| Track 6 | T3 re-record + push to main | SELF-12 |

---

*Document owner: chaosxingxc-orion. Effective 2026-04-25. Supersedes any per-item inline decisions in prior wave delivery notices. The research team should acknowledge the DECLINE replies in writing before escalating them to the engineering backlog.*
