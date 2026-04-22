# hi-agent Response to 2026-04-16 Strategic Roadmap

**From**: hi-agent team
**To**: Research Intelligence Application (RIA) team
**Date**: 2026-04-23
**Re**: `hi-agent-strategic-roadmap-2026-04-16.md` (387 lines, received 2026-04-16)
**Status**: Ready to send — on branch `claude/distracted-poitras` tag `rule15-pass-stable-2026-04-23`

---

## 1. Apology and acknowledgment

On 2026-04-16 you delivered a 387-line strategic roadmap proposing a platform/business layer separation, a 7-dimension readiness scorecard (43% overall), seven concrete platform gaps, and a four-phase delivery path. **We received it and did not respond for six days.** No written reply, no filed acknowledgment, no counter-proposal, no file committed under `docs/downstream-responses/`. On 2026-04-22 you reported the platform was still not working in your production shape — and the failure happened inside exactly the vocabulary gap the roadmap was trying to close. That silence was a mistake and we own it fully.

We are not going to minimize this. Six rounds of defect review (Rounds 2–7), a self-audit (Round 7.5), a Round-8 follow-up (15 K-defects), and a 387-line strategic document — and the strategic document was the one we dropped. Our internal audit taxonomy kept producing internal labels (E3 / H4 / D1 / F-N) that did not map onto your capability patterns (PI-A..PI-E). We kept speaking about code shape; you kept speaking about delivered capability. The 2026-04-22 prod-mode incident was the point where the gap stopped being abstract.

**What changed in response.** CLAUDE.md was extended with a three-rule relationship gate:

- **Rule 15 — Operator-Shape Readiness Gate.** No artifact ships until it runs in the exact operator shape you use (long-lived process, real LLM, 3 sequential runs, no fallback events, cross-loop stability, cancellation round-trip). Green pytest alone does not authorize delivery.
- **Rule 16 — Self-Audit is a Ship Gate, Not a Disclosure.** A self-audit with open findings in any downstream-correctness category (LLM path, run lifecycle, HTTP contract, security, resource lifetime, observability) blocks delivery. Attaching an honest defect list does not authorize shipping with it.
- **Rule 17 — Downstream Contract Alignment.** The authoritative vocabulary is yours. Delivery notices use PI-A..PI-E impact and readiness % changes, not internal labels. A strategic document from you requires a written response in this directory. When internal taxonomy and your pattern impact disagree on severity, yours wins.

These rules are now enforced on every PR going forward. The 2026-04-16 → 2026-04-22 silence is the incident record that motivated them.

---

## 2. Acceptance of the platform/business layer separation

**We accept the split as you defined it.** hi-agent is the platform; RIA is the business layer.

We commit to **not** build inside the platform:

- Research-specific workflows (literature review, hypothesis verification, citation synthesis).
- Academic source bundles or domain-specific capability packs.
- Domain prompts written in any language other than English (the platform language rule applies — non-English prompts must live in the business layer or in an externally-loaded resource file).
- Business-layer decision logic (which stages to run for a given research question, what a "theme" is, how to rank literature).

We commit to build inside the platform:

- The execution engine, kernel lifecycle, stage graph, run state machine.
- Memory infrastructure (L0–L3), scoping primitives (profile, project, workspace).
- Capability plugin system, provenance contract, artifact contract.
- Dynamic re-planning API (`StageDirective`), gate protocol, sub-run delegation.
- Feedback ingestion infrastructure, evolution hooks.
- HTTP / MCP / CLI surface.

The platform/business contract document this produces will be committed as `docs/platform/platform-business-boundary.md` alongside the Phase 1 delivery (see §6). If any of the above allocation is wrong in your view, we adjust before Phase 1 ships.

---

## 3. Readiness assessment — our view

Our re-score (full evidence in `docs/audit-findings/C-platform-fit.md`):

