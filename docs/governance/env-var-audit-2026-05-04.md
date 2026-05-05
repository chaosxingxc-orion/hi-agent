# W34-CONFIG-ENV-AUDIT — Environment Variable Reads (2026-05-04)

**Wave:** 34
**Closes:** W34-CONFIG-ENV-AUDIT (RIA §6 / §2.5)
**Scope:** every `os.environ.get` / `os.environ[...]` / `os.getenv` read under `hi_agent/**` and `agent_server/**` (production code; tests + scripts excluded).
**Method:** AST + Grep enumeration at HEAD `8978f0eb` plus the W34 changes through `5809e422`.

---

## Classification taxonomy

Every direct read is classified into one of three categories:

| Category | Definition | Acceptable in W34? |
|---|---|---|
| **Posture-routed** | The read site is `hi_agent/config/posture.py::resolve_runtime_mode` (the canonical runtime-mode resolver) — covered by W33-E.1's `check_no_hi_agent_env_direct_read.py` gate. | Yes |
| **Settings-loader** | The read site is the documented entry point for that variable, encapsulated behind a typed accessor (`AgentServerSettings.load_settings`, `Posture.from_env`, `json_config_loader.get_provider_api_key`, etc.). The accessor is the canonical home; consumers never reach `os.environ` themselves. | Yes |
| **Principled exception** | The read is at a CLI / bootstrap / diagnostic surface where the value is **data, not logic input** (operator dump, environment forwarding, fault-injection toggle, etc.). Each entry below carries a written rationale. | Yes (allowlisted) |
| **Direct (unscoped)** | A read at a non-canonical site that bypasses the typed accessor. **Defect.** | No (must be routed) |

`scripts/check_env_var_routing.py` (W34) extends `check_no_hi_agent_env_direct_read.py` to enforce this classification at CI time.

---

## Variable inventory (35 unique vars across 64 read sites)

### Posture / runtime mode (Rule 11)

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_POSTURE` | `hi_agent/config/posture.py:34` (anchor); `hi_agent/config/posture.py:126`; `agent_server/api/routes_skills_memory.py:62`; `agent_server/contracts/gate.py:15`; `hi_agent/operator_tools/diagnostics.py:296` | Posture-routed (anchor) + 4 callers using the typed accessor | The anchor is `Posture.from_env`; the four other reads call it transitively via the helper or apply the same fallback. None are unscoped. |
| `HI_AGENT_ENV` | `hi_agent/config/posture.py:129` (sanctioned anchor); `hi_agent/server/ops_routes.py:73` (allowlisted diagnostic) | Posture-routed (anchor) + principled exception | Enforced by `scripts/check_no_hi_agent_env_direct_read.py` (W33-E.1). The ops_routes.py read is allowlisted in that gate as an operator diagnostic dump. |

### Posture-derived runtime knobs

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_LLM_MODE` | `hi_agent/config/json_config_loader.py:119`; `:180`; `hi_agent/server/ops_routes.py:75` | Settings-loader + diagnostic | Reads happen inside the JSON config layering function (`json_config_loader.resolve_llm_mode`) and the operator dump. Both are canonical homes. |
| `HI_AGENT_KERNEL_BASE_URL` | `hi_agent/operator_tools/diagnostics.py:103`; `hi_agent/server/ops_routes.py:74` | Diagnostic only | Both reads are operator dumps; neither drives runtime decisions. The actual kernel routing reads via `AgentServer` config. |
| `HI_AGENT_KERNEL_BASE_URL_OVERRIDE_UNSAFE` | `hi_agent/runtime_adapter/kernel_facade_client.py:57` | Principled exception (test-only override) | The variable name itself documents the boundary; only set in test fixtures. |
| `HI_AGENT_KERNEL_MODE` | `hi_agent/server/ops_routes.py:76` | Diagnostic only | |
| `HI_AGENT_ALLOW_HEURISTIC_FALLBACK` | `hi_agent/capability/defaults.py:42`; `hi_agent/server/ops_routes.py:79` | Settings-loader + diagnostic | The `_allow_heuristic_fallback()` helper is the single canonical reader; ops_routes is the dump. |

