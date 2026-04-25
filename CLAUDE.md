# CLAUDE.md

## Language Rule

**Translate all instructions into English before any model call.** Never pass Chinese, Japanese, or other non-English text into an LLM prompt, tool argument, or task goal.

---

## Project Status

**Active implementation — production engineering phase.** Full design baseline at `architecture-review/`.

Architecture reference → `docs/architecture-reference.md`

---

## AI Engineering Rules

**Thirteen rules.** Rules 1–4 are daily-use engineering principles. Rules 5–7 are class-level patterns triggered by resource type. Rules 8–10 are delivery gates. Rules 11–13 are platform-contract standards. All rules override default habits; CLAUDE.md overrides everything except explicit user instructions.

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

**Parallel-dispatch:** second agent to commit must rebase — never `git reset --soft` (silently absorbs other agent's work). Commits spanning >1 defect ID or >2 distinct modules must be split. See `docs/rules-incident-log.md` (DF-45 incident).

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

**Smoke + lint** — required before commits touching `hi_agent/server/`, `hi_agent/runtime_adapter/`, `agent_kernel/service/`, or any `__init__.py`. Enforced by `scripts/check_rules.py`: ruff clean + import clean + `/health` returns 200 in 3 s.

---

### Rule 4 — Three-Layer Testing, With Honest Assertions

A feature is implementable only when all three layers are designed. A feature is shippable only when all three are green **and** Rule 8 passes.

- **Layer 1 — Unit**: one function per test; mock only external network or fault injection, with reason in docstring.
- **Layer 2 — Integration**: real components wired together. **Zero mocks on the subsystem under test.** Skip with `@pytest.mark.skip(reason="awaiting real implementation")` if a dependency is absent — never fake it.
- **Layer 3 — E2E**: drive through the public interface (HTTP / CLI / top-level API); assert on observable outputs, not internal variables.

**Test honesty is not optional**: MagicMocking the subsystem under test in integration = mislabeled unit test; accepting any terminal status = documentation, not a test; a test that passes when the subject raises = a lie.

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

`asyncio.run(` site check enforced by `scripts/check_rules.py` — every match must be in an entry point (`__main__`, CLI, test) or routed through `sync_bridge`.

---

### Rule 6 — Single Construction Path Per Resource Class

**For every shared-state resource, exactly one builder function owns construction. All consumers receive the instance by dependency injection. Inline fallbacks of the shape `x or DefaultX()` are forbidden.**

When a class needs profile/workspace/project scoping, scope is a **required constructor argument**, not an optional kwarg with a default. Missing scope must be a hard error, not a silent fresh unscoped instance.

**Forbidden:** `x or DefaultX()` fallback; optional scope kwargs with defaults. **Required:** scope as required kwarg; raises `ValueError` if missing. Inline-fallback check enforced by `scripts/check_rules.py` — every match is a defect candidate.

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
3. **Sequential real-LLM runs (N≥3)** — three back-to-back `POST /runs`, each: reaches `state=done` in ≤ `2 × observed_p95`; `llm_fallback_count == 0`; emits ≥1 LLM request in access log + metric.
4. **Cross-loop resource stability** — runs 2 and 3 reuse the same gateway/adapter instance as run 1 (Rule 5 stress test). No `Event loop is closed`, no `ConnectTimeout` on call ≥2.
5. **Lifecycle observability** — each run reports a non-`None` `current_stage` within 30 s; `finished_at` populated on terminal. `current_stage==None` for >60 s on a non-terminal run is a FAIL.
6. **Cancellation round-trip** — `POST /runs/{id}/cancel` on a live run → 200 + drives terminal; on unknown id → 404, not 200.

All six hold. Any FAIL blocks ship. The artifact owner records the gate run in `docs/delivery/<date>-<sha>.md`. Unrecorded ≠ passed.

**T3 Invariance** — a gate pass is valid only for the SHA at which it was recorded. Any subsequent commit touching hot-path files invalidates T3 until a fresh gate run is recorded.

Hot-path files: `hi_agent/llm/**`, `hi_agent/runtime/**`, `hi_agent/config/cognition_builder.py`, `hi_agent/config/json_config_loader.py`, `hi_agent/config/builder.py`, `hi_agent/runner.py`, `hi_agent/runner_stage.py`, `hi_agent/runtime_adapter/**`, `hi_agent/memory/compressor.py`, `hi_agent/server/app.py`, `hi_agent/profiles/**`

Hot-path PR descriptions must include `T3 evidence: docs/delivery/<date>-<sha>-rule15-volces.json` or `T3 evidence: DEFERRED — <reason>`. T1/T2 passing does NOT preserve T3.

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

**Forbidden:** any phrasing that ships with open ship-blocking findings ("H-level open, shipping this version", "follow-up PR", "architectural debt, safe to ship"). If leadership accepts the risk: reclassify as **Known-Defect Notice**, signed by name, acknowledged in writing by downstream, user-visible symptoms spelled out per defect.

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

### Rule 11 — Posture-Aware Defaults

**Every config knob, fallback path, and persistence backend declares its default behaviour under three postures: `dev` / `research` / `prod`.**

- `dev` may be permissive: missing scope emits warnings, in-memory backends allowed, schema validation warns and skips.
- `research` and `prod` default to fail-closed: required scope must be present, persistence must be durable, schemas must be validated, fallbacks must emit metrics.

The posture is set by `HI_AGENT_POSTURE={dev,research,prod}` (default `dev`); `Posture` lives in `hi_agent/config/posture.py`. Use `Posture.from_env()` at call sites — never hard-code the posture.

Tests must cover at least `dev` and `research` paths for any new contract.

**Enforcement:** every new `if posture.is_strict` branch gets a test for both dev-allow and research-reject.

---

### Rule 12 — Contract Spine Completeness

**Every persistent record (run, idempotency, artifact, gate, trace, memory write, KG node, team event, feedback, evolution proposal) must explicitly carry at minimum `tenant_id`, plus the relevant subset of `{user_id, session_id, team_space_id, project_id, profile_id, run_id, parent_run_id, phase_id, attempt_id, capability_name}`.**

A record that cannot answer "which tenant / project / profile / run / phase / capability does this belong to" cannot enter the research/prod default path.

**Pre-commit check:** any new dataclass under `hi_agent/contracts/`, `hi_agent/artifacts/`, `hi_agent/server/{run_store,idempotency,team_run_registry,event_store,gate_*}` must declare a `tenant_id` field unless explicitly marked `# scope: process-internal` with reason.

---

### Rule 13 — Capability Maturity Model

**Status reporting uses L0–L4, not "implemented" or ad-hoc labels.**

| Level | Name | Criterion |
|---|---|---|
| L0 | demo code | happy path only, no stable contract |
| L1 | tested component | unit/integration tests exist, not default path |
| L2 | public contract | schema/API/state machine stable, docs + tests full |
| L3 | production default | research/prod default-on, migration + observability |
| L4 | ecosystem ready | third-party can register/extend/upgrade/rollback without source |

Delivery notices report L-level per capability with evidence (commit SHA + test file + manifest field + posture coverage). Legacy labels (`experimental`=L1, `implemented_unstable`=L1, `public_contract`=L2, `production_ready`=L3) are retired after Wave 9.

A capability cannot move to L3 without: (a) posture-aware default-on, (b) quarantined failure modes, (c) observable fallbacks per Rule 7, (d) doctor-check coverage.

---

## Ownership Tracks

Every PR identifies its primary owner track in the commit body (`Owner: CO|RO|DX|TE|GOV`). A PR touching files outside its owner track requires co-owner approval or a GOV-track exception note.

| Track | Owns | Key file globs | Rule |
|---|---|---|---|
| **CO** | API/artifact/capability/profile schemas, posture concept | `hi_agent/contracts/**`, `artifacts/contracts.py`, `capability/registry.py`, `config/posture.py`, `profiles/schema.json`, `agent_kernel/kernel/contracts.py` | Any public-dataclass/schema/descriptor/posture change = CO; include contract-version bump + migration note. |
| **RO** | Execution, state machines, persistence boundaries | `server/run_*.py`, `idempotency.py`, `team_run_registry.py`, `event_*.py`, `runtime/**`, `runtime_adapter/**`, `gate_protocol.py`, `agent_kernel/runtime/**`, `agent_kernel/kernel/{turn_engine,reasoning_loop,...}`, `agent_kernel/kernel/{task_manager,persistence,recovery}/**` | In-memory state under research/prod = defect. Durable-store changes require restart-survival test. |
| **DX** | Developer journey: first contact → upgrade | `__main__.py`, `cli.py`, `cli_commands/**`, `ops/{doctor_report,diagnostics}.py`, `server/routes_manifest.py`, `config/{validator,readiness,builder,...,watcher}.py`, `examples/**`, `docs/quickstart*.md`, `docs/posture-reference.md`, `docs/api-reference.md` | No L2 without documented quickstart path, doctor-check coverage, and structured error category in `/runs`. |
| **TE** | Artifacts, evidence, provenance, evolution | `artifacts/{registry,adapters,confidence,ledger}.py`, `routes_artifacts.py`, `trace/**`, `observability/**`, `evolve/**`, `skill/{evolver,observer,recorder}.py`, `ops/release_gate.py`, `agent_kernel/kernel/{event_export,failure_evidence,failure_mappings}.py` | Every silent-degradation path: Countable + Attributable + Inspectable + Gate-asserted. ArtifactLedger corruption never silently skipped. |
| **GOV** | CLAUDE.md, capability matrix, CI, delivery | `CLAUDE.md`, `docs/platform-capability-matrix.md`, `docs/TODO.md`, `docs/downstream-responses/**`, `.github/workflows/**`, `scripts/check_*.py`, `docs/delivery/**` | Capability matrix = single source of truth. Delivery notice, TODO, matrix agree at every push to main. |

---

## Operational Appendix

### Narrow-Trigger Rules

These apply only when the stated condition is true. Full detail and incident records → `docs/rules-incident-log.md#narrow-rules`.

| Condition | Required action |
|-----------|-----------------|
| Changing `agent_kernel/service/http_server.py` or `kernel_facade_client.py` | PR must include side-by-side client↔server path/method table; every row ✅ before merge. |
| Adding/modifying CI `if: ${{ env.X_API_KEY != '' }}` | Grep consumers first; every `\|\|` clause must have a matching read in the fixture. |
| Adding latency assertions against a real LLM in CI | Only advisory (`continue-on-error: true`), ≥3× p95 headroom, or trend-not-point. Never a fixed second-count. |

### Three-Gate Demand Intake

Before accepting any new capability request into hi-agent:

**G1 — Positioning gate**: capability-layer only (runtime, memory, LLM routing, observability, contract); business-layer → decline and redirect to research team.

**G2 — Abstraction gate**: composable from existing capabilities without new code → provide a composition example, no new code.

**G3 — Verification gate**: new code requires a Rule 4 three-layer test plan AND a Rule 8 gate run plan before delivery authorization.

**G4 — Posture & Spine gate**: declare (a) default behaviour under `dev`/`research`/`prod` postures and (b) which contract-spine fields it carries; otherwise stays at L0–L1 and cannot enter research/prod default path.

Rule origin history (R1–R13) → `docs/rules-incident-log.md`.
