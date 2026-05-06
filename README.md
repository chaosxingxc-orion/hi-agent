# hi-agent

**Capability layer for autonomous agent execution.**
hi-agent is the platform that the Research Intelligence App (RIA) and other downstream applications build on top of. It packages a cognitive runtime, durable execution substrate, and a versioned northbound HTTP facade — and refuses to host business logic.

**TRACE** = Task → Route → Act → Capture → Evolve. The five-stage execution model is the kernel's contract for every run.

---

## Architecture Positioning

hi-agent is built around six properties that downstream consumers should be able to rely on:

- **Idempotent.** Every mutating northbound route accepts an `Idempotency-Key`. Same key + tenant + body returns byte-identical responses; same key + different body returns 409.
- **Stable.** The v1 contract surface is frozen. `agent_server/contracts/` is digest-snapshotted; breaking changes go to a parallel `v2/` sub-package, never in-place.
- **Extensible.** New capabilities register via plugin hooks (skill, MCP, capability registry); the v1 surface gains additive routes without touching v1 contract types.
- **Evolvable.** ExperimentStore + ChampionChallenger + recurrence-ledger drive A/B versioning and rollback. Skill evolution is closed-loop with operationally-observable alerts.
- **Configurable.** Posture-aware defaults (`dev` permissive / `research` and `prod` fail-closed) flow from `HI_AGENT_POSTURE` through every subsystem; `TraceConfig` + `ConfigStack` support hot-reload.
- **Sustainable.** Seventeen engineering rules in `CLAUDE.md` are CI-enforced. Every contract crossing a tenant boundary carries `tenant_id`. Every silent-degradation path has a metric, log, and gate-asserted alarm.

The platform enforces a hard boundary between platform-layer logic (this repo) and business-layer logic (research team). All downstream integration goes through `agent_server/` HTTP routes only; direct imports of `hi_agent.*` from downstream code are not supported.

---

## Quickstart

**Requirements:** Python 3.12+

### Install

```bash
git clone <repo-url> hi-agent
cd hi-agent
pip install -e ".[llm,dev]"
```

### Smoke

```bash
pytest -m "not live_api and not network and not requires_secret"
```

Or via the canonical wrapper that produces fresh evidence JSON:

```bash
python scripts/verify_clean_env.py --profile default-offline
```

Current baseline (HEAD `276917d8`, W35 corrective close): 9,288 passed / 8 skipped /
0 failed (default-offline profile, ~3 min wall clock).

### Start the northbound API server

```bash
agent-server serve --host 0.0.0.0 --port 8080
```

To use a real LLM provider and fail-closed research posture:

```bash
export HI_AGENT_POSTURE=research
export HI_AGENT_LLM_MODE=real
export OPENAI_API_KEY=<your-key>
agent-server serve --prod
```

### Submit a run

Write the request body to a JSON file (`request.json`), then:

```bash
agent-server run --tenant tenant-a --request-json request.json
```

Or via HTTP. Under research/prod posture every mutating route requires both `X-Tenant-Id`
and `Idempotency-Key`, plus a Bearer JWT signed with `HI_AGENT_JWT_SECRET`:

```bash
curl -s -X POST http://localhost:8080/v1/runs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Tenant-Id: tenant-a" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"tenant_id": "tenant-a", "profile_id": "default", "goal": "summarise quarterly results", "project_id": "proj-1"}'
```

### Cancel a run and stream events

```bash
agent-server cancel --tenant tenant-a --run-id <run_id>
agent-server tail-events --tenant tenant-a --run-id <run_id>
```

The `tail-events` command consumes the live SSE stream from
`GET /v1/runs/{id}/events` (W33-C.5 made it a true live stream rather than a
snapshot-and-close).

---

## Architecture Overview

