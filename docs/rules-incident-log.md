# Rules Incident Log

Historical incident records and narrow-trigger rule details extracted from CLAUDE.md.

---

## Historical Rule Evolution

- **"Goal-Driven Execution"** — merged into Rule 1. The core requirement ("convert vague instructions into falsifiable goals before starting") is absorbed by Root-Cause + Strongest-Interpretation disciplines.
- **"Think Before Coding"** — merged into Rule 1 (strongest-interpretation preamble). Surface assumptions and name confusion before writing code; stop and ask if unclear.
- **"Simplicity First" and "Surgical Changes"** — merged into Rule 2 together. Both express durable engineering hygiene.
- **Rule 18 (T3 Invariance) and Rule 19 (Mechanical Enforcement)** — merged into Rule 8 as T3 invariance clause + DF-46 CI tracking.
- **Rule 11 (Fail-Fast Test Sync)** — absorbed into Rule 3 pre-commit checklist as the "Fail-fast test sync" row.

---

## Narrow-Trigger Rules (Full Detail) {#narrow-rules}

### HTTP Contract Lock (triggered when changing `http_server.py` or `kernel_facade_client.py`)

`agent_kernel/service/http_server.py` is the **single authority** for endpoint definitions.
`hi_agent/runtime_adapter/kernel_facade_client.py` is the **single HTTP client** for those endpoints.

The PR must contain a side-by-side table for every kernel operation:

| Operation | Client call (path · method · body) | Server Route (path · method) | Match? |
|-----------|-----------------------------------|------------------------------|--------|
| `start_run` | `POST /runs · {run_kind, input_json}` | `POST /runs` | ✅ |

Every row must be ✅. Any ❌ blocks merge. Split PRs that leave client/server out of sync are rejected.

**Incident:** 2026-04-19 — `POST /runs/start` (wrong) vs `POST /runs`; `POST /runs/spawn_child` vs `POST /runs/{run_id}/children`; `POST /stages/open` vs `POST /runs/{run_id}/stages/open`. 100% POST /runs failure on downstream deploy.

### CI Secret↔Fixture 1:1 (triggered when modifying `.github/workflows/` conditions)

Every conditional CI step must gate on **exactly** the secrets its fixture reads — nothing more, nothing less.

Before adding/modifying any `if: ${{ env.X_API_KEY != '' }}`:
1. `grep -rn 'os.environ.get.*X_API_KEY\|getenv.*X_API_KEY'` in the test file and its fixtures.
2. Every `|| env.Y_API_KEY != ''` clause must have a matching consumer.
3. A secret meant to drive a different test goes behind a different step.

**Incident:** 2026-04-21 (runs 24701565968, 24703085914, 24703552799) — `Production E2E tests` gated on `VOLCE_API_KEY || OPENAI_API_KEY || ANTHROPIC_API_KEY`, but the fixture only reads OpenAI/Anthropic keys. When only VOLCE was present, the step ran but the server failed with 503 `platform_not_ready`.

### No Wall-Clock LLM Assertions (triggered when adding latency assertions against real LLM in CI)

Hard latency/timeout assertions against external LLM endpoints are forbidden in blocking CI steps.

Three acceptable patterns (preference order):
1. **Advisory-only**: `continue-on-error: true`; status check, not a gate.
2. **Budget with ≥3× headroom**: `3 × p95_observed_over_last_week`, not a fixed second-count.
3. **Trend-not-point**: assert no regression vs a recorded baseline with ≥50% headroom.

Never commit `assert response_time_s < 30` against a real LLM API.

**Incidents:**
- 2026-04-21 (run 24701988423): `test_response_latency[kimi-k2.5]` failed at 47 s vs 30 s assertion; model reachability was fine.
- 2026-04-21 (run 24702363330): `test_multi_turn_conversation[doubao-seed-2.0-pro]` timed out >120 s — same cause.

### Rule 19 — CI Mechanical Enforcement Plan (tracked as DF-46)

**Rule 8's T3 invariance must eventually be enforced mechanically, not by self-discipline.** Planned CI additions (tracked as DF-46):

