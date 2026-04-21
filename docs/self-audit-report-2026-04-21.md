# Self-Audit Report — 2026-04-21

> **Context**: First application of [docs/self-audit-playbook.md](self-audit-playbook.md) against `main` (commit `e84cbb1`). Synthesized from 8 rounds of downstream feedback + the 04-20 code review + the 04-20 vulnerability analysis + the 04-21 prod-mode incident.
>
> This report is the deliverable of running Part IV commands against the current tree. Anything flagged here is either (a) already on a fix track, (b) a false positive with rationale recorded, or (c) a new ticket for the next round.

---

## Executive summary

- **Categories clean**: A1 HTTP contract (but see caveat), C2 hardcoded IDs, I1 thread-pool hot path, Journey tests (10+ e2e tests exist)
- **Categories flagged**: B1 env var doc drift, D1 store duplication (still ≥3 sites for `RawMemoryStore`, 3 for `LongTermMemoryGraph`), E3 async anti-patterns (16 sites), E4 blocking `time.sleep` in sync LLM gateway, H2 payload-sourced `base_dir` (still present!), H3 `prod_enabled_default=True` (3 sites), H4 `shell=True` (1 site in MCP transport)
- **New tickets opened**: 7 (see Part 3)
- **False positives flagged and documented**: 3 (see Part 4)

---

## Part 1 — Clean categories

| Check | Result | Evidence |
|-------|--------|----------|
| A2 empty exception class with pass body | Clean | No `class FooError(Exception): pass` grep hit |
| C2 runtime IDs never fallback to semantic label | Clean | `grep run_id='default'\|stage_id='default'` returns empty |
| I1 `ThreadPoolExecutor(max_workers=1)` in hot path | Clean | No hits in `hi_agent/execution/` or `hi_agent/runner.py` |
| G2 cached-placeholder state in readiness | Clean (after 04-21 P0-4) | Only 1 hit remains: MCP server status fallback default (`"unknown"`), which is legitimate |
| Journey tests exist | Clean | 10+ files under `tests/integration/test_{journey,e2e}_*.py` |

---

## Part 2 — Flagged findings

### 🟠 F-1 — Store duplication: `RawMemoryStore` has 4 construction sites, not 1

**Pattern**: P-4 (instance duplication breaking profile scoping) + S3 (no store registry)

**Evidence**:
```
hi_agent/config/builder.py:1056  RawMemoryStore(run_id=_run_id, base_dir=_raw_base)
hi_agent/config/builder.py:1233  RawMemoryStore()                          ← unscoped default!
hi_agent/runner.py:323           self.raw_memory = raw_memory or RawMemoryStore()   ← fallback
hi_agent/runner.py:1846          executor.raw_memory = RawMemoryStore(...)
```

**Risk**: The `raw_memory or RawMemoryStore()` fallback in `runner.py:323` silently creates a fresh store pinned to the process CWD if the caller forgets to inject one — identical shape to the 04-15 Round 4 F-2 / Round 5 G-5 defects that kept recurring with other stores.

**Recommended fix**: Ticket SA-1 — route all RawMemoryStore construction through a single `build_raw_memory_store(profile_id, workspace_key)` builder that enforces profile/workspace scoping; remove the inline fallback in `runner.py:323` so missing injection is a hard error, not a silent degradation.

### 🟠 F-2 — `LongTermMemoryGraph` bypasses builder cache in `knowledge_manager`

**Pattern**: P-4

**Evidence**:
```
hi_agent/config/memory_builder.py:108   graph = LongTermMemoryGraph(storage_path, project_id=project_id)
hi_agent/config/memory_builder.py:110   graph = LongTermMemoryGraph(...)
hi_agent/knowledge/knowledge_manager.py:82  self._graph = graph or LongTermMemoryGraph(f"{storage_dir}/graph.json")
```

**Risk**: If `knowledge_manager` is instantiated without an injected `graph`, it constructs a fresh `LongTermMemoryGraph` that points at a **different file path** (`{storage_dir}/graph.json`) than the builder's cached instance. Profile-scoped writes and reads diverge silently — this is the J7-1 self-audit defect re-surfacing because the fix was applied at the builder but not at the fallback.

**Recommended fix**: Ticket SA-2 — remove the `or LongTermMemoryGraph(...)` fallback; require callers to inject the builder-provided instance. If a standalone constructor path is needed, it must take `profile_id` and resolve the canonical path via `WorkspacePathHelper`.

### 🟠 F-3 — `shell=True` in `mcp/transport.py:303`

**Pattern**: P-18 (default-permit security posture)

