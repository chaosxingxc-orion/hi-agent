# hi-agent Wave 34 Engineering Expectations

**Date:** 2026-05-04
**From:** Research Intelligence Application (RIA) team — downstream platform consumer
**To:** hi-agent upstream engineering team
**Status:** Engineering expectations directive (M1 — internally reviewed; binding for Wave 34 entry on the items marked **BLOCKER**; advisory on the items marked **expectation**)
**Position:** Successor to `hi-agent-wave31-blocker-closure-requirements-2026-05-02.md`. Carries forward the three W34 items hi-agent themselves placed in carryover at Wave 33 close, plus four additional engineering expectations driven by RIA's positioning of the platform.

**Companion documents on the RIA side (informational, not binding on you, but explain why we are asking):**
- `docs/ria/ria-architecture-v1.md` (live) and `docs/ria/ria-architecture-v2.md` (forthcoming this wave on our side)
- `docs/ria/ria-domain-model-v1.md` (will revise to v1.1 this wave)
- `docs/ria/ria-platform-contract-mapping-v1.md` (will revise to v1.1 this wave)
- `docs/ria/ria-quality-requirements-v1.md` (will revise to v1.1 this wave)

---

## 0. Standing on Wave 33

We have read your Wave 33 delivery notice (`docs/downstream-responses/2026-05-04-w33-delivery-notice.md`, 2026-05-04, manifest `2026-05-03-ce9330fa`). We acknowledge:

