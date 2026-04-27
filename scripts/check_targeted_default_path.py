#!/usr/bin/env python3
"""CI gate: run critical Wave-12 default-path integration tests.

Runs a targeted subset of integration tests that validate the core default
execution path. These tests are in the 'release' profile and must pass before
any release.

Exit 0: all tests pass.
Exit 1: one or more tests fail or do not exist.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Critical tests that MUST pass for the default path to be considered healthy.
TARGETED_TESTS = [
    "tests/integration/test_run_lease_heartbeat.py",
    "tests/integration/test_run_progress_events.py",
    "tests/integration/test_run_liveness_fields.py",
    "tests/integration/test_dlq_surface.py",
    "tests/integration/test_backpressure.py",
    "tests/integration/test_graceful_drain.py",
    "tests/unit/test_metrics_catalogue_complete.py",
]


def _test_exists(test_path: str) -> bool:
    return (ROOT / test_path).exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    missing = [t for t in TARGETED_TESTS if not _test_exists(t)]
    if missing:
        msg = f"missing test files: {missing}"
        if args.json_output:
            print(json.dumps({"check": "targeted_default_path", "status": "fail", "reason": msg}))
        else:
            print(f"FAIL targeted_default_path: {msg}")
        return 1

    if args.dry_run:
        msg = f"dry-run: would run {len(TARGETED_TESTS)} test files"
        if args.json_output:
            print(json.dumps({"check": "targeted_default_path", "status": "pass", "reason": msg}))
        else:
            print(f"OK targeted_default_path (dry-run): {msg}")
        return 0

    cmd = [
        sys.executable, "-m", "pytest",
        *TARGETED_TESTS,
        "-q", "--tb=short",
        "-m", "not external_llm and not network and not e2e",
    ]
    result = subprocess.run(cmd, cwd=str(ROOT))

    status = "pass" if result.returncode == 0 else "fail"
    if args.json_output:
        print(json.dumps({
            "check": "targeted_default_path",
            "status": status,
            "returncode": result.returncode,
            "test_files": TARGETED_TESTS,
        }))
    else:
        if result.returncode == 0:
            print("OK targeted_default_path: all critical tests pass")
        else:
            print(f"FAIL targeted_default_path: pytest exited {result.returncode}")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