1. **CI check via `scripts/check_rules.py`**: detect hot-path file changes in the commit range; require the PR description to name a `docs/delivery/*-rule15-volces.json` file whose git-tracked `committer-date` is ≥ the PR's first hot-path-touching commit date.
2. **Structural "zero-cost gate"**: `httpx.MockTransport` + in-process server verifying async/sync path selection, gateway identity, fallback-event visibility, cancel round-trip. Sub-second. Catches async-path flip class of defect without a real LLM call.
3. **Scheduled true-LLM gate**: nightly (or weekly) run of `scripts/rule15_volces_gate.py` against main. Failure posts to notification channel; branch marked "regression pending investigation."
4. **Rule 42 advisory checker becomes blocking** for hot-path PRs (scoped to files without known violations).

Until DF-46 closes: every hot-path PR must include the T3 evidence line in its body. Reviewer responsibility to enforce manually.

**Incident:** 2026-04-22 DF-45 — the root cause was not any single commit but the absence of mechanical Rule 15 enforcement. Every Wave-5/6 agent correctly believed their changes were green because nothing asked them to re-verify the shared invariant.

---

## Incident Records by Rule

### Rule 1 — Root-Cause + Strongest-Interpretation

- 2026-04-19: Three HTTP path mismatches (04-11, 04-19①, 04-19②) fixed as symptoms until the HTTP contract lock was added to attack the cause (no client/server verification gate).
- 2026-04-19: SSE `test_tc11` returned JSON, not event-stream. Surface diagnosis "wrong media_type" was wrong — StreamingResponse was never reached because the auth guard raised 401 first.
- 2026-04-15 Round 2 C-1: Round 1 asked for "Human Gate"; we delivered a notification API. Round 2 clarified "must block execution"; we delivered blocking. A stronger initial reading would have saved one round.
- 2026-04-15 Round 3 D-1: `GatePendingError` docstring showed `e.gate_id`; class body was empty (`AttributeError` at runtime). Writing the docstring counted as delivering the feature.

### Rule 2 — Simplicity & Surgical Changes

- 2026-04-15 Round 8: the self-audit delivery repaired 18 defects across 9 journeys but introduced 15 new ones (K-1 logger typo, K-8 dream scheduler race, K-11 MagicMock in journey test, etc.) because changes were bundled across modules without per-module review.
- 2026-04-22 DF-45: Wave 5 Agent W (DF-37.1 runner.py self.llm_gateway) and Agent X (DF-35 compressor.py record_fallback) ran in parallel. Both touched runner.py. Agent X committed second via `git reset --soft + re-commit`, silently absorbing Agent W's runner.py line into the DF-35 commit (`d8badfa`). The resulting commit message said "DF-35 wire record_fallback..." but the diff also carried DF-37.1's `self.llm_gateway = llm_gateway`. Bisecting DF-45 was harder because this commit wasn't atomic.

### Rule 3 — Pre-Commit Checklist

- 2026-04-11: 17× Python 2 `except A, B:` syntax + 12× UTF-8 BOM — import failed on downstream, would take <10 seconds locally. (smoke dimension)
- 2026-04-15 Round 8 K-1: `logger` vs `_logger` NameError — ruff would flag it. (lint green dimension)
- 2026-04-15 Round 3 D-1: empty `GatePendingError` class shipped with working docstring. (contract truth + docstring-implementation parity)
- 2026-04-15 Round 6 H-3: `_run_terminated` set but never read. (orphan returns)
- 2026-04-15 Round 4 F-1: `execute()` swallowed GatePendingError. (exception handler narrowness)
- 2026-04-15 Round 5 G-1, Round 8 K-2/K-3/K-15: async path forgot invariants the sync path had. (branch parity)
- 2026-04-15 Round 8 K-11: Journey test J5 used `MagicMock(RunExecutor)`. PI-D pattern had zero real coverage. (test honesty)
- 2026-04-15 Round 8 K-12: Journey test J6 asserted `status in ["completed", "failed"]`. (test honesty)
- 2026-04-19: duplicate `run_id='default'` blocked sequential runs. (ID uniqueness)
- 2026-04-21: SA-P1-6 fail-fast in `_default_executor_factory` broke `test_prod_e2e.py`. (fail-fast test sync)

