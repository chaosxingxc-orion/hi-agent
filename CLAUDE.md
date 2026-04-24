# CLAUDE.md

## Language Rule

**Translate all instructions into English before any model call.** Never pass Chinese, Japanese, or other non-English text into an LLM prompt, tool argument, or task goal.

---

## Project Status

**Active implementation — production engineering phase.** Full design baseline at `architecture-review/`.

Architecture reference → `docs/architecture-reference.md`

---

## AI Engineering Rules

**Ten rules.** Rules 1–4 are daily-use engineering principles. Rules 5–7 are class-level patterns triggered by resource type. Rules 8–10 are delivery gates. All rules override default habits; CLAUDE.md overrides everything except explicit user instructions.

Automated checks: `scripts/check_rules.py` enforces the Language Rule, Rule 4 (three-layer testing, advisory), Rule 5 (asyncio.run sites), Rule 6 (inline fallback pattern) via `.github/workflows/claude-rules.yml`. Hot-path T3 gate enforcement tracked as DF-46.

Incident records and narrow-trigger rule details → `docs/rules-incident-log.md`

---

### Rule 1 — Root-Cause + Strongest-Interpretation Before Plan

**Before writing any plan, fix, or feature — surface assumptions, name confusion, and state tradeoffs. Then (a) name the root cause mechanically and (b) choose the strongest valid reading of the requirement.**

Do not pick one reading silently and ship it expecting the requester to ask again. If unclear, stop and ask first.

**(a) Root-cause discipline** — required before any plan:
1. **Observed failure**: exact error message or test output
2. **Execution path**: which function calls which, where it diverges from expectation
3. **Root cause statement**: one sentence — "X happens because Y at line Z, which causes W"
4. **Evidence**: file:line references that confirm the cause, not the symptom

**(b) Strongest-interpretation defaults:**
- "Gate" → **blocking**, not notification
- "Isolation" → **per-tenant/profile scope**, not process scope
- "Persist" → **survives restart**, not in-memory
- "Compatible" → **same signature + same semantics**, not "same name"

**Enforcement**: A PR without the four-line root-cause block is rejected. A PR delivering the weaker reading of an ambiguous requirement without a prior question is rejected.

---

### Rule 2 — Simplicity & Surgical Changes

**Minimum code that solves the stated problem. Touch only what the task requires.**

- No speculative features, one-use abstractions, unrequested configurability, or impossible-scenario error handling.
- Reach for a library before inventing a framework; reach for a function before inventing a class hierarchy.
- Do not improve, reformat, or rename adjacent code in the same commit. Match surrounding style exactly.
- Remove only imports/variables/functions that **your** change made unused — leave pre-existing dead code for a separate cleanup commit.

