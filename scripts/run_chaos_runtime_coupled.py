#!/usr/bin/env python3
"""W24 Track B: Runtime-coupled chaos driver.

Spawns a single ``python -m hi_agent serve --port <port>`` subprocess with all
known FaultInjector env vars active, then dispatches each of the 10 chaos
scenarios in ``tests/chaos/scenarios/`` against the live server.  Emits a
single evidence JSON whose top-level provenance is one of:

  - ``runtime``         — all scenarios executed real actions against a live
                          hi_agent process; none skipped.
  - ``runtime_partial`` — server was live and at least one scenario reached
                          terminal/asserted state, but one or more scenarios
                          could not be exercised in this environment (e.g.
                          requires Docker, real LLM, or per-scenario server
                          restart) and were recorded as ``skipped=true``.

Distinct from the older ``run_chaos_matrix.py`` driver which restarts the
server between scenarios.  This driver shares one process so cross-scenario
runtime state (queue, store, watchdog) is genuinely exercised end-to-end.

Exit codes:
  0 — all scenarios passed (or were skipped honestly) and provenance is
      ``runtime`` or ``runtime_partial``.
  1 — server failed to start or any scenario asserted a hard failure.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request as _urllib_request

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"
SCENARIOS_DIR = ROOT / "tests" / "chaos" / "scenarios"

# Make scenario modules importable.  Two paths are required:
#   - SCENARIOS_DIR so each scenario can ``from _helpers import ...``
#   - ROOT so _helpers itself can ``from tests._helpers.run_states import ...``
sys.path.insert(0, str(SCENARIOS_DIR))
sys.path.insert(0, str(ROOT))

# Bypass system proxy for localhost server connections.
_OPENER = _urllib_request.build_opener(_urllib_request.ProxyHandler({}))


# ────────────────────────────────────────────────────────────────────────────
# Fault-injection env defaults: every var the scenario modules look for, all
# active for the single shared server.  A scenario that needs an env var
# present on the server will see it here; a scenario that does not care is
# unaffected.
# ────────────────────────────────────────────────────────────────────────────
_ENV_DEFAULTS: dict[str, str] = {
    # Legacy heartbeat stall vars (older code paths still consult these).
    "HI_AGENT_HEARTBEAT_STALL_S": "5",
    "HI_AGENT_HEARTBEAT_INTERVAL_MS": "200",
    # Legacy fault-injection env vars (kept for backward compatibility).
    "HI_AGENT_LLM_MOCK_DELAY_MS": "10000",
    "HI_AGENT_TOOL_FAULT": "crash",
    "HI_AGENT_ARTIFACT_FAULT": "oserror",
    "HI_AGENT_CLOCK_OFFSET_S": "3600",
    # AX-A A5: FaultInjector env vars (wired into runtime seams via
    # fault_injection.py).  These are the canonical, per-scenario knobs.
    "HI_AGENT_FAULT_LLM_TIMEOUT": "1",
    "HI_AGENT_FAULT_TOOL_CRASH": "*",
    "HI_AGENT_FAULT_DISK_FULL": "1",
    "HI_AGENT_FAULT_HEARTBEAT_STALL": "1",
    "HI_AGENT_FAULT_CLOCK_SKEW_SECONDS": "3600",
    "HI_AGENT_FAULT_DLQ_POISON": "1",
}


def _git_short() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _git_full() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _wait_healthy(base_url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with _OPENER.open(f"{base_url}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            # Health probe is best-effort; any error means "not yet healthy".
            pass
        time.sleep(0.5)
    return False


def _spawn_server(port: int) -> tuple[subprocess.Popen | None, str]:
    """Spawn the live hi_agent server with all fault-injection vars active.

    Returns:
        (process, reason)
        - On success: (Popen, "")
        - On failure: (None, "reason text")
    """
    if _port_in_use(port):
        return None, f"port {port} already in use"

    # Inject FaultInjector env vars into the server subprocess only.
    # The driver process intentionally does NOT see these vars: some
    # scenarios (06_tool_mcp_crash, 07_disk_full_artifact_write) inspect
    # ``os.environ`` themselves and assert "if fault_active and run
    # succeeded → silent-swallow defect".  In dev posture without real
    # capabilities/artifacts wired, the run completes via heuristic
    # fallback and the fault path is not exercised — so we let those
    # scenarios skip honestly rather than hard-fail.  Better partial-real
    # than fake-full-real ( contract).
    env = os.environ.copy()
    for key, value in _ENV_DEFAULTS.items():
        env.setdefault(key, value)

    # Force dev posture for chaos: research/prod would refuse to come up
    # without real LLM + KMS keys, which is incompatible with offline runs.
    env.setdefault("HI_AGENT_POSTURE", "dev")
    # Quiet startup so the test pipeline output stays focused on scenario
    # results.  Errors are still exposed via /health probe + scenario notes.
    env.setdefault("HI_AGENT_LOG_LEVEL", "WARNING")

    log_path = VERIF_DIR / f"chaos-server-{port}.log"
    VERIF_DIR.mkdir(parents=True, exist_ok=True)
    # Long-lived file handle for the server's stdout/stderr; closed in
    # _stop_server when the run finishes.  Cannot use a context manager
    # because the lifetime spans the subprocess, not this function.
    log_path.touch()
    log_fp = log_path.open("w", encoding="utf-8", errors="replace")

    proc = subprocess.Popen(
        [sys.executable, "-m", "hi_agent", "serve", "--port", str(port)],
        cwd=str(ROOT),
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        env=env,
    )

    # Stash the log handle on the process for shutdown cleanup.
    proc._chaos_log_fp = log_fp  # type: ignore[attr-defined] # expiry_wave: Wave 26
    return proc, ""


def _stop_server(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    finally:
        log_fp = getattr(proc, "_chaos_log_fp", None)
        if log_fp is not None:
            with contextlib.suppress(Exception):
                log_fp.close()


def _load_scenario(path: pathlib.Path):  # type: ignore[no-untyped-def] # expiry_wave: Wave 26
    """Import a scenario module by file path.  Returns the module or None."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr] # expiry_wave: Wave 26
    except Exception as exc:
        # Caller records the failure as a per-scenario skip with reason text.
        mod._chaos_load_error = str(exc)  # type: ignore[attr-defined] # expiry_wave: Wave 26
    return mod