```mermaid
graph TB
    subgraph BIZLAYER["Business Layer (out of repo)"]
        RIA["Research Intelligence App<br/>(domain logic, prompts, business schemas)"]
        SDK["Third-party SDKs"]
    end

    subgraph CAPLAYER["Capability Layer (this repo)"]
        subgraph NB["Northbound facade — agent_server/"]
            NB_API["api/ — FastAPI routes + middleware<br/>(JWTAuth → TenantContext → Idempotency)"]
            NB_FAC["facade/ — Contract↔kernel adapters<br/>(≤200 LOC each)"]
            NB_CON["contracts/ — Frozen v1 schemas<br/>(SHA 55e51a7f)"]
            NB_RT["runtime/ — Real-kernel binding<br/>(RealKernelBackend, lifespan,<br/>auth_seam)"]
            NB_CLI["cli/ — Operator commands<br/>(serve · run · cancel · tail-events)"]
            NB_CFG["config/ — settings, version"]
            NB_BS["bootstrap.py — Assembly seam #1<br/>build_production_app"]
        end
        subgraph HI["Cognitive runtime + inlined kernel — hi_agent/"]
            HI_LLM["llm/ — Gateway, tier router, budget,<br/>failover chain"]
            HI_RUN["server/ — AgentServer + RunManager +<br/>durable SQLite stores (runs, events,<br/>queue, idempotency, gates, team)"]
            HI_RT["runtime/, runtime_adapter/<br/>— Sync bridge, kernel adapters"]
            HI_MEM["memory/, knowledge/, skill/<br/>— Cognitive subsystems"]
            HI_OBS["observability/ — RunEventEmitter,<br/>spine events, audit log, metrics"]
            HI_AUTH["auth/ + server/auth_middleware<br/>— JWT validation primitives"]
        end
    end

    RIA -->|"HTTP /v1/* + Bearer JWT (research/prod)"| NB_API
    SDK -->|"HTTP /v1/* + Bearer JWT"| NB_API
    NB_CLI --> NB_BS
    NB_API --> NB_FAC
    NB_FAC --> NB_CON
    NB_BS --> NB_API
    NB_BS --> NB_FAC
    NB_BS --> NB_RT
    NB_BS -. "import hi_agent.*<br/>(R-AS-1 seam #1)" .-> HI
    NB_RT -. "import hi_agent.*<br/>(R-AS-1 seam #2)" .-> HI
    NB_RT -. "auth_seam reuses<br/>hi_agent JWT primitives" .-> HI_AUTH
    NB_FAC -. "injected callables" .-> NB_RT
```

Two repository packages cooperate:

| Package | Role |
|---|---|
| `agent_server/` | Versioned northbound HTTP facade (v1 contract frozen at SHA `55e51a7f`); the **only contract surface** RIA depends on |
| `hi_agent/` | Cognitive runtime + inlined execution kernel: LLM gateway, runner, memory, knowledge, skills, config, observability, durable run stores |

> The historical `agent_kernel/` package was inlined into `hi_agent/server/` at Wave 11. References to `agent_kernel.*` in older docs map to `hi_agent.server.*` today.

R-AS-1 (two-seam discipline): only `agent_server/bootstrap.py` and `agent_server/runtime/**` may import `hi_agent.*`. CI gate `scripts/check_layering.py` enforces; annotated `# r-as-1-seam:` imports in two facade modules carry rationale and are policed by `scripts/check_facade_seams.py`.