| W33 closure | Track | Evidence we cross-checked |
|---|---|---|
| Recurrence-ledger 31→32 (RIA §5 drift #1) | W33-A.1 | `docs/governance/recurrence-ledger.yaml:9` + `scripts/check_wave_consistency.py --json` exit 0 |
| Capability-matrix headlines (RIA §5 drift #2) | W33-A.2 | `docs/platform-capability-matrix.md` lines 3, 355 + `check_doc_truth.py` exit 0 |
| Signal route preemptive coverage (RIA §7 hook (d)) | W33-B.1 | `tests/integration/test_v1_runs_signal_resume_real_kernel.py` (2 tests; real RunManager) |
| `agent_server` lifespan W32-C reforms reach prod | W33-C.1 | `agent_server/runtime/lifespan.py` rewrite + `tests/integration/test_agent_server_w32c_lifespan_active.py` |
| SIGTERM graceful drain | W33-C.2 | `hi_agent/server/app.py:_sigterm_handler` + 3-test integration suite |
| `RunQueue.reenqueue` clears `adoption_token` | W33-C.3 | `hi_agent/server/run_queue.py` + `tests/unit/test_run_queue.py::test_reenqueue_clears_adoption_token_for_second_recovery` |
| JWT auth middleware on v1 routes | W33-C.4 | `agent_server/api/middleware/auth.py` + `agent_server/runtime/auth_seam.py` + 6-test integration suite |
| SSE `iter_events` live-stream | W33-C.5 | `agent_server/runtime/kernel_adapter.py` + `tests/integration/test_v1_runs_sse_live_stream.py` (2 tests) |
| Audit log `tenant_id` (D.1) | W33-D.1 | `hi_agent/observability/audit.py` + 11 tests |
| RunQueue defense-in-depth tenant scoping (9 methods, 28 tests) | W33-D.2 | `hi_agent/server/run_queue.py` + `tests/integration/test_run_queue_tenant_defense_in_depth.py` |
| Rule 11 `HI_AGENT_ENV` unification | W33-E.1 | `hi_agent/config/posture.py:resolve_runtime_mode()` + 19 callsites + `scripts/check_no_hi_agent_env_direct_read.py` + 20 tests |
| Rule 12 spine lineage fields | W33-F.1 | `hi_agent/server/event_store.py:StoredEvent` + `hi_agent/server/run_store.py:RunRecord` + `tests/unit/test_spine_lineage_fields.py` (10 tests) |
| Real T3 (Volces) at HEAD | — | `docs/delivery/2026-05-04-65cdbbc0-t3-volces.json` `provenance:real`, 3/3 PASS |
| arch-7×24 fresh evidence | — | `docs/verification/ac37383-arch-7x24.json` 5/5 PASS |
| Clean-env fresh evidence | — | `docs/verification/ac37383b-default-offline-clean-env.json` 9256 passed / 8 skipped / 0 failed |

**Quality of the W33 work.** Wave 33 is the strongest single-wave delivery we have audited. The two soft drifts we surfaced in W32 acceptance §5 (recurrence-ledger lag, capability-matrix headlines) were closed inline; the §7 preemptive coverage ask was honoured; the 13 hidden BLOCKER/HIGH findings your own systematic audit produced were all closed against measured evidence at the release HEAD `ce9330fa`. Five of those findings (lifespan-reaches-prod, SIGTERM drain, JWT outermost, SSE true-stream, RunQueue.reenqueue) directly improve the failure modes RIA exercises in long-running PI Agent runs.

**Architectural-positioning self-assessment.** Your W33 §"Architectural-positioning rationale" lists four positioning lenses (performance stability, northbound idempotency / extensibility, evolvability, configurable development / sustainable evolution). RIA holds a more granular eight-lens view (§2 below); your four map onto four of ours (performance stability → reliability; idempotency / extensibility → functional idempotency; evolvability → continuous intelligence evolution; configurable / sustainable → configurable development). The remaining four RIA lenses (tenant isolation, high concurrency, 7×24 long-running, agent service to upper systems) are not surfaced as headlines in your W33 self-assessment — not because you have ignored them, but because the relevant work is spread across multiple W33 tracks (W33-D.1 / D.2 for tenant; arch-7×24 for long-running; W33-C.4 / C.5 for agent service; nothing yet for high concurrency). We use this directive to make all eight explicit and to anchor what we still expect.

**Cap factors.** `verified_readiness=75.0` is held by `soak_evidence_not_real` (waived per RIA's W32 acceptance §2 architectural-feasibility 7×24 criterion) and `evidence_provenance` (3 historical W27 artifacts; W28 erratum). We accept both cap factors as correctly measured at the W33 HEAD. **We are not asking you to retire either cap factor in W34.**

**Two-seam pattern.** We endorse, again, the W32 `agent_server/runtime/RealKernelBackend` and the W33 `agent_server/runtime/auth_seam` as the right second-seam pattern. The pattern is now mature enough that we are mirroring it on the RIA side this wave (see §5 below — the new `ria/external_services/` boundary is the structural twin of your `agent_server/runtime/`).

---

## 1. Engineering Discipline (Standing Reminder)

These three rules are not negotiable. Each is a CLAUDE.md-level invariant that we hold to ourselves and that we carry into the corrective directives we send you.

### 1.1 No mock-based filtering as stub limitation

> **Statement.** When a test passes against a stub (or a mock, or a fake) but the corresponding behaviour breaks against the real component, that is a defect in the production component, not a "stub limitation" or a "mock gap" or a "boundary that the stub does not cover". The defect must be fixed in the production component. The stub may then be tightened to match.

**Rationale.** This rule exists because RIA observed, in 2026-04 / 2026-05, repeated cycles of the form: hi-agent claims "test pass against stub kernel"; RIA wires real `agent_server` and the same surface fails; rework consumes a wave. The recovery protocol from `engineering-readiness-scorecard-2026-04-26-wave10.md` and the W31 directive both flagged this. We name it again because RIA's Phase 3 going real this wave (see §5) will produce a continuous stream of evidence of the form "passed in stub, fails on `ce9330fa`-or-newer". Each such finding is a defect in your codebase, not in our test discipline.

**Concrete consequence for W34.** When RIA's `tests/integration/` against your real `agent-server serve` produces a red, we will publish the failure shape under `docs/ria/red-status/<head>.json` (machine-readable; one row per failing test with `blocked_by` annotation pointing at the suspected platform gap). We do not expect you to mock the failure away; we expect the production code to change.

### 1.2 Naming / structure accretion is a defect

> **Statement.** A naming pair like `skill/skills`, `profile/profiles`, `state/state_machine`, `failures/errors`, `ops/operations`, an empty `__init__.py` advertised by `ARCHITECTURE.md`, or a top-level subpackage that exists only to satisfy a diagram — each is a defect. It is closed by either renaming-and-consolidation or by a deliberate `# stub-reason: <reason+wave>` annotation. It is not closed by leaving it open across waves.

**Rationale.** W31 §B-6 established this as a binding rule. W31-H1, W31-H2, W31-H3 closed it for the W30 baseline. W33 carries three new candidates (H-3' / H-13' / H-14') as "RIA discretion items". We do not accept "RIA discretion" as a permanent disposition — see §4 below.

### 1.3 Defect-vs-limitation discipline (three-part closure)

> **Statement.** When a defect is found in any artifact (code, doc, evidence file, test), closure requires three parts: (a) fix in the artifact; (b) a check that prevents recurrence (CI gate, checklist line, audit row); (c) the process change recorded in CLAUDE.md or the relevant skill / spec file. Missing any one part = defect remains OPEN.

**Forbidden moves** (carried verbatim from CLAUDE.md):

- Reclassify an open defect as "design intent" or "future work."
- Inflate a score by retiring a cap without producing the missing evidence.
- Mark a closure "complete" because the test was added to the codebase but is `pytest.mark.skip`-ed or `pytest.mark.xfail`-ed without `expiry_wave`.

We mention this rule again because two of the W34 BLOCKERs below (B-W34-1, B-W34-2) are precisely the kind of fix that, in a less disciplined environment, would tempt a "carry to W35" disposition. We do not accept that disposition. F.2 / F.3 / F.4 are defects by your team's own classification (carried in W33 §"Outstanding Items" without re-labelling); the only correct closure path is the three-part sequence.

---

## 2. Cross-Layer Positioning — Eight Lenses

This is RIA's authoritative statement of how we evaluate the platform's fitness for our use. It is binding for the way we score W33 and frame W34. You are welcome to disagree with the framing; if you do, raise it in your W33 acceptance response and we will negotiate an explicit revision.

The eight lenses, in priority order:

| # | Lens | Source of priority |
|---|---|---|
| 1 | Tenant isolation (policy provided by upper systems, enforced by platform) | RIA serves multiple research orgs; cross-tenant leakage is an unconditional non-starter |
| 2 | Functional idempotency | RIA process restart, user retry, SSE reconnect — all must be safe-by-default |
| 3 | High reliability | PI Agent runs are weeks long; one fault must not lose a week's work |
| 4 | High concurrency | Per-org research load is bursty; hundreds of concurrent run-starts during a deadline week |
| 5 | Configurable development | New skill, new profile, new tier without a redeploy |
| 6 | Continuous intelligence evolution | Postmortem → skill A/B → champion-challenger feeds back without human-in-the-loop unless gated |
| 7 | Long-running 7×24 capability | PI Agent runs span weeks; platform must run unattended for that span |
| 8 | Agent service to upper systems | The platform is consumed by RIA (and future apps) over the v1 contract; the contract is the product |

For each lens we state: (a) what W33 closed; (b) what residual gap RIA can see; (c) what we expect in W34.

---

### 2.1 Tenant Isolation

**W33 closures (concrete).**
- Audit log carries `tenant_id` end-to-end (W33-D.1, 11 tests in `tests/unit/test_audit_tenant_id.py`).
- `RunQueue` defense-in-depth: 9 methods scope by `tenant_id`, 28 integration tests in `tests/integration/test_run_queue_tenant_defense_in_depth.py`.
- `RunRecord` and `StoredEvent` carry spine lineage including `tenant_id` (W33-F.1).
- `TenantContextMiddleware` continues to be the second outermost middleware after JWT (W33-C.4).

**Residual gap.**
- **F.4 — `KnowledgeWiki` tenant partition not closed.** Listed in W33 §"Outstanding Items" as W34 carryover with note "Per-tenant key composition". The current `KnowledgeWiki` shape is not partitioned per-tenant; cross-tenant reads at the KG layer are not structurally denied — they are merely unobserved.
- **B-5 status — uncertain.** W31 §B-5 requested `tenant_id NOT NULL` on the persistent schema for KG / skill / tool / capability registry, with `xfail` tests flipping to pass under `prod` posture. W33 closed `RunQueue` (9 methods), but B-5's original four registries (KG, skill, tool, capability) are not enumerated as closed. We need explicit confirmation of which of the four are closed at HEAD `ce9330fa`, which remain open, and (if open) why they are not on the W34 carryover list.
- **No cross-tenant probe coverage at the `agent_server` boundary.** The 28 RunQueue tests are unit-level on the kernel store. There is no integration test of the form "tenant A submits a run, tenant B issues `GET /v1/runs/{id}` with B's `X-Tenant-ID` header, expects 404 (not 403, not 200, not the run body)" for the full set of scoped routes (`/v1/runs/*`, `/v1/artifacts/*`, `/v1/gates/*`, `/v1/skills/*`, `/v1/memory/*`, `/v1/manifest`).

**W34 expectation — see B-W34-3 (BLOCKER) and B-W34-4 (BLOCKER).**

---

### 2.2 Functional Idempotency

**W33 closures (concrete).**
- `IdempotencyMiddleware` is registered third in the production middleware chain (`JWTAuthMiddleware → TenantContextMiddleware → IdempotencyMiddleware`). The W33 `test_middleware_pipeline_no_extraneous_layers` regression test pins this chain.
- `idempotency_facade.py` continues to back the middleware via `hi_agent/server/idempotency.py`.
- Replay semantics for repeated `(tenant_id, key, body)` are documented in `agent_server/api/middleware/idempotency.py` docstring.

**Residual gap.**
- **Cross-process replay correctness is not explicitly tested.** The current tests cover (a) identical request twice → cached response, (b) same key + different body → 409. They do not cover: (c) request lands on platform, platform restarts before responding, RIA retries — does the platform return the cached result of the original execution, or does the original execution effectively never complete? (d) Two different platform processes (HA configuration, future) — do they share idempotency state, or is replay only intra-process? (e) Idempotency record TTL — is there one, and what is RIA's contract about retry beyond TTL?
- **Replay semantics not in `agent_server/contracts/v1/`.** The replay rules are documented in middleware docstring; they should be elevated to a contracts-level document so RIA's `platform_client/idempotency.py` can compile against a stable spec.

**W34 expectation — see B-W34-5 (BLOCKER).**

---

### 2.3 High Reliability

**W33 closures (concrete).**
- W33-C.1 `_lease_expiry_loop` and `_current_stage_watchdog` are kicked off as asyncio tasks during agent_server FastAPI lifespan startup, cancelled cleanly on shutdown — and these now run on the production deployment shape (RIA's actual surface), not just legacy `python -m hi_agent serve`.
- W33-C.2 `_sigterm_handler` provides graceful drain instead of 2-second force-fail.
- W33-C.3 `RunQueue.reenqueue` clears `adoption_token` so runs survive arbitrary lease cycles.

**Residual gap.**
- **F.2 — `RunExecutionContext.from_managed_run` hardcodes lineage as empty.** Per W33 §"Outstanding Items": `parent_run_id`, `attempt_id`, etc. are hardcoded as empty strings. Any reconstruction of a run's parent / attempt tree from the persisted context returns empty — meaning the lineage data is structurally present (W33-F.1) but the executor-side population path is not wired.
- **F.3 — `ReasoningTrace.__post_init__` spine validation missing.** Per W33 §"Outstanding Items": dataclass invariant check absent. A `ReasoningTrace` constructed with empty / null spine fields silently succeeds, defeating Rule 12.
- **No documented post-mortem reconstruction test.** Long-running reliability includes the property "after a fault, the operator can reconstruct what happened from persisted state alone." We do not see an integration test of the form: "kill the process mid-stage; restart; confirm the recovered run's `parent_run_id`, `attempt_id`, `phase_id` chain matches what was active pre-kill."

**W34 expectation — see B-W34-1 and B-W34-2 (BLOCKERs).**

---

### 2.4 High Concurrency

**W33 closures (concrete).**
- The async-first core (per ARCHITECTURE.md Constraint "asyncio.run outside entry points forbidden; sync callers use sync_bridge") provides the substrate.
- `RunQueue` with lease semantics provides per-run isolation under concurrent worker pickup.
- W33-D.2 RunQueue defense-in-depth ensures concurrent multi-tenant access does not cross-leak at the queue level.

**Residual gap.**
- **No published benchmark methodology and no first-baseline number.** "High concurrency" appears in your W30 / W31 / W32 / W33 self-narratives but no `docs/verification/<head>-concurrency-<N>.json` artifact exists with `provenance: real` for `N ∈ {1, 10, 50, 100}` concurrent run-starts. Without a baseline, the platform's high-concurrency claim is unverified (Dimension 4 in our 8-lens scoring stays at "claimed but not measured").
- **SQLite write contention under concurrent run-starts is unknown.** SQLite is the default persistence (per your ARCHITECTURE.md §2 Constraint). Under 100 concurrent `POST /v1/runs`, the write lock behaviour is undocumented. The optional `asyncpg` PostgreSQL adapter exists but we do not see an equivalence test ("same workload, SQLite vs PostgreSQL, both produce same terminal state distribution").
- **No regression budget.** Even with a baseline number, the absence of a per-wave regression budget (e.g., "P95 run-start latency at N=50 must not exceed last wave's P95 by more than 10%") means a future refactor can silently degrade concurrency.

**W34 expectation — see B-W34-7 (BLOCKER) and §6 Acceptance Criteria.**

---

### 2.5 Configurable Development

**W33 closures (concrete).**
- W33-E.1 `Posture.resolve_runtime_mode()` is the single read-site for `HI_AGENT_ENV`; `scripts/check_no_hi_agent_env_direct_read.py` enforces zero direct reads outside that function. 19 callsites updated. 20 tests cover the edge cases.
- Profile config bundles continue to be the configuration unit for declarative skill/route assembly.
- `SkillSpec` registration via `POST /v1/skills` continues to allow runtime skill definition without redeploy.

**Residual gap.**
- **Other env vars are not unified through `Posture` or any equivalent.** W33 closed exactly one env var (`HI_AGENT_ENV`). Per the runtime-modes table in your ARCHITECTURE.md §7, `HI_AGENT_LLM_MODE`, `OPENAI_API_KEY`, `HI_AGENT_KERNEL_BASE_URL` are still separately consumed; the audit gate (`check_no_hi_agent_env_direct_read.py`) covers only `HI_AGENT_ENV`. We do not have evidence about whether other env vars have direct reads scattered across the codebase.
- **No global config schema validator.** Profile JSON, `llm_config.json`, `tools.json` are loaded by ad-hoc parsers. There is no JSON-schema-or-equivalent validator that fails-fast on missing / typo'd fields at startup.
- **Configuration drift between env and in-process state is not detected.** If `HI_AGENT_POSTURE` is changed in env but the running process is not restarted, no warning is emitted.

**W34 expectation — see Acceptance Criterion §6 row "configurable-development env-var enumeration".**

---

### 2.6 Continuous Intelligence Evolution

**W33 closures (concrete).**
- `RunEventEmitter` exposes 12 typed `record_*` methods; `spine_events` are emitted with structured fields.
- `evolve/` package contains `PostmortemEngine`, `ExperimentStore`, `ChampionChallenger` per ARCHITECTURE.md §5 building block view.
- `SkillEvolver` exists in `hi_agent/skill/`.

**Residual gap.**
- **F.2 / F.3 lineage gaps undermine post-mortem reconstruction.** Without `parent_run_id` / `attempt_id` / `phase_id` populated correctly (currently empty per F.2; not validated per F.3), `PostmortemEngine` cannot reconstruct an attempt tree across replans. Any cross-attempt postmortem is grounded on partial data.
- **`SkillEvolver` A/B wiring into the prod path is not verified.** We see the class exists; we do not see an integration test that demonstrates: "Champion skill version v1 produces N runs; Challenger version v2 produces N runs; ChampionChallenger compares signal; output is observable through `/v1/skills/{id}/versions`." If such a test exists, please cite the path; if not, the wiring should be verified before W34 closes.
- **Cross-project skill / route delta retrieval is not exposed.** RIA's Phase 3 `evolution_engine` will need to read "all skills used in `tenant_X` projects in the last 30 days" and "all route changes in `tenant_X` skills in the last 30 days". The `agent_server` v1 contract does not currently expose a route for either query (cross-project reads at the skill / route delta layer).

**W34 expectation — see B-W34-1, B-W34-2 (which transitively close the postmortem gap), and §6 Acceptance Criteria row "evolution wiring observable".**

---

### 2.7 Long-Running 7×24

**W33 closures (concrete).**
- `architectural_seven_by_twenty_four` is 5/5 PASS at HEAD `ac37383`; `seven_by_24_operational_readiness=90.0`.
- `tier 7×24` cap factor was waived in RIA's W32 acceptance §2 per the architectural-feasibility criterion. We continue to honour that waiver.

**Residual gap (advisory, not blocker).**
- **No Linux-runner soak roadmap is stated.** Two of the ten chaos scenarios still skip on Windows (architecturally coupled, OS-limited). RIA's W32 acceptance accepted this as a measurement-environment limitation, not a defect. We would still like to see a roadmap entry: "When does a Linux-runner soak with the 2 OS-limited scenarios become available, and at what duration / workload? The roadmap entry is not blocking for W34; it is a planning input for our Phase 3 release timeline.
- **The "architectural-feasibility" waiver should not be permanent.** We accept it for W34 (and likely W35); we expect the W36 directive will revisit it. This is signal-only; nothing in W34 turns on it.

**W34 expectation — advisory; one paragraph in your W34 delivery notice describing the Linux-runner soak roadmap is sufficient.**

---

### 2.8 Agent Service to Upper Systems

**W33 closures (concrete).**
- `agent_server` v1 contract digest-frozen at SHA `8c6e22f1` (per ARCHITECTURE.md §9 ADR).
- JWT validation is the outermost middleware in production (W33-C.4). 6 integration tests cover missing / valid / invalid-sig / expired / dev-passthrough / exempt-path.
- SSE `iter_events` is a true live-stream (W33-C.5). Snapshot-and-close was retired.
- `/v1/manifest`, `/v1/health`, `/v1/ready`, `/v1/diagnostics`, `/v1/metrics` endpoints documented in ARCHITECTURE.md §7.

**Residual gap.**
- **`/v1/manifest` posture exposure is not spec'd.** RIA's R-RIA-6 boundary rule (per `ria-quality-requirements-v1.md` §1) requires RIA to refuse to start in `prod` posture against a `dev`-posture platform. This requires `GET /v1/manifest` to return the platform's posture in a stable, contract-spec'd field. The manifest endpoint exists; the posture field's name, type, and presence guarantee are not spec'd in `agent_server/contracts/v1/manifest.py` (or equivalent). RIA cannot rely on a field whose name and presence are not contract-frozen.
- **Capability discoverability for cross-project queries is missing.** When RIA's Phase 3 needs to discover whether the platform exposes cross-project skill / KG queries, the manifest is the natural discovery point. Currently it returns runtime / capability info; it does not enumerate the v1 read routes a consumer can call.
- **Conformance suite for downstream consumption is not published.** A consumer-side conformance suite ("the platform implements these N route shapes with these N error envelopes") does not exist. RIA will write one this wave (per `ria-quality-requirements-v1.md` §3 G-RIA-16); we would benefit from your team contributing test cassettes for the canonical cases so our conformance suite tracks your contract intent, not our reverse-engineered interpretation.

**W34 expectation — see B-W34-6 (BLOCKER); cassette contribution is advisory.**

---

## 3. Wave 34 Blocker Inventory (B-W34-1 through B-W34-7)

These are the binding W34 entry blockers. Each is stated with: (a) class, (b) evidence, (c) why it blocks downstream consumption, (d) acceptance criteria for closure.

The first three (B-W34-1, B-W34-2, B-W34-3) are the items hi-agent themselves placed in W33 carryover. We are escalating them from "carryover" to "W34 BLOCKER" because RIA's Phase 3 Going Real (§5) means our own integration tests at HEAD `ce9330fa` will surface them as red within days. The remaining four (B-W34-4 through B-W34-7) are engineering expectations RIA is making explicit for the first time.

---

### B-W34-1 — `RunExecutionContext.from_managed_run` lineage fields populated

**Class:** Reliability / Spine completeness / Dimension R + Dimension E
**Severity:** BLOCKER (escalated from W33 carryover F.2)

**Evidence:**
- W33 delivery notice §"Outstanding Items" line: "F.2 RunExecutionContext spine fields | RO | W34 carryover | from_managed_run hardcodes parent_run_id, attempt_id, etc. as empty".
- W33-F.1 closed the *storage-side* spine (StoredEvent + RunRecord carry the fields); the *executor-side* population (`from_managed_run`) does not.
- Net effect: the platform persists empty strings for `parent_run_id`, `attempt_id`, `phase_id` on records that should carry real values.

**Why it blocks downstream consumption:**
RIA's Phase 3 `evolution_engine` (going real this wave per A.3.α — see §5) reconstructs cross-attempt postmortems by reading `(parent_run_id, attempt_id, phase_id)` chains from persisted run records. With empty strings on the executor side, reconstruction returns disconnected nodes — the postmortem cannot identify which retry was "the same run, second attempt" vs "a separate run". Champion-Challenger comparison degrades to noise. Continuous evolution (Dimension 6) cannot function at correct fidelity.

This is not a future-Phase concern; it is current. RIA's `tests/integration/test_evolution_engine_attempt_tree_reconstruction.py` (forthcoming this wave on our side) will assert: for a run with two recovery cycles, the persisted records expose a connected `(run, attempt) → (run, attempt) → (run, attempt)` chain. With F.2 unclosed, this test is red.

**Acceptance criteria for closure (W34-F.2):**
1. `hi_agent/server/run_executor.py::RunExecutionContext.from_managed_run` (or wherever the construction happens; cite the actual path in your closure notice) populates `parent_run_id`, `attempt_id`, `phase_id` from the `ManagedRun` it adapts.
2. New unit test `tests/unit/test_run_execution_context_lineage_population.py`:
   - Construct `ManagedRun` with non-empty lineage fields.
   - Call `from_managed_run`.
   - Assert resulting context has the same lineage values (not empty strings).
3. New integration test `tests/integration/test_run_lineage_persisted_after_recovery.py`:
   - Start a run; let it reach S2; SIGTERM the worker.
   - Restart the kernel; let the run be re-leased and continue.
   - Read the persisted `RunRecord` and `StoredEvent` rows.
   - Assert: original `attempt_id=A1`, post-recovery `attempt_id=A2`, both rows reference the same `run_id`, and `parent_run_id` linkage is intact.
4. Three-part closure (Rule 15): (a) fix in `run_executor.py`; (b) `scripts/check_lineage_population.py` AST-walks every construction site of `RunExecutionContext` and fails if any pass empty strings to `parent_run_id` / `attempt_id`; (c) record the fix-and-gate in CLAUDE.md or `hi_agent/ARCHITECTURE.md` §"Spine completeness".

---

### B-W34-2 — `ReasoningTrace.__post_init__` spine validation present

**Class:** Reliability / Spine completeness / Dimension R + Dimension E
**Severity:** BLOCKER (escalated from W33 carryover F.3)

**Evidence:**
- W33 delivery notice §"Outstanding Items" line: "F.3 ReasoningTrace __post_init__ | CO | W34 carryover | Spine validation missing".
- The Rule 12 spine fields (`tenant_id`, `parent_run_id`, `attempt_id`, `phase_id`) are required on persistent records, but `ReasoningTrace` constructions can complete with empty / null values without raising.

**Why it blocks downstream consumption:**
A spine field that is structurally required but not programmatically validated is a contract that exists on paper only. RIA's `tests/integration/test_evolution_engine_attempt_tree_reconstruction.py` (per B-W34-1) and a corresponding `tests/conformance/test_spine_completeness_at_construction.py` (forthcoming this wave) will assert: any `ReasoningTrace` reachable through the v1 contract surface has non-empty spine fields. Without the `__post_init__` check, a single buggy constructor anywhere in the kernel can silently emit traces with missing spine — and we discover it only on the consumer side, hours into a long run.

**Acceptance criteria for closure (W34-F.3):**
1. `ReasoningTrace.__post_init__` (locate the class; cite the path in your closure notice) raises `ValueError` (or a typed `SpineCompletenessError`) on any of: empty `tenant_id`, empty `parent_run_id` when `attempt_id != "1"`, empty `phase_id`.
2. Unit test `tests/unit/test_reasoning_trace_spine_validation.py`:
   - Construct `ReasoningTrace` with each spine field individually empty; assert each raises.
   - Construct with all fields non-empty; assert succeeds.
3. Backfill-discovery test `tests/integration/test_no_existing_reasoning_trace_construction_violates_spine.py`:
   - Walk all production construction sites; each must produce a valid `ReasoningTrace` under realistic input. (This is the test that catches "we added the check but a constructor was already passing empty strings".)
4. Three-part closure: (a) fix in `__post_init__`; (b) `scripts/check_dataclass_spine_validation.py` (or extend `check_contract_spine_completeness.py`) verifies that every `@dataclass` carrying spine fields also defines `__post_init__` with the assertion; (c) document in `hi_agent/ARCHITECTURE.md` §"Spine completeness".

---

### B-W34-3 — `KnowledgeWiki` tenant partition

**Class:** Tenant isolation / Dimension T
**Severity:** BLOCKER (escalated from W33 carryover F.4)

**Evidence:**
- W33 delivery notice §"Outstanding Items" line: "F.4 KnowledgeWiki tenant partition | RO | W34 carryover | Per-tenant key composition".
- W33-D.2 closed defense-in-depth at the `RunQueue` layer (9 methods × 28 tests). The KG / Wiki layer is the next-most-trafficked tenant-sensitive store and is not yet closed.

**Why it blocks downstream consumption:**
RIA's positioning of the platform (Lens 1) is "tenant isolation — policy provided by upper systems, enforced by platform". RIA enforces ACL above the platform tenant — but our defense-in-depth assumes the platform's tenant is hard. A `KnowledgeWiki` that does not partition per-tenant means tenant A's wiki entries can be read by tenant B's runs as a function of internal kernel access patterns. This is exactly the failure mode that the W31-T1 / W31-B-5 closure work targeted at the registry layer. The `KnowledgeWiki` layer is the same class of risk one level over.

RIA's Phase 3 `paper_archive` and `lean_library` will hold cross-project data that *intentionally* spans tenants only at the curation layer (a paper added to the cross-tenant archive by tenant A is intentionally readable by tenant B *iff* the curator promotes it). The platform's `KnowledgeWiki` is *not* that store — it is per-tenant by intent. The structural enforcement must match the intent.

**Acceptance criteria for closure (W34-F.4):**
1. `KnowledgeWiki` persistent store includes `tenant_id NOT NULL` on every key (or composite key = `(tenant_id, ...)`); read paths require `tenant_id`; `get_unsafe()`-style escape hatches removed from public surface (internal callers may keep them with `# scope: process-internal` annotation per W31 precedent).
2. `tests/integration/test_knowledge_wiki_tenant_partition.py`:
   - Tenant A writes entry `E_A`; tenant B writes entry `E_B`.
   - Tenant A reads `E_A` → success.
   - Tenant A reads `E_B` (with A's `X-Tenant-ID`) → 404 (not 403, not 200, not the entry).
   - Tenant B reads `E_A` (with B's `X-Tenant-ID`) → 404.
   - Repeat under all three postures (`dev` / `research` / `prod`); under `dev`, the cross-tenant read may succeed with a logged warning (per existing posture pattern); under `research` and `prod`, must 404.
3. Existing `xfail` tests under `tests/integration/test_knowledge_*` (if any) flip to PASS.
4. Three-part closure: (a) fix in `KnowledgeWiki`; (b) `scripts/check_no_unscoped_knowledge_reads.py` AST-walks every read site and fails if `tenant_id` is not in the read parameters; (c) document in `hi_agent/ARCHITECTURE.md` §"Tenant isolation".

---

### B-W34-4 — Cross-tenant skill / tool / capability registry partition status verified (B-5 follow-through)

**Class:** Tenant isolation / Dimension T / W31 carryover verification
**Severity:** BLOCKER

**Evidence:**
- W31 §B-5 stated: "KG, skill, tool, and capability registry add `tenant_id NOT NULL` to the persistent schema" with acceptance criterion W31-T1: `tests/integration/test_route_handle_{kg,skill,tool,capability}_tenant_isolation.py` flip from xfail to pass under `prod` posture.
- W33 delivery notice does not enumerate the four-registry status. W33-D.2 closes `RunQueue` defense-in-depth (one of many platform stores), not the original four registries from W31-B-5.
- We need explicit confirmation: at HEAD `ce9330fa`, what is the per-registry status of W31-T1?

**Why it blocks downstream consumption:**
RIA's `paper_archive` (Phase 3) reads from the platform's skill registry to discover available archival skills. If the skill registry is not tenant-partitioned, RIA's tenant-A query may surface skills registered by tenant B. This is a Lens 1 violation.

The unknown-status problem itself is the BLOCKER. We are not asking you to do new work; we are asking you to publish the evidence of work that may already be done.

**Acceptance criteria for closure (W34-T-FOLLOWUP):**
1. Publish a status row in your W34 delivery notice for each of the four registries originally named in W31-B-5:
   - KnowledgeGraph (KG)
   - Skill registry (`hi_agent/skill/` per ARCHITECTURE.md §5)
   - Tool registry (cite the actual module — likely under `hi_agent/capability/` or a dedicated tools subpackage; we ask you to identify the canonical location)
   - Capability registry (`hi_agent/capability/` per ARCHITECTURE.md §5)
   For each: state `tenant_id` enforcement status (closed / open) at HEAD `ce9330fa`, and cite the integration test that verifies it (or the absence thereof).
2. Any registry not closed at HEAD is added to the W34 BLOCKER set with the same closure shape as B-W34-3.
3. `tests/conformance/test_cross_tenant_isolation_full_surface.py` (RIA-side, forthcoming): probes each scoped read route on the v1 contract with mismatched `X-Tenant-ID`; expects 404. Currently runs against stub; will run against `ce9330fa`-or-newer once published.

---

### B-W34-5 — `/v1/manifest` posture exposure spec'd in `agent_server/contracts/v1/manifest.py`

**Class:** Agent service to upper systems / Dimension N + Dimension D
**Severity:** BLOCKER

**Evidence:**
- `GET /v1/manifest` exists per ARCHITECTURE.md §7 and is referenced as a route returning "compact fingerprint of resolved env/config".
- RIA's R-RIA-6 (per `ria-quality-requirements-v1.md` §1) requires that RIA refuse to start under `prod` posture against a platform reporting `dev` posture. This is enforced by `ria/config/posture.py::Posture.assert_compatible_with_platform()`.
- RIA's call into `/v1/manifest` to discover platform posture requires a stable, contract-frozen field. `agent_server/contracts/v1/manifest.py` (or equivalent) does not currently spec this field.

**Why it blocks downstream consumption:**
R-RIA-6 is enforced at RIA process startup; if the manifest's posture field name shifts between W33 and W34 (e.g., `posture` → `runtime_mode` → `env_class`), RIA's startup check breaks silently or noisily. Either failure mode prevents safe operation. The contract guarantee is what makes the field usable.

**Acceptance criteria for closure (W34-MANIFEST):**
1. `agent_server/contracts/v1/manifest.py` (or the existing equivalent) declares a frozen field — proposed name `posture: Literal["dev", "research", "prod"]` — with a docstring naming RIA's R-RIA-6 as the consumer.
2. The field is part of the v1 contract digest (currently SHA `8c6e22f1`); if including this field requires re-freezing the digest, do so and publish the new digest.
3. Conformance test `tests/integration/test_manifest_posture_field_present.py`:
   - `GET /v1/manifest` under each of dev / research / prod posture.
   - Assert response body contains `posture` with the matching string value.
   - Assert response shape conforms to `manifest.py` declaration.
4. RIA-side conformance test `tests/conformance/test_manifest_field_stability.py` (forthcoming on RIA side): replays a cassette of the W34 manifest response; asserts RIA's `Posture.from_platform_manifest_response()` parses it without error.

---

### B-W34-6 — Idempotency cross-process replay test + documented semantics

**Class:** Functional idempotency / Dimension I
**Severity:** BLOCKER

**Evidence:**
- Per §2.2, current idempotency tests do not cover: (c) request lands on platform, platform restarts before responding, RIA retries; (d) two-process replay state sharing; (e) idempotency record TTL.
- RIA's process restart path (per `ria-architecture-v1.md` §6, §8.6) explicitly resumes long-lived projects by re-reading store state and replaying outstanding writes with the same idempotency key. This relies on platform-side replay correctness across kernel restarts.

**Why it blocks downstream consumption:**
The cross-process replay correctness is the single most consequential property of the idempotency contract. Without an explicit test + spec, RIA's resume path may double-create projects, double-cancel runs, or miss replay-cached responses depending on platform implementation details we cannot inspect. We need this contract to be frozen.

**Acceptance criteria for closure (W34-IDEMPOTENCY):**
1. New integration test `tests/integration/test_idempotency_cross_process_replay.py`:
   - Start `agent-server serve` (subprocess).
   - Send `POST /v1/runs` with `Idempotency-Key=K1`; receive 201 with `run_id=R1`.
   - SIGTERM the server; restart it (same data dir).
   - Send identical `POST /v1/runs` with `Idempotency-Key=K1` (same body); expect 201 with `run_id=R1` (cached response replayed across process boundary).
   - Send same key with different body; expect 409.
   - Repeat for `cancel`, `signal`, `register_skill`, `write_artifact`.
2. Document the semantics in `agent_server/contracts/v1/idempotency.py` (or equivalent). Specifically: (i) cache TTL (or "no TTL — keys cached for run lifetime + grace period of N minutes"), (ii) cache scope (per-tenant? global?), (iii) what happens on key collision across tenants (proposed: scoped per-tenant; key collision across tenants is impossible by construction).
3. The contract digest is updated if (2) requires schema change.
4. Three-part closure: (a) test exists; (b) `scripts/check_idempotency_contract_documented.py` verifies the contract docstring section is present and ≥ N lines; (c) record in `agent_server/ARCHITECTURE.md` §"Idempotency".

---

### B-W34-7 — Concurrency benchmark first-baseline

**Class:** High concurrency / Dimension C
**Severity:** BLOCKER

**Evidence:**
- §2.4 above: no published benchmark methodology, no first-baseline number, SQLite write contention untested at `N=100`, no PostgreSQL equivalence test.
- "High concurrency" is one of the eight positioning lenses RIA holds the platform to. Without a measured baseline, the lens scores "claimed but not measured".

**Why it blocks downstream consumption:**
RIA needs to know the platform's concurrency ceiling before sizing per-tenant rate-limits in `ria/user/budget.py` and before designing the burst-handling shape of `ria/api/http/`. Without a baseline, RIA either oversizes (waste) or undersizes (rejected requests during deadline weeks). The first baseline is sufficient for sizing; subsequent waves can refine.

**Acceptance criteria for closure (W34-CONCURRENCY):**
1. Benchmark methodology document at `docs/perf/concurrency-methodology-v1.md`:
   - Workload: `N` parallel `POST /v1/runs` from `M` simulated tenants.
   - Measurement: P50, P95, P99 of run-start latency; per-tenant fairness coefficient; queue depth time series; SQLite lock-wait count.
   - `N ∈ {1, 10, 50, 100}`; `M ∈ {1, 10}`.
   - Hardware target: a documented baseline (e.g., "16-core x86, 32 GB RAM, SSD, Linux") so the numbers are reproducible.
2. First-baseline JSON at `docs/verification/<head>-concurrency-N100M10.json` with `provenance: real`; passes a new gate `scripts/check_concurrency_evidence.py`.
3. SQLite vs PostgreSQL equivalence test `tests/integration/test_concurrency_persistence_swap.py`:
   - Same workload at `N=10, M=1`.
   - Both persistence backends produce the same terminal state distribution.
4. The `verified_readiness` score at W34 close should reflect this measurement (incrementally, per your established cap-factor discipline).

---

## 4. Naming / Structure Hygiene Backlog (RIA-Discretion Items)

Three items remain from W33 closure as "deferred per RIA's W32 acceptance §7" with the noting "RIA explicitly says 'at our discretion'":

| ID | Item | Owner per W33 | RIA disposition |
|---|---|---|---|
| H-3' | experiment shim deletion | DX | **Close-or-formal-declination required by W34 close** |
| H-13' | task triplet umbrella | RO | **Close-or-formal-declination required by W34 close** |
| H-14' | templates dir consolidation | DX | **Close-or-formal-declination required by W34 close** |

**Position.** "RIA discretion" is not a permanent disposition; it means RIA does not depend on the closure for our current Phase. It does *not* mean the items can sit indefinitely. The W31 directive established (§B-6, Engineering Discipline 1.2) that naming / structure accretion is itself a defect — that rule applies to any wave of deferral.

Acceptable W34 closures for each:

(a) **Close** — execute the consolidation; cite the commit + measure of import-site update.
(b) **Formal declination** — write a one-paragraph rationale in `docs/governance/package-consolidation-2026-05-04.md`: why this name pair is structurally distinct enough that consolidation harms maintainability more than it helps. RIA will accept formal declination as a closure if the rationale is concrete (cites actual import-site asymmetry, conceptual distinctness, or downstream consumer expectation).

Not acceptable: silent carry-forward to W35.

---

## 5. RIA-Side Forcing Function (A.3.α)

This section explains why W34's BLOCKERs are timed-now rather than "eventually". It is informational for hi-agent (no action required from your team beyond closing the BLOCKERs) but it is the operational context for why the closures matter at this wave.

### 5.1 RIA's policy decision (2026-05-04)

RIA has resolved to build Phase 3 (`global_layer/` — `paper_archive`, `lean_library`, `dataset_registry`, `evolution_engine`) **against the real `agent-server serve` process**, not against a stub `agent_server`. The decision is documented in `docs/ria/ria-architecture-v2.md` (forthcoming this wave on our side) under the label "A.3.α — red-as-honest forcing function".

**Why we made this decision.** The hi-agent team's own engineering experience (per the `engineering-readiness-scorecard-2026-04-26-wave10.md` lineage) is that mock-based / stub-based development filtered out real platform issues that surfaced later as expensive rework. RIA has had the same experience in our Phase 1 development: stub `agent_server` passed tests that real `agent-server serve` will fail. We are removing the stub layer for Phase 3 to apply CLAUDE.md's "Using mocks to bypass real failures is strictly forbidden" rule at our integration-test boundary.

### 5.2 What this means for hi-agent operationally

Within days of W33 publication, RIA will have integration tests of the form:

```python
# tests/integration/test_evolution_engine_attempt_tree_reconstruction.py
# (illustrative; exact RIA-side module paths are still being scaffolded)
async def test_recovery_chain_lineage_intact(real_agent_server):
    run_id = await ria.orchestration.start_pi_agent_run(...)
    await advance_to_stage(run_id, "S2")
    await sigterm_kernel_worker()
    await wait_for_recovery(run_id, timeout=60)

    rows = await ria.platform_client.fetch_run_records(run_id)
    assert rows[0].attempt_id == "1"
    assert rows[1].attempt_id == "2"
    assert rows[1].parent_run_id == rows[0].run_id  # F.2 dependency
```

With F.2 unclosed, this assertion fails. We will not patch the test to work around the failure. We will publish the failure under `docs/ria/red-status/<head>.json` so hi-agent can see exactly which test is red and why.

Similar tests apply for B-W34-2 (F.3 spine validation), B-W34-3 (F.4 KG partition), B-W34-4 (B-5 follow-through), B-W34-5 (manifest posture), B-W34-6 (cross-process idempotency), B-W34-7 (concurrency baseline). RIA's CI will reflect, in real time, which W34 BLOCKERs are still unclosed.

### 5.3 What RIA commits to publish

For each commit to RIA's main branch, we will publish:

```
docs/ria/red-status/<sha>.json
{
  "ria_head": "<sha>",
  "platform_head_under_test": "ce9330fa or newer",
  "blocked_by_platform": [
    {"test": "tests/integration/test_evolution_engine_attempt_tree_reconstruction.py::test_recovery_chain_lineage_intact",
     "blocked_by_w34_id": "B-W34-1",
     "first_observed_ria_head": "<sha>"},
    ...
  ],
  "ria_internal_red": [...],   // tests RIA broke; unrelated to platform
  "green": [...]
}
```

This is machine-readable; hi-agent can ingest it as a CI signal. We are not requesting that you act on it — we are committing to publish it so the wave-cycle conversation between our teams becomes evidence-grounded rather than narrative-grounded.

### 5.4 What RIA does NOT do

To preempt a possible misinterpretation: RIA does **not** propose to add defense-in-depth shims on the RIA side that mask platform gaps. We considered the alternative ("RIA implements a lineage proxy that fills empty `parent_run_id` from RIA's own tracking; RIA implements a tenant-scope filter on KG reads that double-checks before forwarding") and rejected it. The rejection rationale is: RIA-side defense-in-depth that is planned to retire when the platform closes the gap is the same shape as the "naming accretion is a defect" pattern from W31 — debt that lives forever because each wave optimises for not adding it.

The BLOCKER list above is the single locus of work. RIA does not duplicate it.

---

## 6. Acceptance Criteria for W34 (CI-Verifiable)

The complete W34 entry-acceptance set, one row per check, all required:

| ID | Test or script (must exist + pass) | Closes |
|---|---|---|
| W34-F.2 | `tests/unit/test_run_execution_context_lineage_population.py` + `tests/integration/test_run_lineage_persisted_after_recovery.py` + `scripts/check_lineage_population.py` exit 0 | B-W34-1 |
| W34-F.3 | `tests/unit/test_reasoning_trace_spine_validation.py` + `tests/integration/test_no_existing_reasoning_trace_construction_violates_spine.py` + `scripts/check_dataclass_spine_validation.py` exit 0 | B-W34-2 |
| W34-F.4 | `tests/integration/test_knowledge_wiki_tenant_partition.py` + xfail flip to PASS + `scripts/check_no_unscoped_knowledge_reads.py` exit 0 | B-W34-3 |
| W34-T-FOLLOWUP | Per-registry status published in W34 delivery notice + any open registry added to BLOCKER set | B-W34-4 |
| W34-MANIFEST | `agent_server/contracts/v1/manifest.py` declares `posture` field + `tests/integration/test_manifest_posture_field_present.py` PASS + contract digest re-published if needed | B-W34-5 |
| W34-IDEMPOTENCY | `tests/integration/test_idempotency_cross_process_replay.py` PASS + `agent_server/contracts/v1/idempotency.py` documents semantics + `scripts/check_idempotency_contract_documented.py` exit 0 | B-W34-6 |
| W34-CONCURRENCY-METHOD | `docs/perf/concurrency-methodology-v1.md` published | B-W34-7 |
| W34-CONCURRENCY-BASELINE | `docs/verification/<head>-concurrency-N100M10.json` `provenance: real` + `scripts/check_concurrency_evidence.py` exit 0 | B-W34-7 |
| W34-CONCURRENCY-EQUIV | `tests/integration/test_concurrency_persistence_swap.py` PASS | B-W34-7 |
| W34-NAMING-CLOSE | H-3', H-13', H-14' each closed-or-formally-declined; `docs/governance/package-consolidation-2026-05-04.md` updated | §4 |
| W34-CONFIG-ENV-AUDIT | Enumeration of all `os.environ` reads in `hi_agent/**` + `agent_server/**`; classification (Posture-routed vs direct vs principled exception); `scripts/check_env_var_routing.py` extended to cover the principled exception list | §2.5 |
| W34-LINUX-SOAK-ROADMAP | One paragraph in W34 delivery notice describing Linux-runner soak roadmap (advisory) | §2.7 |

All twelve are blocking gates in `release-gate.yml` for W34 entry, with the exception of W34-LINUX-SOAK-ROADMAP (advisory).

**Score implications:** RIA does not request a score-cap change in W34. The 75.0 cap continues to be governed by `soak_evidence_not_real` (waived) + `evidence_provenance` (W27 historicals). Closing the seven BLOCKERs improves the underlying readiness; whether and how that surfaces in the scorecard is hi-agent's call per your existing scorecard discipline.

---

## 7. Out of Scope for Wave 34 (Explicitly Not Asking)

To keep the wave focused, the following items — even though some remain on our wishlist — are **not** part of the W34 entry expectations. Track them in your own backlog:

- New v1 contract routes beyond what is required by B-W34-5 (manifest posture). RIA's Phase 3 will require cross-project read routes (skill-list-by-pattern, run-history-by-skill, KG cross-project query) at some future wave, but we will write those requirements in a future directive once we have implemented enough of `external_services/` to know our exact shape.
- The `evidence_provenance` cap factor (W27 historicals + W28 erratum). The 3 historical artifacts are out-of-scope per the W31 directive §6 and remain so.
- Platform v2 contract work. We pin `agent_server v1` per the original architecture-improvement directive A-01; v2 work is your team's planning, not our request.
- Linux-runner chaos coverage extension (the 2 OS-limited scenarios). Listed as advisory in §2.7; not blocking.
- Front-end UI or client SDKs. Not RIA's concern at the platform layer.

---

## 8. Reporting Format (For Wave 34 Closure Notice)

When you close W34, the delivery notice should include the following structured section so we can verify mechanically:

```
## Wave 34 Closure Evidence (RIA-side directive 2026-05-04)

| Acceptance ID | Status | Evidence path | Provenance |
|---|---|---|---|
| W34-F.2                      | PASS | tests/unit/test_run_execution_context_lineage_population.py + tests/integration/test_run_lineage_persisted_after_recovery.py + scripts/check_lineage_population.py | measured |
| W34-F.3                      | PASS | tests/unit/test_reasoning_trace_spine_validation.py + tests/integration/test_no_existing_reasoning_trace_construction_violates_spine.py + scripts/check_dataclass_spine_validation.py | measured |
| W34-F.4                      | PASS | tests/integration/test_knowledge_wiki_tenant_partition.py + scripts/check_no_unscoped_knowledge_reads.py | measured |
| W34-T-FOLLOWUP               | PASS | per-registry status table in this notice + cross-references | derived |
| W34-MANIFEST                 | PASS | agent_server/contracts/v1/manifest.py + tests/integration/test_manifest_posture_field_present.py | measured |
| W34-IDEMPOTENCY              | PASS | tests/integration/test_idempotency_cross_process_replay.py + agent_server/contracts/v1/idempotency.py + scripts/check_idempotency_contract_documented.py | measured |
| W34-CONCURRENCY-METHOD       | PASS | docs/perf/concurrency-methodology-v1.md | derived |
| W34-CONCURRENCY-BASELINE     | PASS | docs/verification/<head>-concurrency-N100M10.json + scripts/check_concurrency_evidence.py | real |
| W34-CONCURRENCY-EQUIV        | PASS | tests/integration/test_concurrency_persistence_swap.py | measured |
| W34-NAMING-CLOSE             | PASS | docs/governance/package-consolidation-2026-05-04.md (per-item: closed | declined-with-rationale) | measured / derived |
| W34-CONFIG-ENV-AUDIT         | PASS | scripts/check_env_var_routing.py exit 0 + audit table in delivery notice | measured |
| W34-LINUX-SOAK-ROADMAP       | NOTED | one paragraph in delivery notice | advisory |
```

Status `PARTIAL` is **not** an accepted W34 outcome for any of the eleven blocking IDs. Each is binary. `NOTED` is acceptable for the advisory item only.

**Three-part defect closure documentation.** For each W34 BLOCKER closure, include the three-part closure summary in the delivery notice (per Engineering Discipline 1.3 above):

```
### W34-F.2 closure (three-part)

(a) Code fix: <commit SHA + file:line>
(b) Recurrence-prevention check: <gate script + CI integration commit>
(c) Process change: <CLAUDE.md or ARCHITECTURE.md section + line>
```

Missing (a), (b), or (c) leaves the closure OPEN.

---

## 9. Why We Are Sending This as a Single Directive (Following W31 Precedent)

We considered batching the seven BLOCKERs into separate, lighter waves. We chose to bundle for the same reasons as W31:

(a) **The three carryover items (B-W34-1, B-W34-2, B-W34-3) are already late.** They were W34 carryover at W33 close on 2026-05-04; deferring them further compounds the lineage and tenant-isolation gaps at the exact moment RIA's Phase 3 going-real exposes them.

(b) **The four new items (B-W34-4 through B-W34-7) are all small individually.** B-W34-4 is "publish status of work likely already done". B-W34-5 is one contract field declaration. B-W34-6 is one integration test + a contract docstring. B-W34-7 is a benchmark methodology + one measurement run.

(c) **Bundling forces the conversation to be about the wave as a whole**, not about per-item negotiation. The W31 directive's bundling was successful (W31 + W31a + W31b were all closed) and we apply the same shape here.

If the bundled scope is too large for one wave, your alternative is to split into:
- **W34a** (B-W34-1, B-W34-2, B-W34-3, B-W34-4 — the tenant + lineage spine work; closure of W33 carryover)
- **W34b** (B-W34-5, B-W34-6, B-W34-7 + naming + env audit — the new engineering expectations)

We accept this split. We do **not** accept any split that defers B-W34-1, B-W34-2, or B-W34-3 past Wave 34. Those three are the W33 carryover and have already been planned as W34 work by your team.

---

## 10. Questions, Pushback, Negotiation

We expect pushback on the following three points; here is our position in advance so the W34 plan response can be focused:

### 10.1 "Do we really need a benchmark in W34?" (re: B-W34-7)

Our position: Yes, but we are flexible on `N` and on the per-tenant `M` parameter. The non-negotiable property is the existence of a methodology document + a first measurement at *some* `N > 1`. If 100 concurrent run-starts is infeasible on your CI runner, propose the largest feasible `N` and we will accept it as the W34 baseline. Subsequent waves can raise the bar.

### 10.2 "Why escalate F.2 / F.3 / F.4 from carryover to BLOCKER?" (re: B-W34-1/2/3)

Our position: §5 above. The escalation is driven by RIA's Phase 3 going-real, not by a change in our perception of severity. F.2 / F.3 / F.4 were already known-defects at W33 close. The escalation is a timing change, not a re-classification. If your team has already planned to close them in W34 (which the W33 carryover label suggests), the escalation is a no-op for you.

### 10.3 "Why are we asking for /v1/manifest spec'ing now, instead of when the field changes?" (re: B-W34-5)

Our position: Field changes silently (rename or removal) are unsafe for downstream consumers exactly because there is no contract spec to detect the change. We are asking for the spec *before* a change is contemplated, so that any future change crosses an explicit contract gate. The spec is a one-time cost; the silent-change risk is permanent without it.

---

## 11. Cross-References

| Document | Purpose | Status |
|---|---|---|
| `D:\chao_workspace\hi-agent\docs\downstream-responses\2026-05-04-w33-delivery-notice.md` | hi-agent W33 delivery notice (the basis we work from) | live |
| `D:\chao_workspace\hi-agent\ARCHITECTURE.md` | hi-agent platform architecture (refreshed at W33) | live |
| `D:\chao_workspace\research\docs\hi-agent-wave31-blocker-closure-requirements-2026-05-02.md` | W31 directive (precedent for this directive's shape) | live |
| `D:\chao_workspace\research\docs\ria\ria-architecture-v1.md` | RIA L0 architecture v1 | live |
| `D:\chao_workspace\research\docs\ria\ria-architecture-v2.md` | RIA L0 architecture v2 (forthcoming this wave) | forthcoming |
| `D:\chao_workspace\research\docs\ria\ria-quality-requirements-v1.md` (→ v1.1) | RIA quality bar | revising to v1.1 this wave |
| `D:\chao_workspace\research\docs\ria\ria-domain-model-v1.md` (→ v1.1) | RIA domain entities | revising to v1.1 this wave |
| `D:\chao_workspace\research\docs\ria\ria-platform-contract-mapping-v1.md` (→ v1.1) | RIA → platform contract mapping | revising to v1.1 this wave |
| `D:\chao_workspace\research\docs\ria\red-status\<sha>.json` | RIA's machine-readable red-status artifact (per §5.3) | forthcoming |

---

## 12. Acknowledgement

The W33 delivery is exemplary work. The escalations and new expectations in this directive are not a comment on the quality of W33; they are the natural shape of the work that follows from W33's closures, plus the engineering positioning RIA is making explicit for the first time. The eight-lens framing (§2) is RIA's contribution to making the conversation between our teams more legible to both sides.

We expect pushback. We expect renegotiation on specific acceptance criteria. We do not expect rebadging of any BLOCKER as advisory; per Engineering Discipline 1.3, that is not a closure path.

---

**Signed:** RIA team
**Audit head (RIA side):** docs match RIA `main` at 2026-05-04
**Platform head under audit:** `ce9330fa` (hi-agent W33, manifest `2026-05-03-ce9330fa`)
**Document maturity:** M1 — internally reviewed; promotes to M2 (preprint-grade) when mirrored into hi-agent's `docs/upstream-directives/` per the conduct spec.

---

**End of Wave 34 Engineering Expectations.**