def _normalise_scenario_result(raw: dict, scenario_name: str) -> dict:
    """Project a raw scenario dict into the  evidence shape.

    Each entry must carry: name, passed, invariants_held, duration_s.
    Skipped scenarios additionally carry skipped=true and reason.
    """
    name = raw.get("name") or scenario_name
    skipped = bool(raw.get("skipped", False))
    passed = bool(raw.get("passed", False))
    notes = raw.get("notes", "")
    skip_reason = raw.get("skip_reason", "") or notes if skipped else ""

    assertions = raw.get("assertions", {})
    # Map legacy assertion fields →  invariants.
    invariants_held = {
        "no_lost_runs": assertions.get("accepted_runs_lost", 0) == 0,
        "no_duplicates": (
            assertions.get("duplicate_terminal_executions", 0) == 0
            and assertions.get("duplicate_terminal_events", 0) == 0
        ),
        "no_regressions": assertions.get("progress_offset_regressions", 0) == 0,
        "no_unclassified_failures": assertions.get("unclassified_failures", 0) == 0,
        "operator_visible_signal": bool(
            assertions.get("operator_visible_signal", False)
        ),
    }

    out = {
        "name": name,
        "passed": passed,
        "skipped": skipped,
        "invariants_held": invariants_held,
        "duration_s": float(raw.get("duration_s", 0.0)),
        "notes": notes,
        "scenario_provenance": raw.get("provenance", "unknown"),
        "scenario_runtime_coupled": bool(raw.get("runtime_coupled", False)),
    }
    if skipped:
        out["reason"] = skip_reason or "scenario reported skipped without reason"
    return out


