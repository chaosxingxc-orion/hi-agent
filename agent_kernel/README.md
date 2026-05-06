# agent_kernel

> **Last refreshed:** 2026-05-06 (W35 corrective close + W36 plans). HEAD `276917d8`.
> **Audience:** internal — platform engineers and RO-track owners.

`agent_kernel` is the **execution substrate** in the three-package layout declared in `CLAUDE.md`:

- `agent_server/` — versioned northbound facade (frozen v1).
- `hi_agent/` — kernel umbrella (posture, runtime adapters, server backends, profiles).
- `agent_kernel/` — **this package** — durable run-actor lifecycle, six-authority FSM, persistence ports.

It is consumed by `hi_agent.runtime_adapter.kernel_facade_client` (which then proxies up to `agent_server`'s northbound contract). End-user entry is always through `agent_server` — never directly here.

---

## What lives here

| Subpackage | Role |
|---|---|
| `adapters/facade/` | `KernelFacade` — the only sanctioned ingress; all writes go through it. |
| `kernel/` | Six-authority FSM core (`turn_engine`, `reasoning_loop`, `admission/`, `dedupe_store`, `recovery/`, `persistence/`, `task_manager/`). |
| `runtime/` | `KernelRuntime`, `AgentKernelRuntimeBundle`, `KernelMetricsCollector`, `KernelHealthProbe`, `RunHeartbeatMonitor`. |
| `service/` | Internal Starlette HTTP service exposing `KernelFacade` 1:1 (`agent_kernel-server` CLI entry). |
| `substrate/` | Temporal SDK / Host / LocalFSM adaptors. Vendored Temporal at `external/temporal-sdk-python/`. |
| `skills/`, `adapters/`, `testing.py`, `worker_main.py` | Skill primitives, adapter shims, test factories, standalone Worker entry. |

The full picture (six authorities, FSM phases, persistence backends, ADRs, quality attributes) is in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Public surface

Exactly three names are exported from `agent_kernel/__init__.py`:

- `KernelFacade` — ingress; instantiated by `hi_agent`'s runtime adapter.
- `KernelRuntime` — runtime wiring (assembles bundle).
- `LocalSubstrateConfig` — in-process substrate (test/CI).

Everything else is internal. Imports of `agent_kernel.kernel.*` from outside the kernel are gated by `scripts/check_no_reverse_imports.py`.

---

## Running locally (developer)

This is **not** an end-user package — start the full stack from `agent_server`. To exercise the kernel in isolation for debugging:

```bash
# Standalone Temporal Worker (requires AGENT_KERNEL_TEMPORAL_HOST)
python -m agent_kernel.worker_main

# Standalone HTTP service (Starlette)
uvicorn agent_kernel.service.http_server:create_app_temporal --factory --port 8400
```

Configuration via `KernelConfig.from_env()` (env vars prefixed `AGENT_KERNEL_`); see `agent_kernel/config.py` for the full env map.

---

## W36 binding scope visible from this package

Two W36 directives have land sites inside `agent_kernel/`:

| W36 track | Scope inside `agent_kernel/` | Plan |
|---|---|---|
| **A3 — Tier-1 retention adoption** | 5 SQLite stores under `kernel/persistence/`: `sqlite_event_log.py`, `sqlite_dedupe_store.py`, `sqlite_decision_deduper.py`, `sqlite_recovery_outcome_store.py`, `sqlite_turn_intent_log.py`. Each adopts the W35-T4 `purge_expired` shape with chunked DELETE + tenant-labeled metric. | `docs/superpowers/plans/2026-05-06-wave-36-a3-tier1-retention-adoption.md` (stores 6–8). |
| **A5 — Boot-time assertions** | 3 sites in `service/http_server.py`: B4 (`api_key` non-None when posture is strict), B5 (`facade` non-None at app build), B11 (block `InMemory*` backends when `environment="prod"`). | `docs/superpowers/plans/2026-05-06-wave-36-a5-boot-time-assertions.md` (B4/B5/B11). |

The kernel itself does **not** host a lifespan; W36-A3 retention loops are scheduled inside `agent_server/runtime/lifespan.py` (the agent_server lifespan owns purge supervision for kernel stores too, per plan §2 store 6).

---

## Pointers

- Architecture detail → [`agent_kernel/ARCHITECTURE.md`](./ARCHITECTURE.md)
- Engineering rules → [`../CLAUDE.md`](../CLAUDE.md) (Rules 5, 6, 8, 12, 14, 17 are the most relevant to kernel changes)
- Top-level architecture (system boundary) → [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
- Narrow-trigger rule for the kernel HTTP server / `kernel_facade_client.py` symmetry → CLAUDE.md operational appendix