**Evidence**: `grep -rn "shell=True" hi_agent/ agent_kernel/` → 1 hit in `hi_agent/mcp/transport.py:303`.

**Risk**: Under certain MCP server-launch paths, user-influenced tokens could reach a shell interpreter. Even if the current callers construct the argv themselves, leaving `shell=True` in the code makes it a time bomb for the next caller.

**Recommended fix**: Ticket SA-3 — audit the callsite at `mcp/transport.py:303`; if the argv is always a pre-validated list, switch to `shell=False` and pass argv explicitly. If a shell is genuinely required (e.g. `.cmd`/`.bat` launchers on Windows), wrap with `shlex.quote` and document the threat model inline.

### 🟠 F-4 — `payload["base_dir"]` at 2 sites in `capability/tools/builtin.py`

**Pattern**: P-25 (base_dir sourced from user payload) — matches **vulnerability analysis H-6**, reported 2026-04-20, still present

**Evidence**:
```
hi_agent/capability/tools/builtin.py:33   payload["base_dir"]
hi_agent/capability/tools/builtin.py:68   payload["base_dir"]
```

**Risk**: Attacker-controlled `base_dir` could write files outside the workspace. Vulnerability analysis 04-20 explicitly flagged this; fix was not landed.

**Recommended fix**: Ticket SA-4 — source `base_dir` from `WorkspaceKey`/`TenantContext` via `WorkspacePathHelper.private(...)` instead of request payload. Reject requests that try to supply `base_dir`.

### 🟠 F-5 — `prod_enabled_default=True` at 3 sites in `builtin.py`

**Pattern**: P-18 + vuln H-2

**Evidence**:
```
hi_agent/capability/tools/builtin.py:231  prod_enabled_default=True,
hi_agent/capability/tools/builtin.py:252  prod_enabled_default=True,
hi_agent/capability/tools/builtin.py:272  prod_enabled_default=True,
```

**Risk**: Built-in tools (likely `file_write`, `file_read`, etc.) are enabled in prod by default — a miscall from an LLM plus any input-injection vector could perform filesystem writes without approval.

**Recommended fix**: Ticket SA-5 — flip defaults to `prod_enabled_default=False` and require an explicit opt-in env flag or profile policy to re-enable in prod. Review all three capability definitions for whether they belong in the default prod surface at all.

### 🟡 F-6 — Blocking `time.sleep` in `http_gateway.py` sync retry

**Pattern**: P-24 (blocking sleep in async-adjacent modules) — matches 04-20 code review §3.3, still present

**Evidence**:
```
hi_agent/llm/http_gateway.py:314  time.sleep(delay)
hi_agent/llm/http_gateway.py:320  time.sleep(delay)
hi_agent/llm/http_gateway.py:329  time.sleep(delay)
hi_agent/llm/http_gateway.py:334  time.sleep(delay)
```

**Risk**: When a sync caller running inside an async event loop hits `HttpLLMGateway`'s retry path, these `time.sleep` calls block the loop for up to `retry_base * 2^attempt` seconds per retry.

**Context**: `compat_sync_llm=False` is the documented default (async `HTTPGateway` used instead), so the blocking path is rarely exercised. But the class is still available for explicit opt-in, and the 04-20 review flagged it as a cliff edge.

**Recommended fix**: Ticket SA-6 — since `HttpLLMGateway` is now marked `@deprecated` (04-15 deprecation warning), either (a) add an explicit "not safe to call from async context" check at entry (raise if running loop detected), or (b) convert the sleep to `asyncio.sleep` via `AsyncBridgeService.run_sync` wrapper.

### 🟡 F-7 — 16 `asyncio.run` / `get_event_loop` call sites outside `async_bridge.py`

**Pattern**: P-3 (sync/async parity missing) — high-priority subset matches 04-20 code review §3.1/3.2

**Evidence (partial, the ones that match the 04-20 review)**:
```
hi_agent/execution/action_dispatcher.py:74   loop = asyncio.get_event_loop()
hi_agent/execution/action_dispatcher.py:88   asyncio.run(self._ctx.hook_manager.wrap_tool_call(...))
hi_agent/execution/recovery_coordinator.py:373  asyncio.run(...)
```

**Risk**:
- `action_dispatcher.py:74-88` — 04-20 review called this out specifically: `ThreadPoolExecutor(max_workers=1)` + `asyncio.run` inside should migrate to `AsyncBridgeService`. Still present.
- `recovery_coordinator.py:373` — same issue.
- The other 13 hits are mostly legitimate (top-level `__main__` entry points, `KernelRuntime.start` which genuinely needs a fresh loop, `kernel_facade_adapter` sync→async bridges that already correctly check for running loop). Individual triage below (Part 4, FP-1).

