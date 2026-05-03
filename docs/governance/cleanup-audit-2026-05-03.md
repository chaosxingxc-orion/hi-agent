# Cleanup Audit — 2026-05-03 (Wave 32 Track E)

**Auditor:** Wave 32 Track E
**Repo HEAD at audit:** `d29b53c8`
**Scope:** Untracked files at repo root, untracked verification artifact, dependency-stale code, workspace-level files outside repo.

---

## E.1 — Untracked dirs at repo root

Verified each untracked directory against `.gitignore`:

| Directory | Pre-audit `.gitignore` status | Action |
|---|---|---|
| `.checkpoint/` | Ignored (line 17) | None |
| `.episodes/` | Ignored (line 27) | None |
| `.hi_agent/` | Ignored (line 14) | None |
| `.hi_agent_soak_w31_l1/` | Ignored (line 15, glob `.hi_agent_soak_*/`) | None |
| `.tmp_soak_scratch/` | **NOT ignored** | **Added to `.gitignore`** |
| `.pytest_cache/` | Ignored (line 31) | None |
| `.ruff_cache/` | Ignored (line 30) | None |
| `.venv/` | Ignored (line 11) | None |

**Verification command:** `git check-ignore -v <dir>` — all eight now produce hits after the `.gitignore` update.

**Defect found and fixed:** `.tmp_soak_scratch/` was an operational scratch directory created during W31 soak shape runs but never added to `.gitignore`. Inserted between `.checkpoint/` (line 17) and `.claude/` (line 18).

**No directories deleted** — all are correctly classified operational state, ignored is the right disposition.

---

## E.2 — Untracked verification artifact: `docs/verification/5c115d82-soak-shape-241m.json`

**File metadata:**
- Size: ~358 KB, 13,063 lines
- `release_head: 5c115d82` (NOT current HEAD `d29b53c8`)
- `provenance: shape_1h` (real data label, not zero/dummy)
- `requested_duration_label: 4h`, observed `duration_seconds: 14496.772`
- **Outcome: FAILED soak shape** — `runs_submitted: 568`, `runs_completed: 0`, `runs_failed: 568`, `llm_fallback_count: 101`

**Cross-reference checks:**
- Not referenced by any committed release manifest under `docs/releases/` (current = `2026-05-03-953d36cb` for W31).
- Not referenced by any closure notice or signoff JSON.
- Only mention in repo: the Wave 32 plan document `docs/superpowers/plans/2026-05-03-wave-32-real-kernel-binding-and-cleanup.md` (which delegated this very decision).
- Per-tenant data structurally legitimate: 3 tenants × 2 projects each, real run counts, real sigterm/respawn event with `downtime_seconds: 2.72`.

**Decision: COMMIT (git-add only — no commit performed per instructions).**

**Rationale:** The file is real W31-L1 soak shape evidence. It is NOT zero/dummy and NOT stale (timestamps `2026-05-02T20:00:54Z` → `2026-05-03T00:02:31Z`). The soak shape failed (0/568 runs reached terminal), which is exactly the W31-L1 in-flight blocker noted in the project memory entry: `"13 of 14 IDs PASS, W31-L1 in-flight"`. Deleting this evidence would erase the failure record that justifies the current `verified_readiness=55.0` cap (`soak_evidence_not_real`). Keeping it as committed evidence supports the open-blocker audit trail.

**Action taken:**
```
git add docs/verification/5c115d82-soak-shape-241m.json
```
(Staged only; centralized commit deferred to caller per task constraints.)

---

## E.3 — Dependency-stale code audit

**Tool:** `vulture 2.16` (installed during this audit) at `--min-confidence 100` against `hi_agent/` and `agent_server/`.

**Findings (6 total, all 100% confidence):**

| # | Path | Symbol | Verdict |
|---|---|---|---|
| 1 | `hi_agent/context/manager.py:893` | `actual_input_tokens` | **KEEP — false positive** (public method kwarg) |
| 2 | `hi_agent/runner.py:2370` | `grant` | **KEEP — false positive** (gate-protocol handler signature) |
| 3 | `hi_agent/server/app.py:1518` | `signum` | **KEEP — false positive** (`signal.signal` callback contract) |
| 4 | `hi_agent/server/app.py:1518` | `frame` | **KEEP — false positive** (`signal.signal` callback contract) |
| 5 | `hi_agent/skill_runtime/contracts.py:65` | `skill_kind` | **KEEP — false positive** (Protocol method kwarg) |
| 6 | `hi_agent/task_mgmt/restart_policy.py:89` | `failed_run_id` | **KEEP — false positive** (public coroutine kwarg) |