### Rule 4 — Three-Layer Testing

- 2026-04-15 Round 8 K-11: Journey test J5 (sub-run dispatch) used `MagicMock(RunExecutor)`. PI-D pattern had zero real coverage; we shipped the test as evidence the fix worked.
- 2026-04-15 Round 8 K-12: Journey test J6 asserted `status in ["completed", "failed"]`. Failure was encoded as success in the assertion itself.
- Multiple rounds: "Layer 3 green" was taken as "shippable"; Rule 8 exists because Layer 3 cannot reproduce long-lived process + real LLM + `asyncio.run` interaction issues.

### Rule 5 — Async/Sync Resource Lifetime

- 2026-04-22 (16 sites enumerated in self-audit E3): `async_http_gateway.py:100` creates `httpx.AsyncClient` in `__init__`, calls `asyncio.run(self._inner.complete(...))` per method. Call 1 = 200 OK. Call 2 = `RuntimeError: Event loop is closed`. Call 3 = 429 from half-dead pool. 100% of downstream LLM traffic failed.

### Rule 6 — Single Construction Path

- 2026-04-15 Round 4 F-2: `profile_id` not propagated to `build_short_term_store`/`mid_term`/`long_term_graph` — memory cross-contamination.
- 2026-04-15 Round 5 G-5: `build_retrieval_engine()` created its own unscoped stores, defeating the F-2 fix.
- 2026-04-15 Round 7 I-7: `build_memory_lifecycle_manager()` was still unscoped — third occurrence.
- 2026-04-21 self-audit F-2: `knowledge_manager` still did `graph or LongTermMemoryGraph(...)` — explicitly labeled "the J7-1 defect re-surfacing." Fourth occurrence.

### Rule 7 — Resilience Must Not Mask Signals

- 2026-04-22: 41 heuristic fallbacks in a 14-minute run. Run reported `state=done`; no metric, no health flag, no metadata event. Downstream discovered the mass fallback only by reading internal logs. The fallback mechanism was correct as a safety net — the defect was that the safety net had no alarm.

### Rule 8 — Operator-Shape Readiness Gate + T3 Invariance

- 2026-04-22: former smoke passed in heuristic-fallback mode (3 sequential runs "completed" without hitting the real LLM). Under PM2 + real MaaS LLM, call 2 failed; heuristic fallback made all three runs look successful internally.
- 2026-04-22 (plan-level): attempted to classify Rule 15 as "ops work outside this session" while volces credentials were present in `config/llm_config.json`. The gate is executable from any environment where credentials resolve. The first real gate run (`docs/delivery/2026-04-22-rule15-volces.json`) surfaced DF-35 — a Rule-7 signal hole in `MemoryCompressor`/`SkillExtractor` fallback paths.
- 2026-04-22 DF-45: gate PASSED at commit `0247a7e` (tag: `rule15-pass-20260422`). Wave 5 + Wave 6 added 14 commits, 5 of them touching hot-path files. Every individual commit passed its own tests. Nobody re-ran the gate. Wave 6 Agent γ attempted an extended gate and every profile + concurrent section timed out. Re-running the baseline gate at HEAD also failed. T3 evidence at `0247a7e` was a snapshot, not an invariant.

### Rule 9 — Self-Audit is a Ship Gate

- 2026-04-22: self-audit listed "E3 async 16 sites — Flagged". Delivery notice said "P0/P1 修了，H/D 级还开着". The flagged E3 item was the fatal defect downstream hit. It met LLM-path and resource-lifetime categories, but shipped under the "Orange / architectural debt" internal label.

### Rule 10 — Downstream Contract Alignment

- 2026-04-16: downstream produced a 387-line strategic roadmap proposing platform/business split + 43% readiness score + Phase 0→3 path. No response was written, filed, or committed in the six days following. 2026-04-22's incident happened inside the vocabulary gap: our self-audit labeled the defect Orange/E3; downstream's PI-D pattern was 100% broken. The same defect had two names and no shared severity scale.
