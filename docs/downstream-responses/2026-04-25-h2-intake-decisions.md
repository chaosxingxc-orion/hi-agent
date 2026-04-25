# H2 Hardening Wave — Intake Decisions (G1/G2/G3 Governance)

**Date**: 2026-04-25
**Wave**: H2 (Hardening Pass 2, post-H1)
**Platform team**: hi-agent (chaosxingxc-orion)
**Downstream**: Research Intelligence App team
**Branch**: claude/worktree-integration (HEAD 5f57ff3)

---

## Purpose

This document is the **normative intake decision record** for the H2 Hardening Wave. No code change enters execution until it has passed the Three-Gate Demand Intake (CLAUDE.md §Three-Gate Demand Intake):

- **G1 Positioning** — is the request a capability-layer concern (runtime, memory, LLM routing, observability, HTTP contract)? Business-layer requests are **declined** and redirected to the research team.
- **G2 Abstraction** — can it be satisfied by composing existing capabilities without new code? If yes, we ship a composition recipe, not new code.
- **G3 Verification** — when new code is unavoidable, a Rule 4 three-layer test plan + Rule 8 gate plan must be in place before delivery authorization.

Every H2 item is **self-found by audit** (three parallel `Explore` agents run post-H1), not downstream-pushed. Governance still applies: each must be a platform-layer concern, must compose with existing capabilities, and must have a verification plan.

If this document and the plan file `D:\.claude\plans\clever-soaring-naur.md` disagree, **this document wins**.

---

## H1 gap disclosure (Rule 9 honesty)

H1's delivery notice (`2026-04-25-h1-delivery-notice.md`) claimed "Tenant scope universal" (T2). The H2 post-mortem audit discovered that **`hi_agent/server/routes_profiles.py` was missed entirely** by H1-T2. Two public handlers (`handle_global_l3_summary` at line 14, `handle_global_skills` at line 29) still respond without `require_tenant_context()`. This is a security boundary violation under Rule 9. H2-T2 closes this gap and the H2 delivery notice will explicitly disclose it.

---

## Architectural impact summary

| Question | Answer |
|----------|--------|
| Does H2 require a new core abstraction? | No. Every ACCEPT composes with current contracts (`require_tenant_context`, `raise ValueError`, existing test patterns). |
| Does H2 couple us to research-domain semantics? | No. All accepts are infrastructure-layer (security boundary, test correctness, Rule 6 hardening, regression coverage). |
| Does H2 break any existing downstream API contract? | No. `/profiles/*` auth is additive enforcement (no current contract guarantees anonymous access). |
| Does H2 expand the platform into business logic? | No. |
| Does H2 preserve Rule 8 T3 evidence? | Track 7 re-records T3 at HEAD after all code changes merge; evidence committed under version control. |

---

## Intake matrix