**Per-finding rationale:**

1. **`actual_input_tokens`** (`record_response`): Method body discards the parameter currently, but the kwarg name is part of the public `ContextManager.record_response()` API; renaming or dropping it would break callers. Conservative: keep.
2. **`grant`** (`async def handler(action, grant)`): The `gate_protocol` registers handlers with a fixed `(action, grant)` signature. Removing the parameter would break the handler factory contract.
3. & 4. **`signum`, `frame`** (`_sigterm_handler`): Required by the standard library's `signal.signal()` callback ABI. Removing them is invalid.
5. **`skill_kind`** (`async def list_by_kind`): Protocol method declaration on `SkillRegistryProtocol`; the body is `...` because it's a Protocol stub. Removing the kwarg name removes it from the public contract.
6. **`failed_run_id`** (`handle_failure`): Public method; callers pass it positionally and by name, even though the body's current branch doesn't reference it (early policy-missing exit doesn't need it).

**`--min-confidence 90` produced identical results — no additional candidates surfaced.**

**`git log -1 --format=%ar` for all six files: "6 hours ago"** — all fail the "≥1 week last-modified" conservative threshold; even if findings were real, they would not qualify for deletion under this audit's safety policy.

**Conservative deletion list: EMPTY.** No code modules or symbols deleted.

---

## E.4 — Workspace-level cleanup (`D:\chao_workspace\`)

**Files inspected at workspace root (outside `hi-agent/`):**
- `ruff_output.txt`
- `ruff_src_output.txt`
- `check_docs.py`
- `fix_all_docs.py`

**Cross-reference inside `hi-agent/`:** Grep for symbol or filename references — **zero matches**. None of these workspace-level files are imported or referenced by any committed hi-agent script.

**Decision: INVESTIGATED BUT NOT IN SCOPE per repo boundary.** Per task instructions: "The workspace-level files are not our concern unless they impact our repo." They do not impact the repo and are outside `D:\chao_workspace\hi-agent\`. **No action taken.**

---

## E.5 — Summary of actions

### Files added to staging (no commit performed)
- `docs/verification/5c115d82-soak-shape-241m.json` — W31-L1 soak shape evidence (failed, real data)

### Files modified
- `.gitignore` — added `.tmp_soak_scratch/` between `.checkpoint/` and `.claude/`

### Files deleted
- **None.**

### Files left alone (with reason)
- `.checkpoint/`, `.episodes/`, `.hi_agent/`, `.hi_agent_soak_w31_l1/`, `.pytest_cache/`, `.ruff_cache/`, `.venv/` — already gitignored, are correctly classified operational state.
- All six vulture findings — false positives in public method/handler/Protocol signatures.
- Workspace-level files (`ruff_output.txt`, `ruff_src_output.txt`, `check_docs.py`, `fix_all_docs.py` at `D:\chao_workspace\`) — outside the repo boundary; per task constraints.

### Surprises
- Only one `.gitignore` defect (`.tmp_soak_scratch/`) — the rest were already correctly ignored, indicating W31's gitignore audit was thorough.
- All six `vulture --min-confidence 100` findings are false positives at the same root cause (public-method kwargs that the body doesn't dereference but consumers do). This suggests vulture's per-symbol heuristic does not distinguish "unused in body" from "unused in API"; future runs should treat these as known-clean unless code structure changes.
- The W31-L1 soak shape failure is more visible than the Wave 31 closure manifests imply: 0/568 runs reached terminal — every single submitted run failed. This artifact materially supports the `soak_evidence_not_real` cap currently in force.

### Tests
- **Not re-run.** No code modules or symbols were deleted; no tests could be affected. Per task spec: "skip if you deleted only verification/log artifacts." Skipped.

---

## Appendix — Verification commands

```
# E.1 ignore status (post-audit)
git check-ignore -v .checkpoint/ .episodes/ .hi_agent/ .hi_agent_soak_w31_l1/ .tmp_soak_scratch/ .pytest_cache/ .ruff_cache/ .venv/

# E.2 staged file
git status --short  # should show "A  docs/verification/5c115d82-soak-shape-241m.json" + " M .gitignore"

# E.3 dependency audit
python -m vulture hi_agent/ agent_server/ --min-confidence 100
python -m vulture hi_agent/ agent_server/ --min-confidence 90

# E.4 cross-reference (zero matches confirmed)
# (Grep tool used; no shell command stored.)
```