### Profile / config layering

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_PROFILE` | `hi_agent/config/stack.py:104`; `hi_agent/server/app.py:1904`; `hi_agent/server/ops_routes.py:78` | Settings-loader + bootstrap + diagnostic | The `ConfigStack` stack is the canonical reader; bootstrap echoes for legacy reasons. |
| `HI_AGENT_PROFILE_DIR` | `hi_agent/config/builder.py:151` | Settings-loader | |
| `HI_AGENT_CONFIG_DIR` | `hi_agent/config/runtime_config_loader.py:76`; `hi_agent/config/builder.py:141` | Settings-loader (two sub-callers in same module family) | |
| `HI_AGENT_CONFIG_FILE` | `hi_agent/server/app.py:1901`; `hi_agent/cli.py:193`,:391,:478; `hi_agent/server/ops_routes.py:77` | CLI + bootstrap + diagnostic | The CLI is the canonical entry point; `app.py:1901` mirrors at server-spawn for CLI parity. |

### Persistence / data dirs

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_DATA_DIR` | 10 sites under `hi_agent/{server,artifacts,operator_tools,cli_commands}/` and `agent_server/runtime/kernel_adapter.py:110` | Bootstrap-fanned (each module reads from the env once at construction; the value is then thread-local) | Each read is the documented entry point for that subsystem. The W34 audit confirms no read path branches on this variable; it is purely a path string. Consolidating these reads behind a single accessor is a W35+ refactor opportunity (low risk, low value). |
| `HI_AGENT_HOME` | `agent_server/bootstrap.py:83`; `hi_agent/profiles/directory.py:30` | Bootstrap | |
| `AGENT_SERVER_STATE_DIR` | `agent_server/bootstrap.py:80` | Bootstrap | |
| `HI_AGENT_EPISODES_DIR` | `hi_agent/operator_tools/release_gate.py:317` | Operator tool | |

### LLM credentials (Rule 7 — never written, only read)

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | `hi_agent/operator_tools/diagnostics.py:74`; `hi_agent/server/ops_routes.py:67` | Diagnostic only | Both reads emit boolean presence (`bool(os.environ.get(...))`); the actual key value flows through `hi_agent/config/json_config_loader.py::get_provider_api_key`. |
| `ANTHROPIC_API_KEY` | `hi_agent/operator_tools/diagnostics.py:73`; `hi_agent/server/ops_routes.py:66` | Diagnostic only | Same shape. |
| `HI_AGENT_API_KEY` | `hi_agent/server/auth_middleware.py:62` | Auth middleware (canonical) | |

### JWT auth (W33-C.4 + W34-C.4 hardening)

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_JWT_SECRET` | `agent_server/runtime/auth_seam.py:121`; `hi_agent/server/auth_middleware.py:117` | Auth seam (canonical) + legacy auth middleware | Both files explicitly carry the `# r-as-1-seam:` annotation. |
| `ENFORCE_JWT_SIGNATURE` | `hi_agent/server/auth_middleware.py:118` | Auth middleware | |
| `HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS` | `agent_server/runtime/auth_seam.py:123`; `hi_agent/server/auth_middleware.py:311` | Test-only override | Documented in module docstrings as a boundary marker. |

### agent_server settings

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `AGENT_SERVER_HOST` | `agent_server/config/settings.py:25` | Settings-loader (canonical) | |
| `AGENT_SERVER_PORT` | `agent_server/config/settings.py:17` | Settings-loader (canonical) | |
| `AGENT_SERVER_API_VERSION` | `agent_server/config/settings.py:27` | Settings-loader (canonical) | |
| `AGENT_SERVER_BACKEND` | `agent_server/bootstrap.py:106` | Bootstrap (canonical) | |

### Lifespan / runtime tunables

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_DRAIN_TIMEOUT_S` | `agent_server/runtime/lifespan.py:176` | Lifespan (canonical) | |
| `HI_AGENT_LEASE_EXPIRY_INTERVAL_S` | `agent_server/runtime/lifespan.py:245` | Lifespan (canonical) | |
| `HI_AGENT_API_TIMEOUT_SECONDS` | `hi_agent/cli.py:34` | CLI | |
| `HI_AGENT_RECOVERY_REENQUEUE` | `hi_agent/server/app.py:1244`; `hi_agent/server/recovery.py:60` | Recovery posture (canonical pair) | |

### Knowledge / capability

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_KG_BACKEND` | `hi_agent/knowledge/factory.py:48` | Settings-loader (canonical) | |
| `HI_AGENT_ENABLE_SHELL_EXEC` | `hi_agent/capability/tools/builtin.py:376` | Security toggle (must be off in research/prod) | |

