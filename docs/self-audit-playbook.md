# hi-agent Self-Audit Playbook

> **Purpose**: Permanent, mechanical checklist distilled from 8 rounds of downstream feedback (Round 1 → Round 7 + self-audit + 04-20 code review + 04-20 vulnerability analysis + 04-21 prod-mode incident). Every future PR, delivery package, or architectural change must pass the checks below before shipping.
>
> **Why this exists**: Across 7 external review rounds and one self-audit, ~70 distinct defects were found in a codebase that had ~3000 passing tests. Every round's defects fell into a small number of recurring patterns — but each pattern was caught individually, one-by-one, instead of mechanically. This playbook turns every historical pattern into a grep/test/command so that the 9th round has nothing to find.
>
> **Relationship to other docs**:
> - [CLAUDE.md](../CLAUDE.md) rules 0–8 — the AI engineering rules this playbook enforces
> - [docs/deployment-env-matrix.md](deployment-env-matrix.md) — authoritative env var list
> - [.github/workflows/smoke.yml](../.github/workflows/smoke.yml) — Rule-8 smoke matrix CI
> - [docs/self-audit-report-2026-04-21.md](self-audit-report-2026-04-21.md) — the first pass of this playbook run against the tree

---

## Part I — Why the same patterns keep recurring

8 structural causes that together explain ~70 defects across 8 rounds. Every PR should be gut-checked against these before writing code.

| # | Structural cause | Drives patterns |
|---|------------------|-----------------|
| S1 | Config flows through 4 layers (env → `TraceConfig` → `SystemBuilder` → subsystem builder) but env binding is implemented in only 3 of them per field; a new env reliably lands in docs + `TraceConfig` but gets dropped somewhere in the wiring. | P-1, P-11, P-20 |
| S2 | No contract between the four execution paths (`execute` / `execute_graph` / `execute_async` / `_execute_remaining`). Each hand-rolls try/except, finalization, session state, hook wrapping. Every feature drifts in 3 of 4. | P-2, P-3 | **Closed 2026-04-21**: `GraphFactory.from_stage_graph()` mirrors linear StageGraph into the async TrajectoryGraph so stage identity is shared; Anchor 7 passes all 4 exec modes. |
| S3 | Store factories proliferate without a registry. Each new subsystem builds its own `LongTermMemoryGraph` / `ShortTermMemoryStore` instance; there is no per-profile cache. New consumers reliably produce new duplication bugs. | P-4 | **Closed 2026-04-21**: MemoryBuilder caches per (method, profile_id, workspace_key); in-tree builder sites route through `build_raw_memory_store(...)` / `build_long_term_graph(...)`. |
| S4 | Features land in two PRs: "add capability" then "wire it in". PR2 frequently gets skipped or partially merged (`record_attempt`, `warm_index_async`, `mid_term_store` param, `LongTermConsolidator` autotrigger). | P-6 |
| S5 | Exception discipline is advisory, not mechanical. Rule 5 "Error visibility" is a review checklist item; no lint/grep rule enforces "every `except Exception` on an execution path has a typed re-raise upstream". | P-5, P-2 |
| S6 | Security defaults optimize for dev convenience, not threat model. Dev-smoke clamps, claims-only JWT, auto-registered `shell_exec`, payload-supplied `base_dir`, unvalidated `base_url`. The posture assumes the caller always configures tight. | P-18, P-19, P-25 |
| S7 | Lifecycle ownership unclear — "who closes the file / cancels the task / flushes the buffer?" is decided per-class, not by a shared lifecycle contract. | P-7, P-13 |
| S8 | Tests are written **after** defects are found, per-defect, not per-journey. 2995 passing tests did not catch 38 self-audit defects because none of them exercised a full `execute → gate → resume → complete` journey. | P-23 |

---

## Part II — Recurring defect patterns (the "Top 25")

Each pattern below has a representative incident, the root cause class, and a canonical detection command. Whenever reviewing a PR, scan the diff for any shape that matches the detection.

### Category A — Contract drift