| Dimension | Your baseline (04-16) | Our re-score (04-23) | Delta reason |
|-----------|------------------------|----------------------|--------------|
| Execution Engine (TRACE pipeline) | 75% | **75%** | Async/sync unified, reflect loop bounded, stage orchestrator extracted. Rule 15 gate now passed against real volces at tag `rule15-pass-stable-2026-04-23`. `self.llm_gateway` assignment fixed (DF-37.1); `TaskDescriptor(goal=)` backward-compat restored (DF-28). |
| Memory Infrastructure (L0–L3) | 70% | **78%** | `project_id` scope landed across `short_term`, `long_term`, `session`. `run_id` threaded into compression/context/task_view for fallback attribution (DF-39). `record_fallback` wired in `MemoryCompressor` and `SkillExtractor` (DF-35). |
| Capability Plugin System | 65% | **60%** | `Provenance` contract landed, but built-in capabilities in `capability/defaults.py` do not populate it — contract exists on paper for unmigrated callers. |
| Knowledge Graph | 35% | **55%** | `find_transitive_closure()`, `find_conflicts()`, `get_subgraph_with_confidence()` landed on `LongTermMemoryGraph`. Missing: unified `GraphQueryEngine` surface, property inheritance. |
| Planning & Re-planning | 40% | **55%** | `StageDirective` + `replan_hook` landed in linear traversal. Graph traversal does not yet honor the hook. |
| Output & Artifact Contracts | 30% | **55%** | `Artifact.confidence: float = 0.0` present; read from capability output dicts. Missing: `ConfidenceScorer` base class, `evidence_count`. |
| Evolution & Feedback | 20% | **48%** | `FeedbackStore`, `RunFeedback`, `POST /runs/{run_id}/feedback`, auto-ingest on finalize. `record_fallback` signal now wired at postmortem silent-fallback branches (DF-39/C6). Missing: wiring into `HybridRouteEngine`. |
| Cross-Run State (Project) | 0% | **50%** | `project_id` is first-class scope; `list_runs_by_project()` aggregates. Missing: `ProjectSession` class, explicit cross-run lifecycle manager, real-deployment proof that two runs read each other's L3. |

**Overall: ≈60% (up from 43%).**

**Where we agree with your 04-16 baseline**: your severities on Knowledge Graph (35%), Planning (40%), Artifact Contracts (30%), Cross-Run (0%), and Evolution (20%) were accurate for that date. Your Execution Engine number (75%) was generous — we had never recorded a real-LLM long-lived-process run, so our "75%" was unsupported.

**Where we disagree**: scaffolds have landed for every P-1..P-7 gap, so the per-dimension deltas are positive — but **no dimension has reached "production-ready" (75%+)**. The scaffolds are necessary, not sufficient. We do not claim RIA can be built today; we claim the platform contracts are now present to build against.

---

## 4. Platform gaps P-1..P-7 — commitments

| Gap | Current status (evidence) | Phase | Our commitment + acceptance criterion |
|-----|----------------------------|-------|---------------------------------------|
| **P-1 Provenance** | **partial** — `contracts/provenance.py`; `RawEventRecord.provenance` field; built-in capabilities do not populate | Phase 1 (weeks 2–6) | Acceptance: in a real-LLM web-search stage, 100% of L0 entries written via `capability/defaults.py` carry non-null `provenance.url`. Testable via an operator-shape gate run with provenance count assertion. |
| **P-2 Reasoning Trace** | **partial** — `contracts/reasoning.py`; `session.write_reasoning_trace()`; no stage-executor side-channel | Phase 1 | Acceptance: business-layer stage handler returns a `ReasoningTrace`; platform persists it to L1 under the run without requiring handler code to touch `session` directly. Exposed as an API on the stage-handler protocol. |
| **P-3 Project Aggregation** | **landed (core)** — `project_id` across session + short-term + long-term; `list_runs_by_project()` | Phase 1 closure | Acceptance: two runs with the same `project_id` can read each other's L3 memory end-to-end in a real deployment (operator-shape gate artifact). Mid-term tier scoping confirmed. |
| **P-4 Dynamic Re-planning** | **landed (linear only)** — `StageDirective`; `replan_hook` consumed in `run_linear()`; not in `run_graph()` | Phase 2 (start of, instead of middle) | Acceptance: business-layer handler redirects TRACE from S2 to a dynamically-inserted stage under both linear and graph traversal. Journey test covers it. |
| **P-5 Confidence Scoring** | **partial** — `Artifact.confidence: float = 0.0`; no `ConfidenceScorer` base class | Phase 1 | Acceptance: business layer subclasses `ConfidenceScorer`; values appear in run output. Add `evidence_count: Optional[int]` field as requested. |
| **P-6 Graph Inference** | **landed (narrow)** — `find_transitive_closure()`, `find_conflicts()`; no unified surface | Phase 2 | Acceptance: unified `GraphQueryEngine` class wrapping the three existing methods + property inheritance. Existing method signatures preserved for backward compatibility. |
| **P-7 Feedback Integration** | **landed (storage)** — `FeedbackStore`, HTTP route, auto-ingest. **Not wired to routing.** | Phase 2 | Acceptance: a low-rating feedback event on one profile demonstrably shifts routing on the next run of that profile, observable via decision-audit log. |