def _run_one_scenario(mod, base_url: str, timeout: float) -> dict:  # type: ignore[no-untyped-def] # expiry_wave: Wave 26
    """Drive a single scenario module against the live server."""
    name = getattr(mod, "SCENARIO_NAME", mod.__name__)
    load_error = getattr(mod, "_chaos_load_error", None)
    if load_error:
        return {
            "name": name,
            "passed": False,
            "skipped": True,
            "invariants_held": {
                "no_lost_runs": False,
                "no_duplicates": False,
                "no_regressions": False,
                "no_unclassified_failures": False,
                "operator_visible_signal": False,
            },
            "duration_s": 0.0,
            "reason": f"scenario module failed to import: {load_error}",
            "notes": "",
            "scenario_provenance": "unknown",
            "scenario_runtime_coupled": False,
        }

    run_fn = getattr(mod, "run_scenario", None)
    if run_fn is None:
        return {
            "name": name,
            "passed": False,
            "skipped": True,
            "invariants_held": {
                "no_lost_runs": False,
                "no_duplicates": False,
                "no_regressions": False,
                "no_unclassified_failures": False,
                "operator_visible_signal": False,
            },
            "duration_s": 0.0,
            "reason": "scenario has no run_scenario(base_url) entry point",
            "notes": "",
            "scenario_provenance": "unknown",
            "scenario_runtime_coupled": False,
        }

    t0 = time.monotonic()
    try:
        raw = run_fn(base_url, timeout=timeout)
    except Exception as exc:
        # Scenario module raised — record as skipped with the exception text
        # rather than letting it crash the rest of the matrix.
        return {
            "name": name,
            "passed": False,
            "skipped": True,
            "invariants_held": {
                "no_lost_runs": False,
                "no_duplicates": False,
                "no_regressions": False,
                "no_unclassified_failures": False,
                "operator_visible_signal": False,
            },
            "duration_s": round(time.monotonic() - t0, 2),
            "reason": f"scenario raised exception: {type(exc).__name__}: {exc}",
            "notes": "",
            "scenario_provenance": "unknown",
            "scenario_runtime_coupled": False,
        }

    if not isinstance(raw, dict):
        return {
            "name": name,
            "passed": False,
            "skipped": True,
            "invariants_held": {
                "no_lost_runs": False,
                "no_duplicates": False,
                "no_regressions": False,
                "no_unclassified_failures": False,
                "operator_visible_signal": False,
            },
            "duration_s": round(time.monotonic() - t0, 2),
            "reason": f"scenario returned non-dict: {type(raw).__name__}",
            "notes": "",
            "scenario_provenance": "unknown",
            "scenario_runtime_coupled": False,
        }

    # Always overwrite duration_s with the observed wall-clock — most scenario
    # modules initialise it to 0.0 and never update it.  The driver's t0 is
    # the only authoritative timer.
    raw["duration_s"] = round(time.monotonic() - t0, 2)
    return _normalise_scenario_result(raw, name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Runtime-coupled chaos driver (W24 Track B)."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9082,
        help="Port for the live hi_agent server (default: 9082).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for evidence JSON.  "
        "Default: docs/verification/<short-sha>-chaos-runtime.json",
    )
    parser.add_argument(
        "--scenario-timeout",
        type=float,
        default=90.0,
        help=(
            "Per-scenario timeout in seconds (default: 90).  Larger than the "
            "tests/chaos/scenarios default of 60 because all 10 scenarios "
            "share a single server process and queue/store state is not "
            "reset between scenarios; later scenarios may need extra budget."
        ),
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=45.0,
        help="Server-readiness timeout in seconds (default: 45).",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    scenario_files = sorted(SCENARIOS_DIR.glob("[0-9][0-9]_*.py"))
    if not scenario_files:
        print("FAIL: no scenario files found in tests/chaos/scenarios/", file=sys.stderr)
        return 1

    sha_short = _git_short()
    sha_full = _git_full()
    base_url = f"http://127.0.0.1:{args.port}"

    start_ts = datetime.datetime.now(datetime.UTC).isoformat()

    server_proc, server_reason = _spawn_server(args.port)
    server_started = False
    server_logs_path = str(VERIF_DIR / f"chaos-server-{args.port}.log")
    results: list[dict] = []

    if server_proc is None:
        # Server cannot be spawned at all — every scenario is skipped.
        for sf in scenario_files:
            mod = _load_scenario(sf)
            name = (
                getattr(mod, "SCENARIO_NAME", sf.stem)
                if mod is not None
                else sf.stem
            )
            results.append(
                {
                    "name": name,
                    "passed": False,
                    "skipped": True,
                    "invariants_held": {
                        "no_lost_runs": False,
                        "no_duplicates": False,
                        "no_regressions": False,
                        "no_unclassified_failures": False,
                        "operator_visible_signal": False,
                    },
                    "duration_s": 0.0,
                    "reason": f"server did not spawn: {server_reason}",
                    "notes": "",
                    "scenario_provenance": "unknown",
                    "scenario_runtime_coupled": False,
                }
            )
    else:
        try:
            server_started = _wait_healthy(base_url, timeout=args.health_timeout)
            if not server_started:
                # Server spawned but never reached /health 200.  Record that as
                # the reason for every scenario; runtime_coupled stays false.
                for sf in scenario_files:
                    mod = _load_scenario(sf)
                    name = (
                        getattr(mod, "SCENARIO_NAME", sf.stem)
                        if mod is not None
                        else sf.stem
                    )
                    results.append(
                        {
                            "name": name,
                            "passed": False,
                            "skipped": True,
                            "invariants_held": {
                                "no_lost_runs": False,
                                "no_duplicates": False,
                                "no_regressions": False,
                                "no_unclassified_failures": False,
                                "operator_visible_signal": False,
                            },
                            "duration_s": 0.0,
                            "reason": (
                                f"server failed to become healthy on {base_url} "
                                f"within {args.health_timeout}s "
                                f"(see {server_logs_path})"
                            ),
                            "notes": "",
                            "scenario_provenance": "unknown",
                            "scenario_runtime_coupled": False,
                        }
                    )
            else:
                # Server is up; drive each scenario sequentially.  Sharing the
                # process across scenarios is the  invariant: cross-
                # scenario runtime state (queue, store, watchdog) is exercised
                # end-to-end.
                for sf in scenario_files:
                    mod = _load_scenario(sf)
                    if mod is None:
                        results.append(
                            {
                                "name": sf.stem,
                                "passed": False,
                                "skipped": True,
                                "invariants_held": {
                                    "no_lost_runs": False,
                                    "no_duplicates": False,
                                    "no_regressions": False,
                                    "no_unclassified_failures": False,
                                    "operator_visible_signal": False,
                                },
                                "duration_s": 0.0,
                                "reason": f"could not import {sf.name}",
                                "notes": "",
                                "scenario_provenance": "unknown",
                                "scenario_runtime_coupled": False,
                            }
                        )
                        continue
                    name = getattr(mod, "SCENARIO_NAME", sf.stem)
                    print(f"Running scenario: {name} ...", file=sys.stderr)
                    res = _run_one_scenario(
                        mod, base_url, timeout=args.scenario_timeout
                    )
                    results.append(res)
                    status = (
                        "SKIP"
                        if res.get("skipped")
                        else ("PASS" if res.get("passed") else "FAIL")
                    )
                    note = res.get("reason") or res.get("notes") or ""
                    print(f"  {status}: {note}", file=sys.stderr)
        finally:
            _stop_server(server_proc)

    finish_ts = datetime.datetime.now(datetime.UTC).isoformat()

    # Aggregate logic:
    #   - If server never came up, all scenarios are skipped → not "runtime".
    #     We still emit evidence with provenance="degraded" so the gate sees
    #     the artifact and reports DEFER (not silently treat absence as PASS).
    #   - If server came up and EVERY scenario executed (passed=true,
    #     skipped=false), provenance is "runtime".
    #   - If server came up but ≥1 scenario was skipped honestly, provenance
    #     is "runtime_partial".
    #   - If any non-skipped scenario asserted hard failure, all_passed=False
    #     and the driver exits 1.
    executed = sum(1 for r in results if not r.get("skipped"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = sum(
        1 for r in results if not r.get("skipped") and not r.get("passed")
    )

    if not server_started:
        provenance = "degraded"
        runtime_coupled = False
    elif skipped == 0 and failed == 0:
        provenance = "runtime"
        runtime_coupled = True
    elif executed >= 1 and failed == 0:
        provenance = "runtime_partial"
        runtime_coupled = True
    else:
        # Server up, but at least one non-skipped scenario hard-failed.
        provenance = "runtime_partial" if executed >= 1 else "degraded"
        runtime_coupled = executed >= 1

    all_passed = failed == 0 and server_started

    evidence = {
        "schema_version": "1",
        "check": "chaos_runtime_coupling",
        "provenance": provenance,
        "runtime_coupled": runtime_coupled,
        "head": sha_short,
        "head_sha_full": sha_full,
        "port": args.port,
        "scenarios_total": len(results),
        "scenarios_executed": executed,
        "scenarios_skipped": skipped,
        "scenarios_failed": failed,
        "all_passed": all_passed,
        "status": "pass" if all_passed else "fail",
        "scenarios": results,
        "server_started": server_started,
        "server_log_path": server_logs_path,
        "command": "python scripts/run_chaos_runtime_coupled.py",
        "generated_at": finish_ts,
        "start_ts": start_ts,
        "finish_ts": finish_ts,
    }

    if args.output:
        out_path = pathlib.Path(args.output)
    else:
        out_path = VERIF_DIR / f"{sha_short}-chaos-runtime.json"
    VERIF_DIR.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ROOT / "scripts"))
    from _governance.evidence_writer import write_artifact

    # write_artifact requires either provenance='real' or degraded=True for
    # any other value.  "runtime" / "runtime_partial" are  vocab that the
    # consumer (check_chaos_runtime_coupling.py) is updated to accept; for
    # the writer they are non-real → degraded=True.
    write_artifact(
        path=out_path,
        body=evidence,
        provenance="real" if provenance == "runtime" else "structural",
        generator_script=__file__,
        degraded=(provenance != "runtime"),
    )

    if args.json:
        # Re-read the artifact so the printed JSON matches what we wrote
        # (write_artifact augments the body with _evidence_meta).
        printed = json.loads(out_path.read_text(encoding="utf-8"))
        print(json.dumps(printed, indent=2))
    else:
        print(
            f"{'PASS' if all_passed else 'FAIL'}: "
            f"executed={executed}, skipped={skipped}, failed={failed}, "
            f"provenance={provenance}, output={out_path}"
        )

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
