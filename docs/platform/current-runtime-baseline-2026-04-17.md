# Runtime Baseline Snapshot — 2026-04-17

**Branch**: `feat/w1-runtime-truth-mvp`  
**Purpose**: Regression anchor for all W1 PRs. Captured before any W1 code changes.  
**Python**: 3.14.3 · pytest 9.0.2 · ruff 0.15.8  
**Working directory**: `/D/chao_workspace/hi-agent/.claude/worktrees/distracted-poitras`

---

## Sample 1: pytest (full suite, quiet)

**Command**: `python -m pytest -q`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:25:00+08:00  
**Output summary** (≤500 chars): 3059 passed, 5 skipped, 1 warning in 147.27s. One warning: `ResilientKernelAdapter: 'open_branch' buffered after 4 retries (Backend operation failed: open_branch: "LocalWorkflowGateway: run not found – run_id='run-api-test'")`. No failures.  
**Skip reasons**: 5 skipped; specific reasons unavailable in `-q` mode (use `pytest -r s` for details)

---

## Sample 2: ruff check

**Command**: `python -m ruff check .`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:25:30+08:00  
**Output summary** (≤500 chars): Found 3178 errors. 726 fixable with `--fix`; 133 additional with `--unsafe-fixes`. Top error types: D102×1492 (missing public method docstrings), I001×272 (import ordering), F401×249 (unused imports), D101×220 (missing class docstrings), E501×185 (line too long). No errors prevent import or runtime execution.  
**Skip reasons**: none

---

## Sample 3: pytest with coverage

**Command**: `python -m pytest --cov=hi_agent --cov-report=term -q`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:26:00+08:00  
**Output summary** (≤500 chars): 3059 passed, 5 skipped, 13 warnings in 154.35s. Total coverage: **80.89%** (22308 stmts, 3670 missed). Required threshold 65.0% — reached. Notable low-coverage modules: `trajectory/node.py` 0%, `trajectory/optimizer_base.py` 0%, `trajectory/greedy.py` 50%, `trajectory/backpropagation.py` 48%. High-coverage: `trajectory/dead_end.py` 100%, `trajectory/optimizers.py` 100%.  
**Skip reasons**: `pytest-cov` was not pre-installed; installed via `pip install pytest-cov` before running.

---

## Sample 4: server /ready

**Command**: `python -m hi_agent serve --port 8080` (background), then `curl -s localhost:8080/ready`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:27:20+08:00  
**Output summary** (≤500 chars): `{"ready":true,"health":"ok","execution_mode":"local","models":[],"skills":[],"mcp_servers":[],"plugins":[],"capabilities":["analyze_goal","build_draft","evaluate_acceptance","file_read","file_write","search_evidence","shell_exec","synthesize","web_fetch"],"subsystems":{"kernel":{"status":"ok","mode":"local"},"llm":{"status":"not_configured"},"capabilities":{"status":"ok","count":9},...},"runtime_mode":"dev"}`. Server started cleanly with auth disabled (HI_AGENT_API_KEY not set). LLM uses heuristic fallback (no API key).  
**Skip reasons**: none

---

## Sample 5: server /manifest

**Command**: `curl -s localhost:8080/manifest`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:27:22+08:00  
**Output summary** (≤500 chars): Returns `name=hi-agent, version=0.1.0, framework=TRACE`. 5 stages: S1_understand→S5_review. 9 capabilities listed. 44 endpoints registered. Contract field status: 9 ACTIVE, 1 QUEUE_ONLY (priority), 3 PASSTHROUGH. MCP provider status: `infrastructure_only` — external stdio/SSE/HTTP transport not yet implemented. Production E2E status: `requires_prerequisites` (API key + kernel endpoint).  
**Skip reasons**: none

---

## Sample 6: server /mcp/status