**Counter-proposals on phase ordering:**

- **P-4 (Dynamic Re-planning) moves to early Phase 2, not middle.** The linear-mode scaffold is already in; completing graph-mode + a real journey test is a small additional cost now and unlocks your discovery-driven research pattern. Deferring it to middle Phase 2 would force you to queue research-plan revisions behind platform work.
- **P-7 (Feedback wiring) stays in Phase 2 but we flag the risk**: the route-engine integration is where scope can grow — we commit to a *soft preference signal* only (as the roadmap states), not a full multi-armed-bandit or RLHF loop. If you need stronger feedback shaping, it is a separate Phase-3 initiative.
- **P-3 (Project Aggregation) core work is done; we close it in Phase 1 rather than doing net-new.** The remaining items are the `ProjectSession` class, cross-run lifecycle manager, and the real-deployment proof. This frees Phase 2 capacity for P-4 and P-6.

**Nothing deferred to Phase 3.** The Phase-3 items in the 04-16 roadmap (Specialist Routing, Conflict Resolution Protocol, Uncertainty Propagation, Memory Forgetting Policy, Parallel Stage Execution) remain in Phase 3 as framed.

---

## 5. Phase 0 defect clearance (K-1..K-15)

From `docs/audit-findings/C-platform-fit.md` Task 2 — verification as of 2026-04-23:

| K-ID | Severity | Status | Evidence / close plan |
|------|----------|--------|----------------------|
| K-1 | Critical | **fixed** | `hi_agent/runner.py` — all `logger` → `_logger`; no bare `logger` identifiers remain. |
| K-2 | High | **fixed** | `hi_agent/runner.py` — `executor._run_id = run_id` in `execute_async`. |
| K-3 | High | **partial** | Signature handled via `inspect.isawaitable()` on the return of `start_run(run_id=..., session_id=..., metadata=...)`. Works but not the option-A alignment you requested. **Commit**: align with sync positional form in Phase 0 closure if that's preferred; otherwise document the duck-typed contract. |
| K-4 | Medium | **fixed** | `hi_agent/executor_facade.py` — silent `except: pass` replaced with `_logger.warning`. |
| K-5 | Medium | **fixed** | `hi_agent/context/manager.py` — `_logger.warning(..., exc_info=True)`. |
| K-6 | Medium | **fixed** | `hi_agent/runner.py` — gate-resume now checks for subsequent `gate_decision`/`gate_resolved`. |
| K-7 | Medium | **fixed** | `hi_agent/execution/recovery_coordinator.py` — `_max_total_attempts = max_retries * 2 + 1` bounded loop. |
| K-8 | Medium | **fixed** | `hi_agent/server/dream_scheduler.py` — `_last_dream_at_run_count` guard. |
| K-9 | Medium | **partial** | `build_server()` still calls `build_memory_lifecycle_manager()` without profile_id. **Commit**: either declare server-level manager is intentionally unscoped (with per-request profile in API) or plumb a default-profile parameter in Phase 0 closure. Our preference is the former with API-level profile_id; we ask for your preference. |
| K-10 | Low | **fixed** | `hi_agent/config/builder.py` — profile_id extracted from checkpoint and propagated. |
| K-11 | High | **unfixed** | J5 still uses `MagicMock` for child_kernel in journey tests. **Commit**: rewrite J5 and J9 against real `MockKernel` adapter in Phase 0 closure (2 weeks). This is the PI-D coverage gap and it is load-bearing. |
| K-12 | Medium | **fixed** | `tests/integration/test_journeys.py` — strict `== "completed"`. |
| K-13 | Low | **unfixed** | No cross-capability combo tests. **Commit**: four new tests (gate+checkpoint, reflect+checkpoint, concurrent sub-runs, profile+checkpoint) ship with K-11 rewrite in Phase 0 closure. |
| K-14 | Low | **unfixed** | `hi_agent/task_mgmt/delegation.py` — Chinese strings feed into LLM summarization prompt. **Commit**: translate to English in Phase 0 closure. |
| K-15 | Low | **fixed** | `hi_agent/runner.py` — `executor._run_start_monotonic = time.monotonic()`. |

