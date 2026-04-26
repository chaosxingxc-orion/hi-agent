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