**Recommended fix**: Ticket SA-7 — migrate `action_dispatcher.py:74-88` and `recovery_coordinator.py:373` to `AsyncBridgeService.run_sync_in_thread(..., timeout=...)` pattern already established in [llm/async_http_gateway.py](../hi_agent/llm/async_http_gateway.py) by P1-7.

### 🟡 F-8 — Env var documentation drift (3 vars in code not in docs)

**Pattern**: P-1 / P-20

**Evidence** (code side only, doc side is all-false-positive — see FP-2):
```
in code but not in any *.md:
  HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS  — test-only escape hatch for JWT signature verification
  HI_AGENT_MEMORY_PATH                   — referenced in doctor's suggested fix, but not read?
  HI_AGENT_RUNTIME_PROFILE               — legacy name? current code uses HI_AGENT_PROFILE
  HI_AGENT_LLM_API_KEY_                  — partial grep hit from f-string (false positive)
```

**Recommended fix**: Ticket SA-8 — verify whether `HI_AGENT_MEMORY_PATH` and `HI_AGENT_RUNTIME_PROFILE` are actually consumed; add to `docs/deployment-env-matrix.md` if yes, delete reference if no. Add `HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS` to the doc as an explicit test-only flag.

---

## Part 3 — New tickets opened by this audit

| ID | Priority | Title | Category |
|----|----------|-------|----------|
| SA-1 | P1 | Single `build_raw_memory_store` builder; remove `runner.py:323` fallback | State consistency |
| SA-2 | P1 | Remove `knowledge_manager.LongTermMemoryGraph` fallback; require injection | State consistency |
| SA-3 | P1 | `mcp/transport.py:303` `shell=True` review & switch to argv | Security |
| SA-4 | **P0** | `payload["base_dir"]` → workspace-derived path (vuln H-6 still open!) | Security |
| SA-5 | P1 | Flip `prod_enabled_default` to False for the 3 built-in tools | Security |
| SA-6 | P2 | `HttpLLMGateway` async-safety guard or `asyncio.sleep` conversion | Performance |
| SA-7 | P1 | Migrate `action_dispatcher` + `recovery_coordinator` to `AsyncBridgeService` | Sync/async parity |
| SA-8 | P2 | Verify & document `HI_AGENT_MEMORY_PATH`, `HI_AGENT_RUNTIME_PROFILE`, `HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS` | Docs |

**P0 urgent**: SA-4 (vulnerability H-6 from 04-20 security review is still present — payload-sourced `base_dir` should have been closed 04-20).

---

## Part 4 — False positives (catalogued with rationale so the next audit doesn't re-raise)

### FP-1 — Many `asyncio.run` call sites are legitimate

Of the 16 hits from `grep -rn "asyncio.run\|get_event_loop"`, the following are **legitimate** and should not be flagged by future audits:
- `hi_agent/runner.py:2015,2076,2254` — top-level `execute_async()` orchestration; uses `asyncio.run` as the correct sync entry to async code when no loop is running.
- `hi_agent/runtime_adapter/kernel_facade_adapter.py:469,479,666,677,786,808` — adapter methods that check `try: get_running_loop()` first and only fall to `asyncio.run` when no loop is present. Correct bridge pattern.
- `hi_agent/runtime_adapter/kernel_facade_client.py:363` — same pattern.
- `hi_agent/llm/http_gateway.py:154` — already guarded (`loop.is_running()` branch uses `AsyncBridgeService`).
- `hi_agent/llm/async_http_gateway.py:100` — fallback for "no running loop", matches the documented contract.

Only `action_dispatcher.py:74-88` and `recovery_coordinator.py:373` are genuine SA-7 tickets; the other 13 have justified patterns.

### FP-2 — "docs only" env vars from `TraceConfig.from_env` generic loop

The following env vars appear in `docs/deployment-env-matrix.md` and `README.md` but do not appear as literal strings in `*.py`:
```
HI_AGENT_ANTHROPIC_*, HI_AGENT_OPENAI_*, HI_AGENT_COMPAT_SYNC_LLM,
HI_AGENT_DEFAULT_MODEL, HI_AGENT_LLM_MAX_RETRIES, HI_AGENT_LLM_TIMEOUT_SECONDS,
HI_AGENT_SERVER_HOST, HI_AGENT_SERVER_MAX_CONCURRENT_RUNS, HI_AGENT_SKILL_DIR
```