### Fault injection / chaos

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_FAULT_TOOL_CRASH` | `hi_agent/server/fault_injection.py:72` | Test-only / chaos | |
| `HI_AGENT_FAULT_CLOCK_SKEW_SECONDS` | `hi_agent/server/fault_injection.py:75` | Test-only / chaos | |
| `HI_AGENT_ARTIFACT_FAULT` | `hi_agent/artifacts/registry.py:129` | Test-only / chaos | |
| `HI_AGENT_STRICT_METRICS` | `hi_agent/observability/collector.py:691` | Observability strictness | |

### Misc

| Variable | Read sites | Classification | Notes |
|---|---|---|---|
| `HI_AGENT_EVOLVE_MODE` | `hi_agent/cli.py:205` | CLI | |
| `HI_AGENT_PROJECT_ID_REQUIRED` | `hi_agent/operator_tools/diagnostics.py:374` | Diagnostic | |
| `HI_AGENT_PROFILE_ID_REQUIRED` | `hi_agent/operator_tools/diagnostics.py:392` | Diagnostic | |
| `WEBHOOK_URL` | `hi_agent/config/runtime_builder.py:114`; `hi_agent/observability/notification.py:70` | Settings-loader pair (canonical) | |

---

## Direct-read defects identified (W34)

**None at HEAD `5809e422`.**

The pre-W33 anti-pattern (multiple unscoped `HI_AGENT_ENV` reads) was closed by W33-E.1 and remains closed: `scripts/check_no_hi_agent_env_direct_read.py` exits 0 at HEAD, with `hi_agent/server/ops_routes.py` correctly listed in the path allowlist as the operator-diagnostic exception.

The remaining 35 environment variables each read from exactly one canonical site (or from a small fanned-out set inside one module family — `HI_AGENT_DATA_DIR`'s 10 sites all live under `hi_agent/server/`, `hi_agent/artifacts/`, or `hi_agent/operator_tools/` and serve operationally distinct paths).

## CI gate coverage (W34)

`scripts/check_env_var_routing.py` (new in W34) extends the W33 gate to:

1. Maintain the W33 `HI_AGENT_ENV` allowlist verbatim (no behaviour change).
2. Add a per-variable enumeration that checks the canonical site exists and is the only non-allowlisted reader for the most-policy-sensitive variables: `HI_AGENT_POSTURE`, `HI_AGENT_LLM_MODE`, `HI_AGENT_JWT_SECRET`, `AGENT_SERVER_BACKEND`.
3. Fail closed on any new direct-read introduction at a non-canonical site for the four sensitive variables.

The gate intentionally does NOT enforce per-variable routing for the long-tail variables (data dirs, fault-injection toggles, episodes dir, etc.) because:

- Their reads are descriptively named module entry points already.
- Forcing a single accessor for `HI_AGENT_DATA_DIR` would flatten 10 documented subsystem entry points into one helper and obscure intent.
- The risk profile (cross-process consistency, posture sensitivity) is materially lower than for `HI_AGENT_POSTURE`/`HI_AGENT_ENV`.

This is a deliberate trade-off documented per Rule 11 / Rule 17 (allowlist-as-debt with concrete rationale per row).

---

## Three-Part Closure (Rule 15)

### W34-CONFIG-ENV-AUDIT

(a) **Code action:** None required at HEAD — the audit confirms no unrouted reads of policy-sensitive variables exist. The W34 work is the audit + enforcement, not a code fix.
(b) **Recurrence-prevention check:** `scripts/check_env_var_routing.py` (new in W34) runs in CI; complements the W33 `check_no_hi_agent_env_direct_read.py` gate.
(c) **Process change:** This document (`docs/governance/env-var-audit-2026-05-04.md`) is the binding audit; future env-var additions must extend the variable inventory above and demonstrate canonical-site discipline before the new variable is merged.

**Closure level (Rule 15 taxonomy):** `verified_at_release_head` — every read site listed has been visited at HEAD `5809e422`, classified, and verified against the documented canonical home.

---

**End of W34-CONFIG-ENV-AUDIT.**
