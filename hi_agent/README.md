# hi_agent

> **Internal package — not a user-facing entry point.**
> **Last refreshed:** 2026-05-06 (W35 corrective close + W36 plans). HEAD `276917d8`.

`hi_agent/` is the **platform execution kernel** of the hi-agent stack. It owns run lifecycle, durable persistence, async/sync resource lifetimes, capability dispatch, observability spine, memory tiers, knowledge stores, and LLM transport.

End users do not import `hi_agent` directly. The supported entry points are:

- **HTTP API:** `agent_server/` v1 (frozen at `55e51a7f`) — see `../agent_server/README.md`
- **Operator CLI:** `agent-server serve` — wraps `agent_server.bootstrap.build_production_app`
- **Programmatic facade:** `from hi_agent import RunExecutorFacade, check_readiness` — see "Public API" below

For the deep architecture map, see [`ARCHITECTURE.md`](ARCHITECTURE.md). For engineering rules, see [`../CLAUDE.md`](../CLAUDE.md).

---

## When you import this

The seam rule is **R-AS-1**: from outside `hi_agent/`, only `agent_server/runtime/kernel_adapter.py` and `agent_server/bootstrap.py` are permitted to `import hi_agent.*`. CI rejects every other inbound edge.

If you are inside the platform team and need to reach in, the import surface is split into three tiers:

| Tier | Import path | Stability |
|---|---|---|
| **Public-ish** (re-exported from `hi_agent.__init__`) | `RunExecutorFacade`, `check_readiness`, `GateEvent`, `GatePendingError`, `SubRunHandle`, `SubRunResult`, `ReadinessReport`, `RunFacadeResult` | Stable across waves; breaking changes require an ADR |
| **Sub-package public** (`hi_agent.<pkg>` top-level exports) | `hi_agent.server.AgentServer`, `hi_agent.runtime.get_bridge`, `hi_agent.runtime.harness.HarnessExecutor`, `hi_agent.contracts.*`, `hi_agent.llm.tier_presets.apply_strict_defaults` | Sub-package owners may break; bumps documented in delivery notices |
| **Internal** (anything else) | `hi_agent.server.run_manager.ManagedRun`, `hi_agent.server._durable_backends.*`, `hi_agent.runtime.async_bridge.*`, etc. | No stability guarantee; may move/rename per wave |

If your code reaches into the **Internal** tier, expect to be invited to the sub-package's owner review and to update with future waves.

---

## Public API (`hi_agent.__init__`)

```python
from hi_agent import (
    RunExecutorFacade,    # start(run_id, profile_id, model_tier, skill_dir) / run(prompt) / stop()
    RunFacadeResult,      # dataclass returned by .run()
    ReadinessReport,      # per-subsystem health snapshot
    check_readiness,      # () -> ReadinessReport
    GateEvent,            # human-gate lifecycle event
    GatePendingError,     # raised when stage execution hits a pending gate
    SubRunHandle,         # nested sub-run dispatch handle
    SubRunResult,         # nested sub-run terminal result
)
```

**Posture awareness.** `hi_agent` follows Rule 11: every config knob and fallback path declares its behaviour under `dev` / `research` / `prod`. Set `HI_AGENT_POSTURE` (default `dev`). Under `research`/`prod`, missing tenant_id, missing `HI_AGENT_DATA_DIR`, and missing JWT signing key all fail-closed. See `hi_agent/config/posture.py`.

**Tenant_id is auth-authoritative (W35-T3).** Code under `hi_agent/` does not trust tenant_id supplied in a request body. The single legal origin is the JWT claim validated by `agent_server/auth/`. Any new `hi_agent/server/` route handler that accepts tenant_id from a request body is a defect.

---

## Sub-package documentation

| Sub-package | Purpose | Detail doc |
|---|---|---|
| `server/` | Run lifecycle, durable persistence, ASGI app, AuthMiddleware | [`server/ARCHITECTURE.md`](server/ARCHITECTURE.md) |
| `runtime/` | sync_bridge (Rule 5), async_bridge, cancellation, harness | [`runtime/ARCHITECTURE.md`](runtime/ARCHITECTURE.md) |
| `runtime_adapter/` | Kernel facade adapter spine (direct + http modes) | [`runtime_adapter/ARCHITECTURE.md`](runtime_adapter/ARCHITECTURE.md) |
| `llm/` | Tier router, failover, anthropic/openai gateways, streaming | [`llm/ARCHITECTURE.md`](llm/ARCHITECTURE.md) |
| `observability/` | Metrics, audit, spine emitters, alerts, SLO | [`observability/ARCHITECTURE.md`](observability/ARCHITECTURE.md) |
| `memory/` | L0 raw → L1 compressed → L2 mid-term → L3 KG | [`memory/ARCHITECTURE.md`](memory/ARCHITECTURE.md) |
| `knowledge/` | Wiki + graph + retrieval (TF-IDF + embedding) | [`knowledge/ARCHITECTURE.md`](knowledge/ARCHITECTURE.md) |
| `skill/` | Registry + loader + matcher + evolver + version mgr | [`skill/ARCHITECTURE.md`](skill/ARCHITECTURE.md) |
| `capability/` | Registry + invoker + circuit breaker + governance | [`capability/ARCHITECTURE.md`](capability/ARCHITECTURE.md) |
| `contracts/` | Public dataclasses, errors, spine validation, posture | [`contracts/CONTRACTS.md`](contracts/CONTRACTS.md) |

Runtime-layer split rule: [`RUNTIME-LAYERS.md`](RUNTIME-LAYERS.md) — what belongs in `runtime/` vs `runtime_adapter/`.

---

## Quickstart for platform engineers

```bash
# 1. Install (editable)
pip install -e ".[llm]"

# 2. Set posture + data directory
export HI_AGENT_POSTURE=research
export HI_AGENT_DATA_DIR=./hi_agent_data

# 3. Run the test suite (offline default)
python -m pytest -q

# 4. Lint
python -m ruff check .

# 5. Boot the agent_server with hi_agent kernel mounted
agent-server serve --host 0.0.0.0 --port 8080
```

For real-LLM smoke tests (operator-shape gate per Rule 8), see `scripts/run_t3_gate.py` and the gate-evidence convention under `docs/delivery/<date>-<sha>.md`.

---

## See also

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — full architecture map for `hi_agent/`
- [`../CLAUDE.md`](../CLAUDE.md) — engineering rules (Rules 1–17), ownership tracks (CO/RO/DX/TE/GOV/AS-CO/AS-RO), narrow-trigger rules
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — top-level system boundary (hi_agent + agent_server + agent_kernel + agent_core)
- [`../docs/governance/retention-roadmap.md`](../docs/governance/retention-roadmap.md) — 24 unbounded-growth stores; W36-A3 binding for Tier 1
- [`../docs/governance/boot-time-assertions-roadmap.md`](../docs/governance/boot-time-assertions-roadmap.md) — B1–B14 W36-A5 binding
- [`../agent_server/README.md`](../agent_server/README.md) — frozen northbound facade