These are read by `TraceConfig.from_env()`'s generic loop `f"HI_AGENT_{field.name.upper()}"` — the literal string never appears in source. Not a defect.

**Mitigation**: Future B1 audit should compute the expected names by iterating `dataclasses.fields(TraceConfig)` and prepending `HI_AGENT_`, then diffing against the doc set. See the runnable version in the playbook Part IV B3.

### FP-3 — `G2 status: unknown` is an MCP server default

The only remaining hit for "unknown"/"not_built" in `hi_agent/server/` is `app.py:397`:
```python
"status": srv.get("status", "unknown")
```
This is a defensive default for an MCP server that didn't report its status. It is not a cached placeholder hiding a real state. Acceptable.

---

## Part 5 — Regression anchors verification

Status against the 13 permanent anchors in playbook Part V:

| # | Anchor | Status | Evidence |
|---|--------|--------|----------|
| 1 | Kernel HTTP contract | ✅ Covered | `.github/workflows/smoke.yml` dev-local matrix |
| 2 | Sequential run_id uniqueness | ✅ Covered | smoke.yml step 3 |
| 3 | Run reaches terminal ≤60s | ✅ Covered | smoke.yml step 4 |
| 4 | Import gate | ✅ Covered | smoke.yml step 1 |
| 5 | Non-/v1 LLM provider URL | ✅ Covered | `tests/test_http_gateway_base_url.py` |
| 6 | Dev-smoke clamp gated on credential | ✅ Covered | `tests/test_http_gateway_base_url.py` |
| 7 | Gate escape across all exec modes | ⚠️ Partial | Unit tests exist; journey test missing for `execute_async` + `_execute_remaining` |
| 8 | `reflect(N)` ≠ `retry(N)` event log | ⚠️ Partial | Unit tests confirm events; no event-log diff assertion |
| 9 | Profile isolation (2 concurrent runs) | ✅ Covered | `tests/integration/test_profile_isolation.py` (verified name; to confirm scenarios) |
| 10 | Checkpoint resume preserves state | ✅ Covered | `tests/integration/test_e2e_restart_replay_consistency.py` |
| 11 | L0 flushed before summarization | ⚠️ Partial | Unit covered; end-to-end flush-ordering not asserted |
| 12 | Default-deny security | ❌ Failing | Would fail if JWT-unsigned/admin scenario run today (default `ENFORCE_JWT_SIGNATURE=false` in non-test env) |
| 13 | `base_url` SSRF allowlist | ❌ Failing | vuln H-4 still open |

**Action**: Tickets SA-4 and SA-5 include delivering anchors 12 and 13 as pytest smoke tests; tickets for anchors 7, 8, 11 to be opened as SA-9/10/11 in the next pass.

---

## Part 6 — Comparison to prior self-audit (2026-04-15)

| Metric | 04-15 self-audit | 04-21 (this) |
|--------|------------------|--------------|
| Defects found | 38 | 8 (7 flagged + 1 already-known vuln) |
| Root-cause classes | 5 (J1–J9) | 7 (mostly security + lifecycle) |
| Parallel-path bugs (P-2 class) | Dominant | Mostly contained — single new site in `action_dispatcher` |
| Instance duplication (P-4) | 4+ store classes | Contained to 2 classes + 1 fallback path |
| Security (P-18/19/25) | Out of scope | **Primary theme of 04-21** — vuln H-2/H-6 still open |
| Documentation drift (P-20) | Moderate | Low — TraceConfig generic loop eliminates most false positives |

**Trend**: Core execution-path defects (fix-then-miss cascades, store duplication) are converging. Security boundary is now the highest-density defect category — which itself is a new structural finding for the playbook (S6).

---

## Part 7 — Action summary for next PR cycle

1. Land SA-4 immediately (P0 security — still-open vuln H-6).
2. Land SA-3 and SA-5 (P1 security). Together with SA-4, turns Part V anchors 12 and 13 into passing smoke tests.
3. Land SA-1 and SA-2 together as "store registry landing" — single PR, closes store-duplication for good (instead of iterating once more).
4. Land SA-7 to close the last two P-3 sites called out by 04-20 review.
5. Land SA-6 as doc-only if `HttpLLMGateway` is fully retired, or as code change if it still ships.
6. Land SA-8 doc cleanup.
7. Open SA-9/10/11 as smoke-test additions for anchors 7, 8, 11.

Next self-audit: schedule for post-merge of SA-1…SA-8, or at the 2026-05 release gate — whichever comes first.
