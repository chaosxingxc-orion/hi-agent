# Clean-Environment Verification

`scripts/verify_clean_env.py` runs the full Wave test bundle in a portable clean environment.

## Usage

```bash
# Default: uses system tempdir (works on any machine)
python scripts/verify_clean_env.py

# Custom paths (for CI or restricted environments)
python scripts/verify_clean_env.py \
  --basetemp /tmp/hi_agent_pytest \
  --cache-dir /tmp/hi_agent_cache \
  --json-report docs/delivery/<sha>-clean-env.json
```

## Evidence JSON

The `--json-report` output is machine-readable evidence for delivery notices.
Required fields: schema_version, head, python, pytest, basetemp, cache_dir,
command, started_at, finished_at, duration_seconds, collected, passed, failed,
errors, skipped, missing_paths.

## Pre-flight Check

By default, the script checks that basetemp and cache-dir are readable/writable
before running pytest. If the check fails, it exits 2 with a single line:
`ENV-CHECK-FAIL: <path> <stage> <error>`

To skip: `--no-fail-fast-env-check`

## Profile Reference

| Profile | Scope | Target runtime | Use case |
|---|---|---|---|
| `default-offline` | tests/unit, tests/contract, tests/security, tests/agent_kernel | <= 10 min | Developer health check; must pass before push |
| `release` | Full WAVE_TEST_BUNDLE (all unit + integration + contract + security + agent_kernel + runtime_adapter + server) | <= 30 min | Pre-release regression; CI release-gate |
| `nightly` | release + tests/e2e + tests/perf + tests/characterization + tests/golden | Unlimited | Full coverage; scheduled nightly |
| `smoke-w5` | Small W5 subset (10 files) | < 2 min | Fast pre-flight import/smoke check |

### Why `default-offline` excludes `tests/integration`

`tests/integration/` contains 419 files.  Without `@pytest.mark.integration`
on most of them, the marker exclusion `-m "not live_api and not external_llm
and not network and not requires_secret"` does not filter them out.  The result
is collection of 12,373+ items and a 600s timeout.

The fix is two-part:

1. `tests/integration/conftest.py` auto-applies `@pytest.mark.integration` via
   `pytest_collection_modifyitems` — no per-file edits required.
2. `default-offline` uses `_DEFAULT_OFFLINE_PATHS` (unit/contract/security/
   agent_kernel) instead of the full `WAVE_TEST_BUNDLE`.  Integration tests are
   only collected under `release` and `nightly`.

### Timeout triage

When pytest is killed due to the 600s timeout, the evidence JSON includes a
`timeout_triage` object:

```json
{
  "timeout_triage": {
    "tail": "<last 200 lines of output>",
    "currently_running_nodeid": "<last RUNNING/PASSED/FAILED line>",
    "total_output_lines": 1234
  }
}
```

`currently_running_nodeid` points to the test that was running at kill time,
which is the primary triage signal for timeout investigations.