Detailed architecture: [`docs/architecture-reference.md`](docs/architecture-reference.md). Per-subsystem docs in §[Reference Map](#reference-map).

---

## Project Status

**Production engineering phase.** Latest close: **Wave 35 at 2026-05-05**. The W35-corrective window mirrored the RIA corrective directive and W36 plans; current HEAD is `276917d8` (2026-05-06). Refer to `CLAUDE.md` § "Project Status" for the binding statement; the wave timeline below tracks delivered scope.

| Wave | Headline | Status |
|---|---|---|
| W1–W11 | Foundation: cognitive runtime, TRACE S1–S5, agent_kernel inlined | closed |
| W12 | Default-path hardening; Rules 14–17 codified | closed |
| W13–W15 | Systemic class closures; 35-gate infrastructure | closed |
| W16 | Observability spine + chaos + operator drill | closed |
| W17–W18 | Manifest discipline + governance gap definitions | closed |
| W19 | Scope-aware caps + 6 class closures (verified=86.6) | closed |
| W20 | 10 defect classes (CL1–CL10); raw=88.7 | closed |
| W21–W22 | Continuous closure (verified rebound to 80.0) | closed |
| W23 | 8 parallel tracks + 3 cleanups (verified=94.55) | closed |
| W24 | Agent server MVP (5 routes + idempotency + CLI) | closed |
| W25 | PM2 drill + contract freeze + git-worktree dispatch | closed |
| W26 | Hidden-gap closure pass | closed |
| W27 | 17 lanes closed; PR#17; soak deferred | closed |
| W28 | Architectural 7×24 tier (`run_arch_7x24.py`); soak retired | closed |
| W29–W30 | Substantive closure passes | closed |
| W31 | RIA directive 13/14 IDs PASS; verified=55.0 (capped by `soak_evidence_not_real`); 79/91 hidden findings closed | closed |
| W32 | Real-kernel binding for v1 northbound; ARCHITECTURE refresh; hidden-gap closure; cleanup | closed |
| W33 | RIA acceptance follow-ups: JWT middleware (C.4); SSE live-stream (C.5); SIGTERM graceful drain (C.2); RunQueue tenant defense-in-depth (D.2); spine lineage (F.1); `HI_AGENT_ENV` unification (E.1); audit-log tenant_id (D.1) | closed |
| W34 | RIA W34 BLOCKERs B-W34-1..B-W34-7 + 4 governance items: lineage population, ReasoningTrace spine validation, KnowledgeWiki tenant partition, registry audit, manifest posture field, idempotency contract, concurrency baseline | closed |
| W35 | RIA W35-T1..W35-T8 acceptance: 53-dataclass spine validation, posture parity sweep, INVERTED posture fix, idempotency TTL purge + observability + boot-time MCP assertion + W35-T9 hidden re-lease attempt_id bump; 38 of 91 hidden audit findings closed | closed |
| W35-corrective | C-1 metric labels reverted (`{tenant_bucket}` → `{tenant_id}`); C-2 `provenance_unknown_or_synthetic` lifecycle note; C-3 W35-T9 closure level; C-4 dev-side body-mismatch regression test; H1 extension manifest + spine asymmetric test fill-in; H2 orphan gate wiring; §5.1 wave-ledger drift fix; §5.2 signoff evidence-exemption | closed (HEAD `276917d8`) |
| W36 | A3 Tier-1 retention adoption (8 stores) · A4 schema lineage extensions · A5 boot-time assertions · 6h Linux soak (cap-resolution path) | binding (plans staged) |

Current verified readiness: **75.0** at the W35 close manifest (`docs/releases/platform-release-manifest-2026-05-05-24cfa0a6.json`). The cap is held by `soak_evidence_not_real` per RIA W35 directive §6 (retained explicitly; W36 6h Linux soak addresses measurement). `raw_implementation_maturity = 94.5` reflects the additional spine + audit work. Architectural 7×24: 5/5 PASS at the W34 HEAD; the W35 corrective commits include hot-path code (`hi_agent/observability/idempotency_metrics.py`, `hi_agent/server/run_manager.py`), so a fresh T3 gate run is required at HEAD `276917d8` per Rule 8 T3 invariance before any score recompute.

| Capability | Level | Notes |
|---|---|---|
| Run execution (TRACE S1–S5) | L3 | Long-lived process, real LLM, durable queue |
| TierRouter | L3 | Active calibration, signal-weight routing (P-6 closed W27) |
| ExtensionRegistry | L4 | Full lifecycle, rollback, third-party registration |
| PostmortemEngine | L2 | Wired into RunManager; `on_project_completed` hook |
| StageDirective wiring | L3 | `skip_to` + `insert_stage` + `replan` wired |
| Multi-agent team | L2 | `TeamRunSpec`; registry; not production-default |
| Knowledge graph | L2 | SQLite backend; four-layer retrieval (no v1 northbound route) |
| Evolution closed-loop | L2 | `ExperimentStore` rollback; recurrence-ledger observable |
| MCP tools | L2 | `StdioMCPTransport`; plugin-registered (v1 route is L1 stub) |
| Observability spine | L3 | `RunEventEmitter` (12 event types); real provenance enforced |
| agent_server v1 contract | L3 | Frozen at SHA `55e51a7f`; production default |

Maturity levels: L0 demo · L1 tested component · L2 public contract · L3 production default · L4 ecosystem ready (Rule 13).

### RIA capability map — 7 dimensions × 8 lenses

Downstream RIA tracks platform readiness along seven capability dimensions and eight architectural lenses (Rule 10). Where each W35-close capability lands:

| RIA dimension | Lens | hi-agent surface | Status at W35 close |
|---|---|---|---|
| Execution | L3 high reliability | `agent_server/api/routes_runs*.py` + `hi_agent/server/run_manager.py` (W35-T3 auth-authoritative tenant precedence) | L3 production default |
| Memory | L1 tenant isolation | `hi_agent/memory/episodic.py` (W35-T1 spine validation) | L2 public contract |
| Capability | L8 agent service to upper systems | `hi_agent/capability/registry.py` + manifest posture field (W34-MANIFEST) | L2 public contract; `posture` field frozen for RIA R-RIA-6 |
| Knowledge graph | L1 + L3 | `hi_agent/knowledge/wiki.py` per-tenant partition (W34-F.4) + KG SQLite backend | L2 public contract |
| Planning | L3 + L6 | `hi_agent/runner_stage.py` StageDirective wiring; W35-T1 spine validation across reasoning + planning contracts | L3 production default |
| Artifact | L2 functional idempotency | `hi_agent/artifacts/contracts.py` + `agent_server/contracts/idempotency.py` (W34 contract + W35-T4 retention + W35-T6 metrics + W35-T8 boot assertion) | L3 production default; idempotency contract frozen + retained |
| Evolution | L6 continuous intelligence evolution | `hi_agent/evolve/*` (W35-T1 + W35-T2 spine + posture parity); `RunFeedback`, `EvolveResult`, `EvolveChange` posture-validated | L2 public contract |
| Cross-Run | L7 7×24 architectural feasibility | Lineage chain (W34-F.2 create-run + W35-T9 re-lease attempt_id bump); retention infra (W35-T4 reference + `docs/governance/retention-roadmap.md`) | L3 production default for happy path; W36 binding to extend Tier-1 retention |

W35 audit reconnaissance at five dimensions (A1 spine, A2 posture, A3 unbounded-growth stores, A4 lineage, A5 boot-time) surfaced 91 hidden findings; 38 closed in W35, 32 scoped for W36 via `docs/governance/retention-roadmap.md` + `docs/governance/boot-time-assertions-roadmap.md`, 17 for W37+. See `docs/governance/systematic-audit-w35-2026-05-05.md` for the audit footprint.

---

## Posture Model

`HI_AGENT_POSTURE` selects the platform's execution posture (Rule 11). Every config knob, fallback path, and persistence backend declares its default behaviour for the three values:

| Subsystem | `dev` (permissive) | `research` | `prod` (fail-closed) |
|---|---|---|---|
| Spine validation (Rule 12) | Missing `tenant_id` / `run_id` / `stage_id` logs WARNING; record accepted | Raises `SpineCompletenessError` at construction | Raises `SpineCompletenessError` at construction |
| Tenant scope on body vs middleware (W35-T3) | Body tenant_id mismatching middleware logs WARNING; auth-authoritative middleware value used | Raises `TenantScopeError` (anti-forgery) | Raises `TenantScopeError` (anti-forgery) |
| Persistence backends | In-memory backends accepted (`InMemoryDecisionAuditStore`, `InMemoryKnowledgeStore`) | SQLite-backed backends required | SQLite-backed backends required |
| `AGENT_SERVER_BACKEND=stub` | Accepted (default-offline test profile) | Raises `ValueError` at boot | Raises `ValueError` at boot |
| Missing JWT secret (`HI_AGENT_JWT_SECRET`) | 401 per request (no boot fail) | Required (per-request 401 today; W36 boot assertion B15) | Required (per-request 401 today; W36 boot assertion B15) |
| LLM fallback | Heuristic fallback allowed; metric emitted | Heuristic fallback alarm-triggers via `hi_agent_llm_fallback_total` | Heuristic fallback blocks Rule 8 ship gate |
| Idempotency middleware | Permissive (mock cache OK) | Strict; required on every mutating route | Strict; required on every mutating route |

Set via env: `export HI_AGENT_POSTURE=research` (recommended for downstream integration testing) or `prod` (operator-shape gate).

---

## Operator-Shape (Rule 8) Gate Summary

No artifact ships until it runs in the exact operator shape downstream uses. Six checks plus the architectural 7×24 readiness assertions hold at every release HEAD:

1. **Long-lived process** — PM2 / systemd / docker run; not foreground `python -m`.
2. **Real LLM** — `HI_AGENT_LLM_MODE=real` against the production provider.
3. **Sequential real-LLM runs (N≥3)** — three back-to-back `POST /v1/runs`, each reaches `state=done`, `llm_fallback_count=0`, ≥1 LLM request emitted to access log + metric.
4. **Cross-loop resource stability** — runs 2 and 3 reuse the same gateway/adapter as run 1 (Rule 5 stress).
5. **Lifecycle observability** — each run reports a non-`None` `current_stage` within 30 s; `finished_at` populated on terminal.
6. **Cancellation round-trip** — `POST /v1/runs/{id}/cancel` on a live run returns 200 and drives terminal; on unknown id returns 404.

**Architectural 7×24 readiness** (W28 reform, RIA W35 §2.7) — five assertions replace the 24h soak: cross-loop stability (3 sequential real-LLM runs), lifespan observable (current_stage <30s), cancellation round-trip, spine provenance real, chaos runtime-coupled. Evidence file: `docs/verification/<sha>-arch-7x24.json` with all 5 PASS.

T3 evidence at the release HEAD: `docs/delivery/<date>-<sha>-t3-volces.json`. The W35 close lands hot-path code in `run_manager.py`, `idempotency.py`, `app.py`, and `lifespan.py`; the W35-corrective commits (HEAD `276917d8`) further touch `hi_agent/observability/idempotency_metrics.py` and `hi_agent/server/run_manager.py` — T3 invariance demands a fresh gate run at the current HEAD before the verified-readiness score is recomputed.

---

## Idempotency Contract

Every mutating northbound route accepts an `Idempotency-Key`. The contract is documented in `agent_server/contracts/idempotency.py` and frozen at the v1 contract digest. Behaviour (per W34 + W35):

| Property | Value | Source |
|---|---|---|
| Cache scope | per-tenant (`SCOPE='tenant'`); two tenants with identical keys never collide | W34-IDEMPOTENCY |
| Cross-process replay | Same key + same body returns byte-identical response across process restarts (POSIX-tested; Windows skipped with documented reason) | W34-IDEMPOTENCY (`tests/integration/test_idempotency_cross_process_replay.py`) |
| Body mismatch | Same key + different body returns HTTP 409 conflict (research/prod); WARNING log + 409 (dev) | W34-IDEMPOTENCY |
| TTL | `DEFAULT_TTL_SECONDS=86400.0` (24h); records past TTL deleted by background purge + lazy purge on next access | W34-IDEMPOTENCY + W35-T4 |
| Retention | `IdempotencyStore.purge_expired()` drained by `_idempotency_purge_loop` background task in `agent_server/runtime/lifespan.py`; lazy purge in `reserve_or_replay` | W35-T4 (`tests/integration/test_idempotency_ttl_purge.py`) |
| Observability | 4 Prometheus metrics on `/metrics`: `hi_agent_idempotency_replay_total`, `_conflict_total`, `_purged_total`, `_record_age_seconds` (histogram) | W35-T6 (`docs/observability/idempotency-metrics.md`) |
| Boot-time check | `include_mcp_tools=True` or `include_skills_memory=True` requires `idempotency_facade is not None`; raises at boot otherwise | W35-T8 (`tests/integration/test_mcp_tools_idempotency.py`) |
| Spine fields (Rule 12) | Every `IdempotencyRecord` carries `tenant_id` + posture-aware validation in `__post_init__` | W35-T1 |
| Limitations (W37+) | Float canonicalization (`1` vs `1.0`) deferred per RIA endorsement — see Limitations section in `agent_server/contracts/idempotency.py` | W35-T5 |

Cross-region multi-process idempotency (external coordinator) is out of scope at the v1 surface.

---

## Tests / Dev Workflow

| Profile | Coverage | Tooling |
|---|---|---|
| `default-offline` | 9,288 tests; no network, no real LLM, no secrets; ~3 min wall clock | `python scripts/verify_clean_env.py --profile default-offline` |
| `release` | default-offline + T3 freshness + manifest consistency + route-scope + lint + rule-checks | release-captain workflow |
| `live_api` | Real LLM path; manual / scheduled | `pytest -m live_api` (requires `OPENAI_API_KEY` or `VOLCES_API_KEY`) |
| `prod_e2e` (Rule 8 gate) | Operator-shape gate; long-lived process; real LLM; 3 sequential runs | `python scripts/run_t3_volces.py` (Volces) or `scripts/run_t3.py` (provider-agnostic) |
| `chaos` | Injection matrix; 10 scenarios (8 cross-platform, 2 POSIX-only) | `python scripts/run_arch_7x24.py` |

Test profiles defined in `tests/profiles.toml` (Rule 16). Every PR description carries a "Profile validated:" line.

CI gates: `scripts/check_dataclass_spine_validation.py` (53 targets at W35 close), `scripts/check_lineage_population.py`, `scripts/check_layering.py` (R-AS-1), `scripts/check_facade_seams.py`, `scripts/check_contract_freeze.py`, `scripts/check_manifest_freshness.py`, `scripts/check_doc_consistency.py`, `scripts/check_wave_consistency.py`, `scripts/check_allowlist_discipline.py`, `scripts/check_env_var_routing.py`, `scripts/check_idempotency_contract_documented.py`, `scripts/check_no_unscoped_knowledge_reads.py`, `scripts/check_concurrency_evidence.py`. See `.github/workflows/` for the full matrix.

---

## Key Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `HI_AGENT_POSTURE` | `dev` | Execution posture: `dev` permissive, `research`/`prod` fail-closed (Rule 11) |
| `HI_AGENT_LLM_MODE` | `heuristic` | `real` routes to actual LLM provider |
| `HI_AGENT_ENV` | `dev` | `prod` enables fail-fast 503 on missing credentials. Read only via `Posture.resolve_runtime_mode()` (W33-E.1) |
| `AGENT_SERVER_BACKEND` | `real` | `real` binds `RealKernelBackend` from `agent_server/runtime/`; `stub` keeps `_InProcessRunBackend` for the default-offline test profile (forbidden under research/prod) |
| `AGENT_SERVER_STATE_DIR` | – | Persistent state directory (SQLite stores: runs, events, queue, idempotency, gates, team) |
| `HI_AGENT_HOME` | – | Fallback state-dir parent: `$HI_AGENT_HOME/.agent_server` |
| `AGENT_SERVER_HOST` / `AGENT_SERVER_PORT` | `0.0.0.0` / `8080` | Settings for `AgentServerSettings.load_settings()` |
| `HI_AGENT_JWT_SECRET` | – | HMAC secret for `JWTAuthMiddleware` (W33-C.4); required under research/prod |
| `HI_AGENT_KERNEL_BASE_URL` | – | Legacy detached-kernel RPC (deprecated; kernel inlined at W11) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `VOLCES_API_KEY` | – | LLM provider credentials |

Full environment matrix: [`docs/deployment-env-matrix.md`](docs/deployment-env-matrix.md).

---

## Reference Map

Per-subsystem architecture docs (each follows the standard 11-section SE template, all
diagrams in mermaid):

| Subsystem | Document |
|---|---|
| **L0 system** | [`ARCHITECTURE.md`](ARCHITECTURE.md) (arc42-style) |
| **L1 agent_server** (northbound facade) | [`agent_server/ARCHITECTURE.md`](agent_server/ARCHITECTURE.md) |
| L2 HTTP routes + middleware | [`agent_server/api/ARCHITECTURE.md`](agent_server/api/ARCHITECTURE.md) |
| L2 Contract↔kernel adaptation | [`agent_server/facade/ARCHITECTURE.md`](agent_server/facade/ARCHITECTURE.md) |
| L2 Frozen v1 contracts | [`agent_server/contracts/ARCHITECTURE.md`](agent_server/contracts/ARCHITECTURE.md) |
| L2 Real-kernel binding | [`agent_server/runtime/ARCHITECTURE.md`](agent_server/runtime/ARCHITECTURE.md) |
| L2 Operator CLI | [`agent_server/cli/ARCHITECTURE.md`](agent_server/cli/ARCHITECTURE.md) |
| L2 Config + version constants | [`agent_server/config/ARCHITECTURE.md`](agent_server/config/ARCHITECTURE.md) |
| **L1 hi_agent** (cognitive runtime + inlined kernel) | [`hi_agent/ARCHITECTURE.md`](hi_agent/ARCHITECTURE.md) |
| L2 server kernel (RunManager + durable stores) | [`hi_agent/server/ARCHITECTURE.md`](hi_agent/server/ARCHITECTURE.md) |
| L2 runtime helpers (sync bridge, harness) | [`hi_agent/runtime/ARCHITECTURE.md`](hi_agent/runtime/ARCHITECTURE.md) |
| L2 runtime_adapter (kernel facade spine) | [`hi_agent/runtime_adapter/ARCHITECTURE.md`](hi_agent/runtime_adapter/ARCHITECTURE.md) |
| L2 LLM gateway / tier router / failover | [`hi_agent/llm/ARCHITECTURE.md`](hi_agent/llm/ARCHITECTURE.md) |
| L2 Observability spine (events, metrics) | [`hi_agent/observability/ARCHITECTURE.md`](hi_agent/observability/ARCHITECTURE.md) |
| L2 Knowledge layer (wiki + KG + retrieval) | [`hi_agent/knowledge/ARCHITECTURE.md`](hi_agent/knowledge/ARCHITECTURE.md) |
| L2 Skill subsystem (load, version, evolve) | [`hi_agent/skill/ARCHITECTURE.md`](hi_agent/skill/ARCHITECTURE.md) |
| L2 Capability registry | [`hi_agent/capability/ARCHITECTURE.md`](hi_agent/capability/ARCHITECTURE.md) |
| **Codebase reference** | [`docs/architecture-reference.md`](docs/architecture-reference.md) — canonical module index, R-AS rules, gate map |

---

## Engineering Rules (one-line summary)

The seventeen rules in [`CLAUDE.md`](CLAUDE.md) are CI-enforced. Brief intent of each:

| # | Rule | One-line intent |
|---|---|---|
| 1 | Root-cause + strongest-interpretation | Surface the four-line root cause + pick the strongest reading before any plan |
| 2 | Simplicity & surgical changes | Minimum code that solves the stated problem; touch only what the task requires |
| 3 | Pre-commit checklist | Audit contract truth, orphan config, error visibility, lint, test honesty before every commit |
| 4 | Three-layer testing | Unit + integration (zero mocks on subject) + E2E; honest assertions only |
| 5 | Async/sync resource lifetime | Async resource bound to one loop; sync callers route through `sync_bridge` |
| 6 | Single construction path | One builder per shared resource; DI everywhere; `x or DefaultX()` banned |
| 7 | Resilience must not mask signals | Every fallback: countable + attributable + inspectable + gate-asserted |
| 8 | Operator-shape readiness gate | PM2 / real LLM / N≥3 sequential runs at the release HEAD; T3 invariance |
| 9 | Self-audit is a ship gate | Open ship-blocking findings block delivery; Known-Defect Notice or fix |
| 10 | Downstream contract alignment | Use RIA's vocabulary; their severity wins; respond to roadmaps in writing |
| 11 | Posture-aware defaults | Every knob declares dev/research/prod behaviour; tests cover at least dev + research |
| 12 | Contract spine completeness | Every persistent record carries `tenant_id` + relevant scope dimensions |
| 13 | Capability maturity model | Status reporting uses L0–L4 with evidence; "implemented" is not a status |
| 14 | Manifest is the single release fact source | Closure notices derive claims from the manifest; no manual score increases |
| 15 | Closure-claim taxonomy + 3-part defect closure | `verified_at_release_head` minimum + (code fix, gate, process change) |
| 16 | Test profile taxonomy | Profiles in `tests/profiles.toml`; PR descriptions declare profile validated |
| 17 | Allowlist discipline | Allowlist entries are tracked debt with owner / risk / expiry / replacement |

CI workflows under `.github/workflows/` enforce the rules; `scripts/check_*.py` are the primitives.

---

## Contributing

| Pointer | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Seventeen engineering rules + ownership tracks + narrow-trigger rules. CI-enforced. |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Wave-by-wave implementation plans. Latest closed: `2026-05-05-wave-35-systematic-audit-followups.md`. Binding W36 plans: `2026-05-06-wave-36-a3-tier1-retention-adoption.md`, `2026-05-06-wave-36-a4-schema-lineage-extensions.md`, `2026-05-06-wave-36-a5-boot-time-assertions.md` |
| [`docs/governance/`](docs/governance/) | Closure taxonomy, evidence-provenance schema, allowlists, recurrence ledger, retention roadmap (W35), boot-time assertions roadmap (W35), systematic-audit-w35 |
| [`docs/platform/`](docs/platform/) | Public surface descriptions: `agent-server-northbound-contract-v1.md`, runtime profile guide |
| [`docs/observability/`](docs/observability/) | Operator-facing metric/spine docs (e.g. `idempotency-metrics.md`, W35-T6 + W35-corrective C-1 label policy) |
| [`docs/upstream-directives/`](docs/upstream-directives/) | Mirrored RIA directives (latest: `2026-05-05-hi-agent-w35-corrective-directive.md`) |
| [`docs/downstream-responses/`](docs/downstream-responses/) | Wave delivery notices + corrective responses to downstream (latest: `2026-05-05-w35-corrective-response.md`) |

Owner tracks govern review responsibilities (see `CLAUDE.md`):

| Track | Scope |
|---|---|
| CO | Contracts, schemas, posture |
| RO | Execution, state machines, persistence |
| DX | CLI, config, developer tooling |
| TE | Artifacts, observability, evolution |
| GOV | CI, delivery governance, CLAUDE.md |
| AS-CO | `agent_server` contracts (v1 frozen) |
| AS-RO | `agent_server` routes, facades, CLI, runtime |

Every PR must declare its owner track in the commit body. Hot-path changes require T3 gate evidence at `docs/delivery/`. Pre-commit checklist (Rule 3) is mandatory.

---

## License

Proprietary — internal platform use only. Not for external distribution.