**Parallel-dispatch anti-bundle clause:** when multiple agents run in parallel and any two touch the same file:
1. The second-to-commit agent **rebases** onto the first — never `git reset --soft` + re-commit (silently absorbs the other agent's work).
2. Any commit spanning >1 defect ID in its message OR touching files in >2 distinct modules must be split before merge.
3. `git diff --cached --stat | wc -l` > 6 files is a yellow flag; >10 is a red flag requiring justification in the commit body.

---

### Rule 3 — Pre-Commit Checklist

Before every commit, audit every touched file across all dimensions below. Fix defects before committing — "I'll fix it later" is forbidden.

| Dimension | Check |
|-----------|-------|
| **Contract truth** | No `pass`, `NotImplementedError`, or stub bodies. |
| **Orphan config** | Every parameter / config field / env var is consumed downstream. |
| **Orphan returns** | Every non-`None` return is consumed by the caller. |
| **Subsystem connectivity** | No broken DI, unattached components, missing wiring. |
| **Driver-result alignment** | Every decision-driving field produces an observable effect. |
| **Error visibility** | No silent `except: pass`. Every catch re-raises, logs at `WARNING+`, or converts to typed failure. |
| **Exception handler narrowness** | `except Exception:` must not catch `GatePendingError`/`KeyboardInterrupt` without explicit filtering first. |
| **Branch parity** | Async and sync paths mirror each other's invariants (`_run_id` set, reflection prompt injected, timers initialized). |
| **Docstring-implementation parity** | Every example in a docstring executes without `AttributeError`/`TypeError`. |
| **Test honesty** | No `MagicMock` on the unit under test in integration tests. No assertion that accepts failure as success. |
| **Lint green** | `ruff check .` exits 0. No `# noqa` added in the same commit as the offending line. |
| **ID uniqueness** | Runtime IDs from caller or `uuid.uuid4()`. No `run_id='default'` semantic-label fallback. |
| **Fail-fast test sync** | If a PR tightens a silent path to fail-fast (`raise RuntimeError`, 503, hard validation), update all affected tests in the same PR. |

**Smoke + lint** — required before every commit touching `hi_agent/server/`, `hi_agent/runtime_adapter/`, `agent_kernel/service/`, or any `__init__.py`:

```bash
ruff check .                                      # exit 0 required
python -c "import hi_agent; import agent_kernel"  # exit 0, no stderr
python -m hi_agent serve --port 8080 &            # background
sleep 3 && curl -sf http://127.0.0.1:8080/health | jq .
```

Pass criteria: ruff clean, import clean, `/health` returns 200 within 3 s. Rule 3 gates a **commit**, not a delivery (Rule 8 gates delivery).

---

### Rule 4 — Three-Layer Testing, With Honest Assertions

A feature is implementable only when all three layers are designed. A feature is shippable only when all three are green **and** Rule 8 passes.

- **Layer 1 — Unit**: one function per test; mock only external network or fault injection, with reason in docstring.
- **Layer 2 — Integration**: real components wired together. **Zero mocks on the subsystem under test.** Skip with `@pytest.mark.skip(reason="awaiting real implementation")` if a dependency is absent — never fake it.
- **Layer 3 — E2E**: drive through the public interface (HTTP / CLI / top-level API); assert on observable outputs, not internal variables.

**Test honesty is not optional**:
- An integration test that `MagicMock`s the executor is a unit test mislabeled.
- An assertion of shape `result.status in ["completed", "failed"]` is not a test — it is documentation that the feature might not work.
- A test named `test_foo_works` that passes when `foo` raises is a lie.

---

### Rule 5 — Async/Sync Resource Lifetime

**Async-first core, sync-bridge via a single durable event-loop thread.** Every async resource (`httpx.AsyncClient`, `aiohttp.ClientSession`, `asyncpg.Pool`, async generators, anyio task groups) has a lifetime **bound to exactly one event loop**.

**Forbidden patterns:**
1. Constructing an async resource in `__init__` of a sync-facing class, then calling `asyncio.run(...)` on its methods.
2. Sharing one `AsyncClient`/`ClientSession` across two `asyncio.run(...)` calls.
3. Passing an async resource built in loop A into a coroutine on loop B.
4. Wrapping an async library with a sync façade that `asyncio.run`s per method.

**Required patterns** — pick one per call site:
- **Async-native**: caller is already async; use the resource under its owning loop.
- **Sync bridge**: route through `hi_agent.runtime.sync_bridge` (persistent loop on dedicated thread; marshals via `asyncio.run_coroutine_threadsafe`).
- **Per-call construction** (cheap resources only): `async with httpx.AsyncClient(...) as c:` inside the coroutine.

**Pre-commit check:**
```bash
rg -n 'asyncio\.run\(' hi_agent/ agent_kernel/
```
Every match must be in an entry point (`__main__`, CLI, test) or routed through `sync_bridge`.

---

### Rule 6 — Single Construction Path Per Resource Class

**For every shared-state resource, exactly one builder function owns construction. All consumers receive the instance by dependency injection. Inline fallbacks of the shape `x or DefaultX()` are forbidden.**

When a class needs profile/workspace/project scoping, scope is a **required constructor argument**, not an optional kwarg with a default. Missing scope must be a hard error, not a silent fresh unscoped instance.

**Forbidden patterns:**
```python
self.raw_memory = raw_memory or RawMemoryStore()          # silent unscoped instance
def build_short_term_store(profile_id: str = "") -> ...:  # optional scope
```

**Required patterns:**
```python
def __init__(self, raw_memory: RawMemoryStore):           # injection required
    self.raw_memory = raw_memory                          # no fallback

def build_short_term_store(*, profile_id: str, workspace_key: WorkspaceKey) -> ...:
    if not profile_id:
        raise ValueError("profile_id required")
```

**Pre-commit check:**
```bash
rg -n ' or [A-Z][a-zA-Z]*Store\(|\bor [A-Z][a-zA-Z]*Graph\(|\bor [A-Z][a-zA-Z]*Gateway\(' hi_agent/
```
Every match is a defect candidate. Remaining fallbacks must be documented inline with the threat they answer.

---

### Rule 7 — Resilience Must Not Mask Signals

Every silent-degradation path emits a **loud, structured, ship-gate-visible** signal. Required for each fallback branch:

1. **Countable**: named Prometheus counter on `/metrics` (`hi_agent_llm_fallback_total`, `hi_agent_heuristic_route_total`, etc.).
2. **Attributable**: `WARNING+` log with `run_id` and trigger reason at the branch entry.
3. **Inspectable**: run metadata carries `fallback_events: list[dict]`. A terminal run with non-empty fallback_events is not "successful" for delivery purposes.
4. **Gate-asserted**: Rule 8's operator-shape gate asserts `llm_fallback_count == 0` — any non-zero blocks ship.

Introducing or touching a fallback requires all four. A fallback without an alarm bell is a defect disguised as resilience.

---

### Rule 8 — Operator-Shape Readiness Gate + T3 Invariance

**No artifact ships until it runs in the exact operator shape downstream will use.** Green pytest, green Layer 3 E2E, and a clean self-audit do not authorize delivery by themselves.

Before any artifact leaves the repo (zip, pip, docker, PM2 bundle), the following must pass in a clean environment mirroring the target deployment:

1. **Long-lived process** — PM2 / systemd / docker run; not foreground `python -m hi_agent serve`. Process survives steps 2–6.
2. **Real LLM** — `HI_AGENT_LLM_MODE=real`, pointing at the provider downstream will use. Mock gateways disqualify.
3. **Sequential real-LLM runs (N≥3)** — three back-to-back `POST /runs`, each:
   - reaches `state=done` in ≤ `2 × observed_p95`,
   - has `llm_fallback_count == 0` in run metadata (Rule 7),
   - emits ≥1 outgoing LLM request in access log + `hi_agent_llm_requests_total` metric.
4. **Cross-loop resource stability** — runs 2 and 3 reuse the same gateway/adapter instance as run 1 (Rule 5 stress test). No `Event loop is closed`, no `ConnectTimeout` on call ≥2.
5. **Lifecycle observability** — each run reports a non-`None` `current_stage` within 30 s; `finished_at` populated on terminal. `current_stage==None` for >60 s on a non-terminal run is a FAIL.
6. **Cancellation round-trip** — `POST /runs/{id}/cancel` on a live run → 200 + drives terminal; on unknown id → 404, not 200.

All six hold. Any FAIL blocks ship. The artifact owner records the gate run in `docs/delivery/<date>-<sha>.md`. Unrecorded ≠ passed.

**T3 Invariance** — a gate pass is valid only for the SHA at which it was recorded. Any subsequent commit touching hot-path files invalidates T3 until a fresh gate run is recorded.

Hot-path files: `hi_agent/llm/**`, `hi_agent/runtime/**`, `hi_agent/config/cognition_builder.py`, `hi_agent/config/json_config_loader.py`, `hi_agent/config/builder.py`, `hi_agent/runner.py`, `hi_agent/runner_stage.py`, `hi_agent/runtime_adapter/**`, `hi_agent/memory/compressor.py`, `hi_agent/server/app.py`, `hi_agent/profiles/**`

On any PR touching hot-path files, the PR description must include one of:
- `T3 evidence: docs/delivery/<YYYY-MM-DD>-<sha>-rule15-volces.json` (gate run from this PR's tip), OR
- `T3 evidence: DEFERRED — <reason>` (PR tagged "requires gate before release"; may merge to dev but NOT to release)

T1/T2 (unit + integration) passing does NOT preserve T3. At any time the repository has exactly one "last known T3" tag.

---

### Rule 9 — Self-Audit is a Ship Gate, Not a Disclosure

A self-audit with open findings in a downstream-correctness category **blocks delivery**. Attaching an honest defect list does not authorize shipping with them.

**Ship-blocking categories (any open finding blocks):**
- LLM path (gateway, adapter, streaming, async lifetime, retry, rate-limit)
- Run lifecycle (stage, state machine, cancellation, resume, watchdog)
- HTTP contract (path, method, body, status, auth)
- Security boundary (path traversal, `shell=True`, auth bypass, tenant-scope escape)
- Resource lifetime (async clients, file handles, subprocesses, background tasks)
- Observability (missing metric, log, or health signal for a failure path)

**Forbidden phrasing in delivery notices:**
- "P0/P1 fixed, H-level open, shipping this version"
- "Flagged but not fixed — ok for this round"
- "Will address in follow-up PR"
- "Orange severity, architectural debt, safe to ship"

If leadership explicitly accepts the risk: reclassify as a **Known-Defect Notice**, signed by name, acknowledged in writing by downstream before transfer, with user-visible symptoms spelled out per defect.

---

### Rule 10 — Downstream Contract Alignment

**The authoritative vocabulary for capability assessment is downstream's, not ours.**

`docs/downstream-responses/` contains the reference roadmap. Downstream defines:
- Platform/business layer separation (platform = hi-agent team; business = research team).
- 7-dimension readiness scorecard (Execution / Memory / Capability / Knowledge Graph / Planning / Artifact / Evolution / Cross-Run).
- Capability patterns **PI-A through PI-E**.
- Platform gaps **P-1 through P-7**.

**When interacting with downstream:**
- Delivery notices use **their** taxonomy (PI-A..PI-E impact, readiness % change, gap P-N status), not our internal labels (E3/H4/D1/F-N).
- When our defect taxonomy and downstream's usage pattern disagree on severity, **downstream's severity wins**.
- A strategic roadmap / gap analysis from downstream requires a written response under `docs/downstream-responses/`.

**Enforcement:**
- Every delivery notice contains a "Readiness delta" table keyed by the 7 downstream dimensions.
- Every delivery notice maps changes to PI-A..PI-E impact.
- Outstanding gap items (P-1..P-7) tracked in `docs/platform-gaps.md`.

---

## Operational Appendix

### Narrow-Trigger Rules

These apply only when the stated condition is true. Full detail and incident records → `docs/rules-incident-log.md#narrow-rules`.

| Condition | Required action |
|-----------|-----------------|
| Changing `agent_kernel/service/http_server.py` or `kernel_facade_client.py` | PR must include side-by-side client↔server path/method table; every row ✅ before merge. |
| Adding/modifying CI `if: ${{ env.X_API_KEY != '' }}` | Grep consumers first; every `\|\|` clause must have a matching read in the fixture. |
| Adding latency assertions against a real LLM in CI | Only advisory (`continue-on-error: true`), ≥3× p95 headroom, or trend-not-point. Never a fixed second-count. |

### Rule Origin Mapping

| New | Absorbed from |
|-----|---------------|
| Rule 1 | Old Rule 1 + Rule 2 (Think Before Coding) |
| Rule 2 | Old Rule 3 + Rule 4 |
| Rule 3 | Old Rule 5 + Rule 6 + Rule 11 (fail-fast sync) |
| Rule 4 | Old Rule 7 |
| Rule 5 | Old Rule 12 |
| Rule 6 | Old Rule 13 |
| Rule 7 | Old Rule 14 |
| Rule 8 | Old Rule 15 + Rule 18 + Rule 19 (CI plan → DF-46) |
| Rule 9 | Old Rule 16 |
| Rule 10 | Old Rule 17 (with old Rule 8 HTTP table as narrow-trigger) |

---

## Production Integrity (P3)

No Mock implementations in production. Using mocks to bypass real failures is **strictly forbidden**.

| Rule | Detail |
|------|--------|
| No mock bypass | Do not use Mock/Stub/Fake to conceal missing components or broken wiring. |
| Tests reflect reality | A passing test must mean the real path works. |
| Missing = exposed | Unimplemented dependencies → `skip`/`xfail`, never faked. |
| Legitimate mock uses | (1) external HTTP calls in unit tests; (2) fault injection; (3) performance benchmarks. Document reason in docstring. |
| Zero mocks in integration | Integration and E2E tests use real components only. |

---

## Quick Start

```bash
python -m hi_agent run --goal "Analyze quarterly revenue data" --local
python -m hi_agent serve --port 8080
python -m hi_agent resume --checkpoint .checkpoint/checkpoint_run-001.json
python -m pytest tests/ -v
python -m ruff check .
```