| ID | Pattern | Rounds | Representative incident | Detection |
|----|---------|--------|-------------------------|-----------|
| P-9 | HTTP path mismatch between `kernel_facade_client.py` and `agent_kernel/service/http_server.py` | Rule 7 incident 04-19 | `/runs/start` (client) vs `/runs` (server) → 100% POST /runs failure on prod deploy | `grep -rn "_http_post\|_http_get" hi_agent/runtime_adapter/kernel_facade_client.py` vs `grep -rn "Route(" agent_kernel/service/http_server.py` → side-by-side table, every row ✅ |
| P-10 | httpx/urllib absolute path overrides `base_url`'s path segment | 04-21 | `post("/v1/chat/completions")` with `base_url=.../v2` → httpx urljoin drops `/v2` → 404 on MaaS | `grep -rn 'post(\"/' hi_agent/llm/ hi_agent/runtime_adapter/` — every network call must compose URL via f-string from `base_url`, never pass absolute path |
| P-14 | Custom exception class with empty body but state encoded in message | R3 D-1 | `GatePendingError.gate_id` → AttributeError; callers parsed error message | `grep -rnP "class \w+Error\(\w*Exception\):\s*\n\s*(pass|\"\"\")" --include="*.py" hi_agent/` |
| P-15 | `reflect(N)` structurally identical to `retry(N)` in event log | R2 M-2, R3 D-2, R5 G-1 | `_decide()` always returned `action="retry"`; reflection prompt not threaded through | Integration test: reflect(N) event log must contain N `ReflectionPrompt` events with populated stage_id; retry(N) must not |

### Category B — Config binding

| ID | Pattern | Rounds | Representative incident | Detection |
|----|---------|--------|-------------------------|-----------|
| P-1 | Env var declared in docs / `TraceConfig` but never read anywhere | 04-21; R7 I-4/I-8 | `HI_AGENT_KERNEL_BASE_URL` declared but `AgentServer` built `TraceConfig()` not `from_env()` → always "local" | `grep -rohE "HI_AGENT_[A-Z_]+" --include="*.md" docs/ README.md CLAUDE.md` vs `grep -rohE "HI_AGENT_[A-Z_]+" --include="*.py" hi_agent/` → must match |
| P-11 | Dev-only clamp / feature flag leaking into real-credential case | 04-21 | `dev-smoke` → `timeout=min(3, timeout)` unconditional; killed real LLM (10-13s latency) | `grep -rn "min(self._timeout\|max_retries *= *0" hi_agent/` — each hit gated on env AND credential absence |
| P-20 | Documentation claim diverges from code reality | 04-20 review §3.3 | `compat_sync_llm=False` documented as "async default" but openai branch still built sync `HttpLLMGateway` | For every architectural claim in CLAUDE.md / docstrings, grep the claimed class/method; assert behavior matches |

### Category C — State consistency

| ID | Pattern | Rounds | Representative incident | Detection |
|----|---------|--------|-------------------------|-----------|
| P-2 | Fix-then-miss cascade: fix applied in `execute()` but missed in `execute_graph`/`execute_async`/`_execute_remaining`/failure-handler branches | R4 F-1 → R5 G-4 → J2-1/J3-1/J4-1 | `GatePendingError` handled in `execute` but re-swallowed in 4 other paths | `grep -rn "except Exception" hi_agent/runner.py hi_agent/execution/` — each hit must have a sibling `except GatePendingError: raise` above it |
| P-4 | Instance duplication — same store class constructed from N builders without per-profile cache | R4 F-2 → R5 G-5 → R7 I-7 → J7-1 | `LongTermMemoryGraph` built in 4 places; profile scoping missed in 3 | `grep -rn "LongTermMemoryGraph(\|ShortTermMemoryStore(\|MidTermMemoryStore(\|RawMemoryStore(" hi_agent/config/` → every site reuses shared instance or threads `profile_id=` |
| P-8 | Runtime ID falling back to semantic label | Rule 5 / Rule 8 incidents | `run_id='default'` duplicated across sequential POST /runs | `grep -rn "run_id=['\"]default\|run_id=['\"]trace\|stage_id=['\"]default" hi_agent/ agent_kernel/` → must be empty |
| P-17 | File-path key not sanitizing `/`, `\`, `..` | R7 I-6 | Reflection session_id `"{run}/reflect/{stage}/{attempt}"` contained `/` → `_memory_path` created subdirectory → save silently failed | Every `_path(session_id)` / `_path(key)` helper must sanitize path-traversal characters before filesystem use |
| P-22 | Private field access (`._nodes`, `._cache`) across module boundaries | 04-20 §4.4 | `graph._nodes` read directly from 5 modules despite public `iter_nodes()` existing | `grep -rn "\._nodes\|\._edges\|\._tf\|\._df\|\._cache" hi_agent/` outside the owning class |

### Category D — Lifecycle completeness

| ID | Pattern | Rounds | Representative incident | Detection |
|----|---------|--------|-------------------------|-----------|
| P-3 | Sync/async parity missing — async mode skips finalization, hook wrapping, session state | R5 G-1, R7 I-1, J3-2/3/4, 04-20 §3.1 | `execute_async()` never called `_finalize_run()`; hooks bypassed | Diff body of `execute()` vs `execute_async()` line-by-line; `grep -rn "asyncio.get_event_loop\|asyncio.run" hi_agent/ --include="*.py"` outside `async_bridge.py` = suspect |
| P-6 | Method added but never wired (stub-to-production gap) | R3 D-3/4, R6 H-1/3, R7 I-7, 04-20 §3.4 | `record_attempt()` on RestartPolicyEngine — never called; `warm_index_async()` — zero call sites; `mid_term_store` ctor param — missing | For every public method added in a PR: `grep -rn "\.METHOD_NAME(" --include="*.py" hi_agent/` must show call sites outside `tests/` |
| P-7 | Resource / file-handle / task lifecycle incomplete | R2 M-1, R6 H-2/4, J8-1/J9-2 | `RawMemoryStore` file never closed; reflection `create_task` never cancelled; L0 JSONL not flushed before L0Summarizer reads | `grep -rn "open(\|loop.create_task\|asyncio.ensure_future" hi_agent/` — each hit has matching close/cancel reachable from teardown |
| P-13 | Class with persisted file does not auto-load in `__init__` | R2 H-2 | `LongTermMemoryGraph.__init__` started empty; forgetting `load()` caused silent data loss on next save | Every persistence class must `self.load()` (or equivalent) when the file exists |
| P-16 | Return value generated but not consumed (driver-result alignment) | R3 D-3, 04-20 §4.3 | `_finalize_run` extracted DailySummary but `mid_term_store` was None; `mid_term.py:197-228` returned `summaries[:days]` where `summaries` only defined in a sibling branch → NameError | Every non-None return value traced to a caller; every return path of a function uses the same variable name |

### Category E — Error visibility

| ID | Pattern | Rounds | Representative incident | Detection |
|----|---------|--------|-------------------------|-----------|
| P-5 | Exception swallowed silently; typed error degraded to generic `except Exception` | R4 F-1, R5 G-3/4, 04-21 | `execute_async()` converted `GatePendingError` → `status="failed"`; kernel-adapter build failure hidden by `try/except: pass` → CPU idle, no log | `grep -rnPA2 "except Exception" hi_agent/runner.py hi_agent/execution/ hi_agent/server/` — each must re-raise, log at ERROR, or convert to typed failure |
| P-24 | Blocking `time.sleep` in async-adjacent module | 04-20 §3.3 | `HttpLLMGateway.failover` used `time.sleep(delay)` — blocked event loop when invoked from async | `grep -rn "time.sleep" hi_agent/llm/ hi_agent/execution/ hi_agent/server/` → must be `asyncio.sleep` in async modules |

### Category F — Observability

| ID | Pattern | Representative incident | Detection |
|----|---------|-------------------------|-----------|
| P-21 | Big-file monolith; partial router extraction leaves hybrid state | `server/app.py` ~2250 LoC with extracted routers AND inline `_handle_*` | `wc -l hi_agent/server/app.py` trend must be downward; `grep -c "_handle_" hi_agent/server/app.py` |
| (N/A) | `/health` or `/ready` reflects cached / placeholder state instead of truth | 04-21 `kernel_adapter: not_built` shown even when adapter built | `grep -rn 'status.*not_built\|status.*unknown' hi_agent/server/` — any literal match must be justified or removed |

### Category G — Security boundary

| ID | Pattern | Representative incident | Detection |
|----|---------|-------------------------|-----------|
| P-18 | Default-permit security posture | vuln H-1/2/3/6: `ENFORCE_JWT_SIGNATURE=false` default; `CapabilityInvoker(policy=None)` permitted; `shell_exec` auto-registered; `file_write.prod_enabled_default=True` | `grep -rn 'prod_enabled_default\|requires_approval\|ENFORCE_\|policy.*=.*None' hi_agent/` |
| P-19 | Network base_url / redirect unvalidated (SSRF) | vuln H-4/5: `KernelFacadeClient.base_url` accepts any URL; `web_fetch` urllib auto-follows redirects | `grep -rn "urlopen\|httpx\|urllib.request" hi_agent/` — each must apply `URLPolicy` or be loopback-allowlist-only |
| P-25 | `base_dir` for file tools sourced from user payload | vuln H-6: `file_write`: `base_dir = Path(payload.get("base_dir", ".")).resolve()` | `grep -rn 'payload.get.*base_dir\|payload\[.base_dir.\]' hi_agent/capability/` |

### Category H — Performance

| ID | Pattern | Representative incident | Detection |
|----|---------|-------------------------|-----------|
| P-12 | Keyword-overlap search where semantic recall is required | R2 H-1: `LongTermMemoryGraph.search()` — word intersection; "attention mechanism" missed "multi-head self-attention" | Any `def search / def recall` in memory/knowledge modules must document algorithm class and expose injection point |

### Category I — Testing

| ID | Pattern | Representative incident | Detection |
|----|---------|-------------------------|-----------|
| P-23 | No user-journey integration test; only per-defect unit tests | Self-audit Root Cause E: all 38 defects found with 2995 passing tests | `grep -rln 'test_journey_\|test_e2e_' tests/` — ≥1 per exec mode |

---

## Part III — The Pre-Delivery Checklist (40 YES/NO questions)

Run all 40 before every delivery package. Any NO is a blocker.

### A. Contract truth
1. Every `_http_post/_http_get(path)` in `kernel_facade_client.py` matched 1:1 to a `Route(path, method)` in `agent_kernel/service/http_server.py`? **Attach the side-by-side table to the PR.**
2. Custom exceptions used for control flow carry typed attributes (not message-string parsing)?
3. Every public method added has ≥1 call site outside `tests/`?
4. Every non-None return value traced to a consumer?

### B. Config binding
5. Every env var read in code appears in (i) `TraceConfig` (ii) `README` env table (iii) `docs/deployment-env-matrix.md`?
6. Every `HI_AGENT_*` declared in docs actually read by some `os.getenv(...)` or `TraceConfig.from_env`?
7. Dev-only clamps gated on env OR credential absence — never unconditional?
8. `prod_enabled_default` / `requires_approval` / `ENFORCE_*` defaults favor secure mode?

### C. State consistency
9. For every `*Store` / `*Graph` / `*Engine`: ≤1 instance per `profile_id` across all builders?
10. `profile_id` threaded through every constructor that writes to disk (never empty default)?
11. Runtime IDs from caller or `uuid.uuid4()` — never fallback to `"default"` / `"trace"` / semantic labels?
12. Path keys sanitize `/`, `\`, `:`, `\0`, `..` before filesystem use?

### D. Lifecycle completeness
13. Every `open()`, `loop.create_task()`, `asyncio.ensure_future()` has a matching close/cancel reachable from teardown?
14. Every persistence class auto-loads in `__init__` when file exists?
15. `_finalize_run()` reachable on all exit paths (success/failure/gate/cancel) for `execute`, `execute_graph`, `execute_async`, `_execute_remaining`?
16. Files flushed and closed before any downstream reader reads them?

### E. Error visibility & sync-async parity
17. Every `except Exception` on execution paths preceded by matching `except GatePendingError: raise` (and other typed control-flow errors)?
18. No silent `except Exception: pass` — every catch re-raises, logs at ERROR, or converts to typed failure?
19. Diff of `execute()` vs `execute_async()` shows feature parity (finalization, gates, hooks, session state)?
20. No `asyncio.get_event_loop() + asyncio.run()` forking outside `async_bridge.py`?
21. No `time.sleep()` in `hi_agent/llm/ hi_agent/execution/ hi_agent/server/`?

### F. Testing
22. ≥1 journey-level integration test per exec mode (`execute`, `execute_graph`, `execute_async`, `resume`, `RunExecutorFacade`)?
23. `pytest -m integration` passes with zero internal mocks?
24. Rule-8 smoke (import gate + 3 sequential distinct run_ids + run-to-terminal ≤60s) passes in clean env?
25. Test compares `reflect(N)` vs `retry(N)` event logs — proves they differ?

### G. Observability
26. Every `create_task()` has an error callback that logs at ERROR?
27. `/health`, `/ready`, `/diagnostics`, `/doctor` reflect real subsystem state (no cached `not_built` when built)?
28. Startup logs kernel-adapter construction outcome (success → INFO + endpoint; failure → ERROR + traceback, fail-fast)?

### H. Security
29. `base_dir` for file tools sourced from `WorkspaceKey` / `TenantContext`, never from request payload?
30. `base_url` for any HTTP client applied to `URLPolicy` or explicit allowlist (loopback + configured host)?
31. `web_fetch` disables redirect auto-follow; each `Location` re-validated?
32. `shell_exec` default-off; requires explicit env flag AND approval AND `shell=False` + argv allowlist?
33. `ENFORCE_JWT_SIGNATURE=true` default; claims-only JWT requires explicit test-only env flag?
34. `CapabilityInvoker` default-deny without policy (or returned wrapped in `GovernedToolExecutor`)?

### I. Performance & architecture
35. No `ThreadPoolExecutor(max_workers=1)` in request hot path — use `AsyncBridgeService`?
36. Private fields (`._nodes`, `._cache`) accessed only inside owning class?
37. `RetrievalEngine.warm_index_async()` / `mark_index_dirty()` called from lifecycle hooks (startup; after ingest/consolidate)?
38. Server `app.py` LoC trend not growing vs previous commit?

### J. Documentation
39. Every class/method name referenced in CLAUDE.md / module index exists in code and behaves as described?
40. "Async by default" claims provable: `compat_sync_*=False` path instantiates the async class?

---

## Part IV — Mechanical audit commands

Copy-paste runnable. Keep one master script in `scripts/self_audit.sh`; below is the canonical set.

```bash
# ---- A. Contract truth ----

# A1. HTTP contract: client paths vs server routes
grep -rn "_http_post\|_http_get" hi_agent/runtime_adapter/kernel_facade_client.py \
  | sed -nE 's/.*_http_(post|get)\(["'"'"']([^"'"'"']+).*/\1 \2/p' | sort -u > /tmp/client_paths.txt
grep -rn "Route(" agent_kernel/service/http_server.py \
  | sed -nE 's/.*Route\(["'"'"']([^"'"'"']+)["'"'"'], *["'"'"']([^"'"'"']+).*/\2 \1/p' | sort -u > /tmp/server_routes.txt
diff /tmp/client_paths.txt /tmp/server_routes.txt

# A2. Empty exception class carrying runtime state
grep -rnP "class \w+Error\(\w*Exception\):\s*\n\s*(pass|\"\"\")" --include="*.py" hi_agent/

# ---- B. Config binding ----

# B1. Env vars: code vs docs
grep -rohE "HI_AGENT_[A-Z_]+" --include="*.py" hi_agent/ agent_kernel/ | sort -u > /tmp/env_in_code.txt
grep -rohE "HI_AGENT_[A-Z_]+" --include="*.md" docs/ README.md CLAUDE.md | sort -u > /tmp/env_in_docs.txt
diff /tmp/env_in_code.txt /tmp/env_in_docs.txt

# B2. Unconditional dev clamps
grep -rn "min(self._timeout\|max_retries *= *0" hi_agent/

# B3. Every TraceConfig field is consumed somewhere
python -c "from hi_agent.config.trace_config import TraceConfig; import dataclasses; \
  [print(f.name) for f in dataclasses.fields(TraceConfig)]" > /tmp/cfg_fields.txt
while read f; do grep -rln "config\.$f\|cfg\.$f\|self\._config\.$f" hi_agent/ >/dev/null || echo "UNUSED: $f"; done < /tmp/cfg_fields.txt

# ---- C. State consistency ----

# C1. Store construction sites — must be ≤1 per profile_id per class
grep -rn "LongTermMemoryGraph(\|ShortTermMemoryStore(\|MidTermMemoryStore(\|RawMemoryStore(" hi_agent/config/ hi_agent/

# C2. Hardcoded semantic IDs
grep -rn "run_id=['\"]default\|run_id=['\"]trace\|stage_id=['\"]default" hi_agent/ agent_kernel/

# C3. Path sanitization
grep -rn "def _memory_path\|def _session_path\|def _path" hi_agent/memory/

# ---- D. Lifecycle completeness ----

# D1. Unmanaged open()
grep -rn "= *open(" hi_agent/ --include="*.py"

# D2. Untracked create_task
grep -rn "loop.create_task\|asyncio.ensure_future" hi_agent/ --include="*.py"

# D3. _finalize_run call sites — must cover every exec mode
grep -rn "_finalize_run(" hi_agent/runner.py hi_agent/executor_facade.py hi_agent/execution/

# ---- E. Error visibility & parity ----

# E1. except Exception without re-raise or log
grep -rnPA2 "except Exception" hi_agent/runner.py hi_agent/execution/ hi_agent/server/

# E2. Missing GatePendingError guard in execution paths
for f in hi_agent/runner.py hi_agent/executor_facade.py hi_agent/execution/*.py; do
  grep -l "except Exception" "$f" 2>/dev/null | while read g; do
    grep -l "except GatePendingError" "$g" >/dev/null || echo "  ^ missing gate guard: $g"
  done
done

# E3. Async event loop anti-patterns outside async_bridge
grep -rn "asyncio.get_event_loop\|asyncio.run" hi_agent/ --include="*.py" | grep -v async_bridge

# E4. Blocking sleep in async-adjacent modules
grep -rn "time.sleep" hi_agent/llm/ hi_agent/execution/ hi_agent/server/

# ---- F. Testing ----

# F1. Journey-level integration tests
find tests -name "test_journey_*" -o -name "test_e2e_*" | head

# F2. reflect vs retry differentiated
grep -rn "ReflectionPrompt" tests/ --include="*.py"

# ---- G. Observability ----

# G1. Background task error callbacks
grep -rn "create_task(" hi_agent/ | head

# G2. Cached placeholder state in readiness
grep -rn "status.*not_built\|status.*unknown" hi_agent/server/

# ---- H. Security ----

# H1. Unvalidated base_url
grep -rn "base_url *=" hi_agent/runtime_adapter/ hi_agent/llm/ hi_agent/capability/

# H2. payload-sourced base_dir
grep -rn "payload.get.*base_dir\|payload\[.base_dir.\]" hi_agent/capability/

# H3. Default-permit flags
grep -rn "prod_enabled_default *= *True\|ENFORCE_JWT.*false\|policy *= *None" hi_agent/

# H4. shell=True
grep -rn "shell=True" hi_agent/ agent_kernel/

# H5. web_fetch redirect policy
grep -rn "urllib.request.build_opener\|httpx\.AsyncClient\|httpx\.Client" hi_agent/capability/

# ---- I. Performance ----

# I1. Legacy thread pool in hot path
grep -rn "ThreadPoolExecutor(max_workers=1)" hi_agent/execution/ hi_agent/runner.py

# I2. Private field access outside owning class
grep -rn "graph\._nodes\|store\._tf\|engine\._cache" hi_agent/ --include="*.py"

# ---- J. Documentation ----

# J1. Classes referenced in CLAUDE.md exist
grep -oE "\`[A-Z][a-zA-Z0-9_]+\`" CLAUDE.md | sort -u | while read cls; do
  name=$(echo $cls | tr -d '\`')
  grep -rln "class $name" hi_agent/ agent_kernel/ >/dev/null || echo "MISSING CLASS: $cls"
done
```

---

## Part V — Permanent regression anchors (smoke tests)

Every delivery package must pass these 13 anchors in a clean environment. Failures map to a specific past incident; a regression means that incident has come back.

| # | Anchor | Scenario | Incident it guards |
|---|--------|----------|--------------------|
| 1 | **Kernel HTTP contract** | `POST /runs` → 200/201 with `{run_id, state}` | 04-19: `/runs/start` 405 |
| 2 | **Sequential run_id uniqueness** | 3 sequential POST /runs → 3 distinct run_ids | 04-19: `run_id='default'` dup |
| 3 | **Run reaches terminal ≤60s** | POST /runs → poll `/runs/{id}` → state ∈ {done, failed} within 30×2s | 04-21: prod worker not starting |
| 4 | **Import gate** | `python -c "import hi_agent; import agent_kernel"` exits 0 with no output | 04-11: 17× Py2 syntax, 12× UTF-8 BOM |
| 5 | **Non-/v1 LLM provider** | `AsyncHTTPGateway(base_url=".../v2")` → request URL ends `/v2/chat/completions` | 04-21: httpx absolute path 404 |
| 6 | **Dev-smoke clamp gated** | `HI_AGENT_ENV=dev-smoke` + real `OPENAI_API_KEY` → timeout ≥ 30s, retries ≥ 1 | 04-21: unconditional 3s clamp |
| 7 | **Gate escape across all exec modes** | Register gate; call `execute`, `execute_graph`, `execute_async`, `_execute_remaining` → `GatePendingError` escapes with `e.gate_id` populated | R4 F-1 → J2-1/J3-1/J4-1 |
| 8 | **reflect(N) ≠ retry(N)** | Force-fail under `restart_policy="reflect(2)"` → event log has 2 `ReflectionPrompt` events with real stage_id (not "unknown") | R3 D-2 |
| 9 | **Profile isolation** | Two concurrent runs with `profile_id="A"` / `profile_id="B"` → zero cross-contamination in `profiles/A/` vs `profiles/B/`; knowledge graph for A is not the same object as for B | R4 F-2 → J7-1 |
| 10 | **Checkpoint resume preserves state** | Execute 2/5 stages → checkpoint → kill → resume → stages 1-2 not re-run; `_stage_attempt` preserved; L0 appended; `profile_id` intact; gate_pending preserved | J5-1..4 |
| 11 | **L0 flushed before summarization** | Run with L0 events → finalize → `L0Summarizer` sees all events (no tail truncation) | R6 H-4 |
| 12 | **Default-deny security** | Without `HI_AGENT_JWT_SECRET`: unsigned JWT `role=admin` rejected; in default profile `GET /tools/list` excludes `shell_exec` | vuln H-1, H-2 |
| 13 | **base_url SSRF allowlist** | `KernelFacadeClient(base_url="http://169.254.169.254")` rejected; same for `file://`, other private-range IPs outside allowlist | vuln H-4 |

Implementation status: Anchors 1, 2, 3, 4 covered by [`.github/workflows/smoke.yml`](../.github/workflows/smoke.yml). Anchors 5, 6 covered by [`tests/test_http_gateway_base_url.py`](../tests/test_http_gateway_base_url.py). Anchors 7–13 still need dedicated journey tests — tracked as future work in the audit report.

---

## Part VI — How to use this playbook

1. **Before writing code** — skim Parts I and II. Recognize whether the task you're about to do has a pattern match; if so, the solution likely already exists, don't rebuild it.
2. **During PR review** — run Part IV commands against the diff; every NO in Part III is a blocker comment.
3. **Before a delivery package** — run all 13 anchors in Part V against a clean environment; attach output to the delivery handoff doc.
4. **After each new downstream review round** — if a new defect pattern appears that isn't in Part II, add it; if a new root cause appears that isn't in Part I, add it. This document is append-only, maintained by the round-by-round survivors.

## Part VII — Governance & update policy

- **Append-only**: Never remove a pattern or anchor — patterns already found tend to recur. Mark historical items with "superseded" if replaced by a mechanical enforcement (lint rule, CI test), but don't delete.
- **Owner on call**: Whoever ships a fix for a novel downstream defect is responsible for adding the corresponding pattern row and detection command to this playbook in the same PR.
- **CI wiring**: Where possible, promote a Part IV grep command into a ruff/flake8 rule or a lint script. The goal is to make every NO in Part III be mechanically detectable, not manually reviewed.