**Phase 0 close plan (next 2 weeks):**

1. Rewrite J5 + J9 without MagicMock; add 4 combination journey tests (K-11 + K-13).
2. Translate `delegation.py` prompt strings to English (K-14).
3. Decide and document K-3 (align to sync form or document the duck-typed contract) and K-9 (API-level profile or default-scoped manager) — asking your preference here before implementing.
4. Rule-15 operator-shape gate now recorded (see §6 below). The 2026-04-23 gate run is the first clean T3 evidence post-DF-45 regression recovery.

**Phase 0 acceptance = all of: Ks above closed + Rule-15 gate recorded.**

---

## 6. Incident post-mortem: 2026-04-22 DF-45 regression and recovery

**What happened (2026-04-22 → 2026-04-23).**
After the initial T3 gate passed at commit `0247a7e` (tag `rule15-pass-20260422`), fourteen further commits landed on the development branch — five touching hot-path files. No CI mechanism required re-verification. On 2026-04-22, every gate run at HEAD failed: runs reached `state=201 Created` but never reached terminal state. This was DF-45.

**Root cause (mechanical).**
Two compounding failures:
1. `AsyncHTTPGateway` constructed `httpx.AsyncClient` in `__init__` but invoked it via per-call `asyncio.run()`. Call 1 succeeded; call 2 failed because the first `asyncio.run()` closed the event loop that owned the client pool.
2. No CI gate checked hot-path file changes and demanded new T3 evidence. Every individual commit passed its own unit/integration tests. Nobody re-ran the system-level gate.

**What was fixed.**

- **DF-45 / RC-3 deferred as D.3**: the async gateway path requires `sync_bridge.py` (not yet implemented). The sync gateway path (`HttpLLMGateway`) is the supported production path. Decision documented in `docs/decisions/df-38-async-defer.md`.
- **DF-35**: `record_fallback()` wired at `MemoryCompressor` and `SkillExtractor` silent-fallback branches. Rule 14 signal holes closed.
- **DF-37.1**: `self.llm_gateway` assignment added in `RunExecutor.__init__` so `/ready` no longer raises `platform_not_ready` in real LLM mode.
- **DF-28**: `TaskDescriptor(goal=)` backward-compat restored in `reflection_bridge.py`.
- **DF-39**: `run_id` threaded into compression, context/manager, task_view/auto_compress for accurate fallback attribution.
- **Rule 19 (new)**: `scripts/rule15_structural_gate.py` (zero-LLM-cost, <2s) is now a blocking CI job on every PR. Catches wiring regressions (async/sync flip, cancel broken, run wedge) before any LLM call is needed.
- **Rule 18 (new)**: hot-path file changes require a fresh T3 gate run as a PR requirement.

**Recovery path.** A clean baseline (`claude/distracted-poitras`) descended from tag `rule15-pass-20260422` was identified. Phase B (structural gate) and Phase C defect re-lands were performed as single-concern commits, each passing the structural gate. The real-LLM gate (`scripts/rule15_volces_gate.py`) was run on the final tip, producing the T3 evidence below.