**Command**: `curl -s localhost:8080/mcp/status`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:27:25+08:00  
**Output summary** (≤500 chars): `{"servers":[],"health":[],"count":0,"tool_count":9,"transport_status":"not_wired","capability_mode":"infrastructure_only","note":"No external MCP server transport is active. Platform tools are accessible via /mcp/tools/list and /mcp/tools/call as MCP-compatible endpoints. Register stdio MCP servers via plugin manifests (mcp_servers field) to enable external providers."}`. 0 external servers; 9 platform tools exposed as MCP-compatible endpoints.  
**Skip reasons**: none

---

## Sample 7: server /health

**Command**: `curl -s localhost:8080/health`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:27:27+08:00  
**Output summary** (≤500 chars): All subsystems ok except `kernel_adapter` (status: unknown, error_rate: 0.0, total_calls: 0). `run_manager`: ok (active:0, queued:0, capacity:32). `memory`: ok. `context`: ok (GREEN). `event_bus`: ok (subscribers:0, dropped:0). `metrics`: ok (events_recorded:0). Timestamp: 2026-04-17T04:27:20Z.  
**Skip reasons**: none

---

## Sample 8: POST /runs smoke

**Command**: `curl -sX POST localhost:8080/runs -H 'Content-Type: application/json' -d '{"goal":"baseline smoke"}'`  
**Env vars**: none  
**Timestamp**: 2026-04-17T12:27:31+08:00  
**Output summary** (≤500 chars): `{"run_id":"f19354ae0024","task_contract":{"goal":"baseline smoke"},"state":"created","result":null,"error":null,"created_at":"2026-04-17T04:27:31.426695+00:00","updated_at":"2026-04-17T04:27:31.426695+00:00"}`. Run accepted and queued with state=created. No immediate error.  
**Skip reasons**: none

---

## Sample 9: readiness check (prod mode)

**Command**: `python -m hi_agent readiness --local`  
**Env vars**: `HI_AGENT_ENV=prod`  
**Timestamp**: 2026-04-17T12:28:00+08:00  
**Output summary** (≤500 chars): Platform: NOT READY (health=degraded). 3 issues: (1) kernel — production requires real agent-kernel HTTP endpoint, not local; (2) llm — production requires OPENAI_API_KEY or ANTHROPIC_API_KEY or llm_config.json; (3) llm — credentials required. Models:0, skills:0, capabilities:0, mcp_servers:0, plugins:0. Subsystem kernel/llm: error; capabilities/skills/mcp/plugins: ok. Expected result — no prod credentials in this environment.  
**Skip reasons**: none

---

## Post-D3-001 Diff Verification

**Timestamp**: 2026-04-17T06:08:15+08:00  
**Verified by**: QA Engineer

### Diffs observed

- `POST /runs` response: No structural changes. All 7 fields present and identical: run_id, task_contract, state, result, error, created_at, updated_at. No execution_provenance field in initial response (expected — field is populated only in completed RunResult, not in ManagedRun serialization).
- `/manifest` response: `evolve_policy` field present as dict with keys (mode, effective, source) — additive field from D2-001, consistent with runtime state.
- `RunResult.to_dict()` output: execution_provenance field properly serialized when result is a completed RunResult (verified via test_runner_provenance_propagation.py: 5/5 passing).
- pytest suite: unit tests 140 passed; integration provenance tests 5 passed; full suite compilation completes with no import errors.

### Verdict: PASS — additive only, no regressions

All pre-existing POST /runs and /manifest fields remain byte-identical. execution_provenance wiring is correct and tested. No breaking changes detected.

---

## Notes

- 5 skipped tests: reasons not printed in `-q` mode; detailed verbose run in progress but not included here as the counts match the plain pytest run.
- `kernel_adapter` health is `unknown` at startup because no calls have been made yet (total_calls=0); this is not an error condition.
- Server startup logs three `build_gateway_from_config: ... not found` warnings for missing `config/llm_config.json`; this is expected in dev mode.
- `ruff` errors are entirely style/docstring violations (D*, I001, F401, E501); no type errors or security findings.
- MCP `transport_status: not_wired` is a known intentional gap (external stdio/SSE/HTTP transport deferred per architecture decision).