Legend:
- **ACCEPT** — ship in H2 wave; Track N implements it.
- **DEFER** — legitimate capability-layer ask, explicitly not in H2 scope; target wave named.
- **DECLINE** — business-layer; not applicable in H2 (H1's three declines stand).

### Self-identified defects (H2 audit — post-H1 health check)

| ID | Description | Verdict | Track / Target |
|----|-------------|---------|----------------|
| **C1** | `tests/agent_kernel/skills/test_skill_runtime_factory.py:10` imports `agent_kernel.skills.runtime_factory` which does not exist → pytest collection `ModuleNotFoundError`; CI sees truncated suite headline `11616 collected, 1 error` | **ACCEPT** | Track 1 |
| **C2** | `routes_profiles.py:14 handle_global_l3_summary`, `:29 handle_global_skills` — public handlers with no `require_tenant_context()`; defeats H1-T2 universal-tenant-scope claim | **ACCEPT** | Track 2 |
| **C3** | `routes_profiles.py:57 except Exception: return None` — silently swallows `ProfileDirectoryManager` construction errors; handlers return `503 profile_manager_not_available` with no `WARNING+` log (Rule 7 violation) | **ACCEPT** | Track 2 (bundled with C2) |

### H2 deferred items now executable (DF-47, DF-48, DF-49)

| ID | Description | Verdict | Track / Target |
|----|-------------|---------|----------------|
| **DF-47** | Reflection-path silent-drop family (I-6/F-5/F-6): code is **already correct** at HEAD in `recovery_coordinator.py:357-386`. Missing: regression test pins to prevent silent regression. | **ACCEPT** | Track 4 (tests only; no production code change) |
| **DF-48** | P-2 reasoning trace side-channel: code is **already implemented** at HEAD (`runner_stage.py:84,90,104,110` + `short_term.py:323` + `run_session.py:175`). Missing: Layer-2 test that persists and reads back a trace. | **ACCEPT** | Track 4 (bundled with DF-47; tests only) |
| **DF-49** | Rule 6 inline-fallback sweep: 12 `or DefaultClass()` patterns confirmed in `runner.py` (5), `evolve/engine.py` (3), `task_mgmt/scheduler.py` (2), `knowledge/knowledge_manager.py` (2). Pattern to apply: `runner.py:325-332` raise-on-missing. | **ACCEPT** | Track 3 (4 sequential commits per file) |

### Governance / housekeeping

| ID | Description | Verdict | Track / Target |
|----|-------------|---------|----------------|
| **H2-HK-1** | `.worktrees/fix-others-k8` and `.worktrees/fix-runner-k8` — H1-era parallel-agent leftovers still registered in `git worktree list` | **ACCEPT** | Track 5 |
| **H2-HK-2** | 6 env vars defined in code but absent from `docs/api-reference.md`: `HI_AGENT_API_TIMEOUT_SECONDS`, `HI_AGENT_ALLOW_HEURISTIC_FALLBACK`, `HI_AGENT_ENABLE_SHELL_EXEC`, `HI_AGENT_EVOLVE_MODE`, `HI_AGENT_PROFILE`, `WEBHOOK_URL` | **ACCEPT** | Track 5 |
| **H2-HK-3** | `docs/delivery/2026-04-25-5f57ff3-rule15-volces-v3.json` is untracked (working copy only); Rule 8 evidence must be under version control | **ACCEPT** | Track 5 |
| **H2-HK-4** | K-7 recursion guard: "in review" in `platform-gaps.md:53` vs "FIXED in WS-2/3/4" in `h1-intake-decisions.md`; doc drift | **ACCEPT** | Track 5 |
| **H2-HK-5** | `CapabilityDescriptor` schema duplication: `capability/registry.py:14-33` and `capability/adapters/descriptor_factory.py:9-35` have different schemas — latent defect | **DEFER** | H3 — file as DF-50 |

### Open backlog items (explicit carry-forward)

| ID | Description | Verdict | Track / Target |
|----|-------------|---------|----------------|
| **K-13** | PI-C + PI-D combination test (gate + subrun orchestration) listed as "added to backlog" in `platform-gaps.md:54` but no track assigned in H1 | **ACCEPT** | Track 6 |
| **P-4 dynamic re-planning** | `StageDirective(skip_to, insert_stage)` — Wave 9 | **DEFER** | Wave 9 |
| **Gap 4 durable substrate** | SQLiteRunQueue default-on, Temporal main-path — Wave 9 | **DEFER** | Wave 9 |
| **P-6 cost/budget governance** | — Wave 9 | **DEFER** | Wave 9 |
| **P-7 / Gap 6 evolution closed loop** | feedback → routing; — Wave 10 | **DEFER** | Wave 10 |
| **D-2 / P3-2 TierRouter.calibrate** | active calibration (record-only today) — Wave 10 | **DEFER** | Wave 10 |

### H1 DECLINE replies (unchanged; no H2 action required)

H1 declined three business-layer requests. These remain declined in H2; the research team has not yet filed written acknowledgement. No H2 code touches them.

| Source | Decline reason |
|--------|----------------|
| Foundation §4.2 ResearchProjectSpec DSL | Research-domain ontology; platform exposes `project_id` + free-form `metadata`. Research team builds domain DSL in their app layer. |
| Foundation §4.3 Force capability outputs into ArtifactLedger | Research artifact policy; platform exposes `POST /artifacts`. Research team writes the policy. |
| Round 7 I-8 `on_exhausted='escalate'` default | Policy preference, not a defect. Set `on_exhausted='reflect'` in profile JSON. |

---

## Track sequencing (normative)

```
T0 (this doc) → commits first → gates T1–T6 dispatch

T1   T2   T3   T4   T5   T6       ← parallel dispatch (no shared files)
  \   |   |    |    |   /
   ---+---+----+----+---
            T7                    ← sequential after T1–T6 merge to main
                                  (T3 record, delivery notice, push)
```

T3 is split into 4 sub-commits (one per file: runner, evolve, scheduler, knowledge) per Rule 2 anti-bundle. Each sub-commit lands with its paired unit test.

---

## Acceptance criteria (wave-level)

Before Track 7 pushes to main:

1. `pytest --collect-only -q` exits 0 with **0 errors** (C1 closed).
2. `curl http://host/profiles/hi_agent_global/l3` → 401 (C2 closed).
3. `rg ' or [A-Z][a-zA-Z]*\(' hi_agent/runner.py hi_agent/evolve/engine.py hi_agent/task_mgmt/scheduler.py hi_agent/knowledge/knowledge_manager.py` → zero matches (DF-49 closed).
4. `tests/integration/test_reflection_path_regression.py` and `test_reasoning_trace_persistence.py` pass (DF-47/48 pinned).
5. `tests/integration/test_picd_combination.py` passes (K-13 closed).
6. All 6 env vars appear in `docs/api-reference.md` (HK-2 closed).
7. `git ls-files docs/delivery/2026-04-25-5f57ff3-rule15-volces-v3.json` returns the path (HK-3 closed).
8. Rule 8 gate passes at new HEAD (T7).
9. Push to `origin/main` succeeds without `--force` or `--no-verify`.

---

*Signed: chaosxingxc-orion, 2026-04-25.*
*Research team acknowledgement required only if DECLINE scope changes — none changed in H2.*