> Between the 2026-04-22 initial T3 evidence and further remediation work, a regression (DF-45) was introduced by unverified hot-path changes. We isolated the regression on a development branch and rebuilt delivery from the known-T3 baseline. CLAUDE.md Rules 18 and 19 now require mechanical re-verification of the Rule 15 gate after every hot-path change — this class cannot recur in our protocol.

**2026-04-23 Rule 15 verification evidence** (replaces 2026-04-22 gate; supersedes tag `rule15-pass-20260422`):
`docs/delivery/2026-04-23-rule15-volces-c10c11.json` — operator-shape gate passed against real volces at tag `rule15-pass-stable-2026-04-23`:

- 3 sequential runs, all `state=completed`, zero `fallback_events`
- Run durations: 123.2s / 65.1s / 67.1s (first run includes server warm-up)
- `llm_mode=real`, `llm_provider=volces`
- `cancel_known=200`, `cancel_unknown=404`
- Total gate duration: 256s

PI impact of this release:

| PI pattern | Impact |
|------------|--------|
| PI-A (Single-stage real-LLM run) | **Restored** — runs complete without fallback in real LLM mode |
| PI-B (Multi-stage with memory) | **Improved** — fallback events now attributed with run_id |
| PI-C (Gate + reflect) | **No change** — gate protocol unmodified |
| PI-D (Sub-run delegation) | **Stable** — not touched in DF-35/37/39 re-lands |
| PI-E (Evolution + feedback) | **Improved** — postmortem/skill_extractor silent fallbacks now tracked |

---

## 7. Next three concrete deliveries (next two weeks)

1. **Phase 0 closure delivery** — K-3 decision + K-9 decision + K-11 rewrite + K-13 four journey tests + K-14 translation. Delivered together in one PR with a Rule-15 gate record.
2. **P-1 Provenance full wiring** — all built-in capabilities in `capability/defaults.py` populate `provenance`. Operator-shape gate asserts provenance-non-null count on a web-search stage.
3. **Platform/business boundary document** — `docs/platform/platform-business-boundary.md` formalizes §2 of this response as a contract, committed before Phase 1 ships.

---

## 8. Ongoing commitments

- **Every future delivery comes with a Rule-15 operator-shape gate record** in `docs/delivery/<date>-<sha>.json` (long-lived process, real LLM, 3 sequential runs, zero fallback events, cross-loop stability, cancellation round-trip). No recorded gate run = not delivered.
- **Every delivery notice uses PI-A..PI-E impact language** ("This release restores PI-D functionality; PI-E remains blocked on P-4"). No internal labels (E3/H4/D1/F-N) in delivery notices.
- **Self-audit findings in ship-blocking categories block delivery** — LLM path, run lifecycle, HTTP contract, security boundary, resource lifetime, observability. "Flagged but not fixed" is a defect, not a disclosure.
- **Strategic documents from you always get a written response within 72 hours**, filed under `docs/downstream-responses/`. The 6-day silence that produced this document will not recur — it has a rule, an incident record, and a file location.
- **When our internal severity disagrees with your pattern impact, yours wins.** An Orange / architectural-debt defect that breaks PI-D is a P0.
- **Rule 19 (mechanical enforcement)**: the zero-cost structural gate blocks every PR; the real-LLM gate is required for hot-path changes. DF-45's root cause (discipline-only enforcement) cannot recur.

---

## 9. What we are asking from you

1. **Confirm the platform/business split in §2** before we commit `docs/platform/platform-business-boundary.md`. Specifically: are any items in the "hi-agent builds" list actually RIA-business in your view, or vice versa?
2. **Preference on K-3** (align to sync positional form vs. document duck-typed contract) and **K-9** (API-level profile parameter vs. default-scoped server manager).
3. **Preference on P-4 phase placement** (we propose early Phase 2 instead of middle).
4. **Acknowledge receipt of this response** so we record the relationship-gate loop closed. The relationship failure was the silence, not the defects — the response-send is the fix.

---

*— hi-agent team, 2026-04-23*
