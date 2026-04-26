#!/usr/bin/env python3
"""Clean-environment verification wrapper for Wave 10.3+.

Reproduced the downstream reviewer's Windows PermissionError in cleanup_dead_symlinks.
Root cause: pytest 8.x tries to clean dangling symlinks in basetemp on session teardown;
on Windows with restricted ACLs, the cleanup itself fails with PermissionError.

Fix: set PYTEST_DEBUG_TEMPROOT to an absolute path we control; wipe .pytest_cache
before running so pytest doesn't walk stale entries.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".pytest_tmp"
CACHE = ROOT / ".pytest_cache"

# Wave 10.3 targeted test bundle — extend as new integration tests land
WAVE_TEST_BUNDLE = [
    "tests/integration/test_gate_store_spine.py",
    "tests/integration/test_team_run_registry_spine.py",
    "tests/integration/test_feedback_store_spine_via_http.py",
    "tests/integration/test_run_queue_spine_via_http.py",
    "tests/integration/test_cross_tenant_object_level.py",
    "tests/unit/test_check_select_completeness.py",
    "tests/unit/test_run_execution_context.py",
    # Wave 10.3 additions — added as W3-A/B/C/D tests land:
    "tests/unit/test_posture_guards.py",
    "tests/integration/test_human_gate_spine_strict.py",
    "tests/integration/test_op_handle_strict.py",
    "tests/integration/test_gate_store_unscoped_strict.py",
    "tests/unit/test_runner_finalize_fallback_alarm.py",
    "tests/unit/test_runner_get_fallback_events_alarm.py",
    "tests/integration/test_http_gateway_failover_alarm.py",
    "tests/unit/test_run_execution_context_pilot.py",
    "tests/integration/test_intake_to_finalizer_spine_consistency.py",
]


def main() -> int:
    print("=== hi-agent clean-env verification ===")
    print(f"ROOT: {ROOT}")

    # 1. Wipe stale cache to avoid cleanup_dead_symlinks PermissionError
    if CACHE.exists():
        try:
            shutil.rmtree(CACHE)
            print(f"Cleared {CACHE}")
        except PermissionError as e:
            print(f"WARNING: could not clear {CACHE}: {e} (continuing)")

    # 2. Ensure tmp dir exists and is writable
    TMP.mkdir(parents=True, exist_ok=True)

    # 3. Set env vars so pytest uses our controlled paths
    env = os.environ.copy()
    env["PYTEST_DEBUG_TEMPROOT"] = str(TMP.absolute())

    # 4. Filter bundle to only existing paths (W3-A/B/C/D tests added incrementally)
    bundle = [p for p in WAVE_TEST_BUNDLE if (ROOT / p).exists()]
    missing = [p for p in WAVE_TEST_BUNDLE if not (ROOT / p).exists()]
    if missing:
        print(f"NOTE: {len(missing)} test paths not yet created (will land in W3-A/B/D):")
        for m in missing:
            print(f"  {m}")

    if not bundle:
        print("ERROR: no test paths found in bundle")
        return 1

    # 5. Run pytest
    cmd = [
        sys.executable, "-m", "pytest",
        f"--basetemp={TMP}",
        "--timeout=60",
        "-v",
        *bundle,
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, cwd=ROOT)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
