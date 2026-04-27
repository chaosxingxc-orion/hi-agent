# Closure-Claim Taxonomy

Reference: CLAUDE.md Rule 15

---

## Five Closure Levels

Levels are ordered; each level strictly includes all lower-level requirements.

| Level | Name | What it means |
|---|---|---|
| `component_exists` | Code written | Implementation committed; not wired into default path; no tests cover it. |
| `wired_into_default_path` | Wired | Code is on the default server/runtime call path; unit tests exist. |
| `covered_by_default_path_e2e` | E2E covered | An E2E or integration test drives the default path and asserts the behavior end-to-end. |
| `verified_at_release_head` | Release-verified | All above + confirmed at the current release HEAD; manifest evidence (SHA + test run) recorded in `docs/delivery/`. |
| `operationally_observable` | Observable | All above + metric, alert, or runbook surfaces the behavior to operators in production. |

---

## Evidence Examples

### `component_exists`
- Evidence: "Committed in abc1234, class `FooStore` in `hi_agent/server/foo_store.py`."
- NOT sufficient for CLOSED. Report as `IN PROGRESS (level: component_exists)`.

### `wired_into_default_path`
- Evidence: "Wired via `app.py` dependency injection; unit tests in `tests/unit/test_foo_store.py`."
- NOT sufficient for CLOSED. Report as `IN PROGRESS (level: wired_into_default_path)`.

### `covered_by_default_path_e2e`
- Evidence: "`tests/integration/test_foo_e2e.py::test_foo_round_trip` exercises the default path and asserts `state=done`."
- NOT sufficient for CLOSED unless at release HEAD with manifest.

### `verified_at_release_head`
- Evidence: "Gate run recorded at `docs/delivery/2026-04-27-abc1234-rule8.md`; all 6 Rule 8 checks passed; manifest ID `W12-001`."
- **Minimum level for a `CLOSED` claim.**

### `operationally_observable`
- Evidence: "Prometheus counter `hi_agent_foo_total` appears in `/metrics`; alert rule in `runbook/foo-alert.yml`."

---

## Anti-Examples (what does NOT count)

- "Tests pass in CI" -- passes do not prove wiring or E2E coverage.
- "I reviewed the code and it looks correct" -- not evidence.
- "Covered by `test_foo.py`" with no assertion listed -- not evidence; name the assertion.
- "SHA abc1234 merged" -- a merge does not prove the component is on the default path.
- "Closed in a previous wave" -- re-verified at current HEAD required; level resets on hot-path changes.

---

## Three-Part Defect Closure

Every defect marked `CLOSED` requires all three parts. Missing any one part keeps the defect `OPEN`.

| Part | Required content |
|---|---|
| **Code fix** | Commit SHA or PR URL pointing to the change. |
| **Regression test or hard gate** | Test file + test function name, OR CI gate script + the assertion it makes. |
| **Delivery-process change** | What prevents re-entry: CLAUDE.md rule added/updated, CI gate added, scorecard row added, etc. |

### Example three-part closure block

```
Defect: DF-55 -- run_id not set before LLM call

Code fix: commit e7f3a12, hi_agent/runner.py line 88
Gate: tests/integration/test_runner_run_id.py::test_run_id_set_before_llm_call
Process: Rule 12 pre-commit check + check_rules.py enforces run_id spine; added DF-55 to CLAUDE.md incident log.
Level: verified_at_release_head
```

---

## Delivery Notice Sub-Table Format

Each defect-closure row in a delivery notice must carry a 3-row sub-table:

```markdown
| Part | Evidence |
|---|---|
| Code fix | commit <sha>, <file>:<line> |
| Gate | <test_file>::<test_name> asserts <what> |
| Process | <rule or CI gate change> |
| Level | verified_at_release_head |
```
