#!/usr/bin/env python3
"""Runtime-coupled chaos matrix driver.

Starts a live hi_agent server for each scenario, injects the specified
failure, and records whether the platform recovers with zero lost runs
and operator-visible signal.

Exit 0: all scenarios pass (or skip)
Exit 1: any scenario fails
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request as _urllib_request

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"
SCENARIOS_DIR = ROOT / "tests" / "chaos" / "scenarios"

sys.path.insert(0, str(SCENARIOS_DIR))

# Bypass system proxy for localhost server connections.
_OPENER = _urllib_request.build_opener(_urllib_request.ProxyHandler({}))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _git_short() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _wait_healthy(base_url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with _OPENER.open(f"{base_url}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


_ENV_DEFAULTS: dict[str, str] = {
    "HI_AGENT_HEARTBEAT_STALL_S": "5",
    "HI_AGENT_HEARTBEAT_INTERVAL_MS": "200",
    # Legacy fault-injection env vars (kept for backward compatibility).
    "HI_AGENT_LLM_MOCK_DELAY_MS": "10000",
    "HI_AGENT_TOOL_FAULT": "crash",
    "HI_AGENT_ARTIFACT_FAULT": "oserror",
    "HI_AGENT_CLOCK_OFFSET_S": "3600",
    # AX-A A5: FaultInjector env vars (wired into runtime seams via fault_injection.py).
    "HI_AGENT_FAULT_LLM_TIMEOUT": "1",
    "HI_AGENT_FAULT_TOOL_CRASH": "*",
    "HI_AGENT_FAULT_DISK_FULL": "1",
    "HI_AGENT_FAULT_HEARTBEAT_STALL": "1",
    "HI_AGENT_FAULT_CLOCK_SKEW_SECONDS": "3600",
    "HI_AGENT_FAULT_DLQ_POISON": "1",
}


def _run_with_server(scenario_mod) -> dict:  # type: ignore[type-arg]  expiry_wave: Wave 26
    """Start server, run scenario, stop server."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Inject env vars declared by the scenario before starting the server subprocess.
    import os as _os
    env = _os.environ.copy()
    for var in getattr(scenario_mod, "REQUIRED_ENV", []):
        if var not in env and var in _ENV_DEFAULTS:
            env[var] = _ENV_DEFAULTS[var]

    proc = subprocess.Popen(
        [sys.executable, "-m", "hi_agent", "serve", "--port", str(port)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        if not _wait_healthy(base_url, timeout=30):
            return {
                "name": scenario_mod.SCENARIO_NAME,
                "runtime_coupled": True,
                "synthetic": False,
                "provenance": "degraded",
                "passed": False,
                "assertions": {
                    "accepted_runs_lost": -1,
                    "duplicate_terminal_executions": -1,
                    "duplicate_terminal_events": -1,
                    "progress_offset_regressions": -1,
                    "unclassified_failures": 1,
                    "operator_visible_signal": False,
                },
                "notes": "server did not become healthy within 30s",
                "duration_s": 0.0,
                "skipped": False,
                "skip_reason": "",
            }
        t0 = time.monotonic()
        result = scenario_mod.run_scenario(base_url, timeout=60.0)
        result["duration_s"] = round(time.monotonic() - t0, 2)
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chaos matrix.")
    parser.add_argument("--output", help="Output path for evidence JSON")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    # Discover scenarios
    scenario_files = sorted(SCENARIOS_DIR.glob("[0-9][0-9]_*.py"))
    if not scenario_files:
        print("FAIL: no scenario files found in tests/chaos/scenarios/", file=sys.stderr)
        return 1

    sha = _git_short()
    start_ts = datetime.datetime.now(datetime.UTC).isoformat()
    results = []

    for sf in scenario_files:
        spec = importlib.util.spec_from_file_location(sf.stem, sf)
        if spec is None or spec.loader is None:
            print(f"WARN: could not load {sf}", file=sys.stderr)
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]  expiry_wave: Wave 26
        print(f"Running scenario: {mod.SCENARIO_NAME} ...", file=sys.stderr)
        result = _run_with_server(mod)
        results.append(result)
        status = "SKIP" if result.get("skipped") else ("PASS" if result.get("passed") else "FAIL")
        print(f"  {status}: {result.get('notes', '')}", file=sys.stderr)

    passed = sum(1 for r in results if r.get("passed") and not r.get("skipped"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = len(results) - passed - skipped

    finish_ts = datetime.datetime.now(datetime.UTC).isoformat()
    overall_status = "pass" if failed == 0 else "fail"

    # Derive aggregate provenance and runtime_coupled from actual per-scenario results.
    # observation: aggregate_provenance derived from per-scenario provenance fields
    any_degraded = any(
        r.get("provenance") == "degraded" or r.get("skipped")
        for r in results
    )
    all_runtime_coupled = all(
        r.get("runtime_coupled", False)
        for r in results
        if not r.get("skipped")
    )
    aggregate_provenance = "degraded" if any_degraded else "real"
    aggregate_runtime_coupled = all_runtime_coupled and not any_degraded

    evidence = {
        "schema_version": "1",
        "check": "chaos_runtime_coupling",
        "provenance": aggregate_provenance,
        "runtime_coupled": aggregate_runtime_coupled,
        "head": sha,
        "scenarios_total": len(results),
        "scenarios_passed": passed,
        "scenarios_skipped": skipped,
        "scenarios_failed": failed,
        "status": overall_status,
        "scenarios": results,
        "command": "python scripts/run_chaos_matrix.py",
        "generated_at": finish_ts,
        "start_ts": start_ts,
        "finish_ts": finish_ts,
    }

    out_path = pathlib.Path(args.output) if args.output else VERIF_DIR / f"{sha}-runtime-chaos.json"
    VERIF_DIR.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "scripts"))
    from _governance.evidence_writer import write_artifact
    _chaos_provenance = evidence.get("provenance", "structural")
    write_artifact(
        path=out_path,
        body=evidence,
        provenance=_chaos_provenance if _chaos_provenance == "real" else "structural",
        generator_script=__file__,
        degraded=(_chaos_provenance != "real"),
    )

    if args.json:
        print(json.dumps(evidence, indent=2))
    else:
        print(
            f"{'PASS' if overall_status == 'pass' else 'FAIL'}: "
            f"{passed} passed, {skipped} skipped, {failed} failed"
        )

    return 0 if overall_status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
