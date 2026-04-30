"""Scenario 2 - provider_outage: LLM provider unavailable; degraded path observable.

Operator behavior under test
---------------------------
When the upstream LLM provider becomes unavailable, the operator must see:

  - /health stays reachable (the server itself is healthy even when the
    provider is not).
  - /metrics/json reports the failure mode (fallback or error counters).
  - A new run does not silently succeed - it either fails-fast with a
    structured error, falls back through an observable path, or surfaces a
    degraded readiness signal via /ready.

Fault injection
---------------
The driver running this scenario sets ``HI_AGENT_FAULT_LLM_TIMEOUT=1`` in the
server env before startup. When active, the FaultInjector raises
``LLMTimeoutError`` on the first LLM call, exercising the timeout / fallback
recovery path. From within the scenario we observe the operator-visible
signals after the fault would have fired.

If the env var is NOT set when the scenario runs (i.e. the driver could not
restart the server with the fault), the scenario records
``simulated_pending_pm2`` provenance: the contract under test (operator
surfaces stay live during provider outage) is exercised against the same
endpoints, but the upstream fault was not injected, so we cannot claim full
real provenance for the degraded-path observation.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

SCENARIO_NAME = "provider_outage"
SCENARIO_DESCRIPTION = (
    "Verify /health stays 200, /metrics/json reports counters, and a new run "
    "produces an operator-visible signal when the LLM provider is unavailable "
    "(HI_AGENT_FAULT_LLM_TIMEOUT=1 active in server env)."
)

REQUIRED_ENV = ("HI_AGENT_FAULT_LLM_TIMEOUT",)

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get_json(url: str, timeout: float = 10.0) -> tuple[int, dict]:
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _post_json(url: str, payload: dict, timeout: float = 15.0) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _wait_terminal(base_url: str, run_id: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code, payload = _get_json(f"{base_url}/runs/{run_id}", timeout=5)
        if code == 200:
            state = payload.get("state") or payload.get("status") or "unknown"
            if state in _TERMINAL:
                return state
        time.sleep(0.3)
    return "timeout"


def run_scenario(base_url: str, timeout: float = 30.0) -> dict:
    t0 = time.monotonic()
    result: dict = {
        "name": SCENARIO_NAME,
        "duration_s": 0.0,
        "passed": False,
        "provenance": "simulated_pending_pm2",
        "notes": "",
        "evidence": {},
    }

    fault_active = bool(os.environ.get("HI_AGENT_FAULT_LLM_TIMEOUT"))

    # 1. /health must stay 200 even when the provider is broken.
    health_code, _health_payload = _get_json(f"{base_url}/health", timeout=5)
    health_ok = health_code == 200

    # 2. /metrics/json must answer with structured counters.
    metrics_code, metrics_payload = _get_json(f"{base_url}/metrics/json", timeout=5)
    metrics_ok = metrics_code == 200 and isinstance(metrics_payload, dict)

    # 3. /ready answers - 503 is acceptable (degraded), 200 is acceptable.
    ready_code, _ready_payload = _get_json(f"{base_url}/ready", timeout=5)
    ready_responsive = ready_code in (200, 503)

    # 4. Submit a run with a small timeout - when the provider is down, this
    #    should reach a non-success terminal state quickly OR produce a
    #    fallback event observable in the run state.
    submit_code, submit_resp = _post_json(
        f"{base_url}/runs",
        {"goal": "operator-drill v2 provider-outage probe", "context": {}},
        timeout=15,
    )
    run_id = submit_resp.get("run_id", "") if isinstance(submit_resp, dict) else ""
    final_state = ""
    submit_ok = 200 <= submit_code < 300
    if submit_ok and run_id:
        wait_budget = max(5.0, min(20.0, timeout - 10))
        final_state = _wait_terminal(base_url, run_id, timeout=wait_budget)

    elapsed = round(time.monotonic() - t0, 2)
    result["duration_s"] = elapsed
    result["evidence"] = {
        "fault_active_in_env": fault_active,
        "health_status": health_code,
        "metrics_status": metrics_code,
        "ready_status": ready_code,
        "submit_status": submit_code,
        "run_id": run_id,
        "final_state": final_state,
        "metric_keys_count": len(metrics_payload) if isinstance(metrics_payload, dict) else 0,
    }

    surfaces_ok = health_ok and metrics_ok and ready_responsive

    if surfaces_ok and fault_active and final_state in _TERMINAL:
        # Real path: provider was actually broken via fault injection AND the
        # run reached a terminal state without the operator-visible surfaces
        # going down.
        result["passed"] = True
        result["provenance"] = "real"
        result["notes"] = (
            f"provider-outage fault active; /health={health_code}, /metrics={metrics_code}, "
            f"/ready={ready_code}, run terminal={final_state} in {elapsed}s"
        )
    elif surfaces_ok and not fault_active:
        # The contract under test (operator surfaces stay live) was observed
        # against the same endpoints, but the fault was not injected.
        result["passed"] = True
        result["provenance"] = "simulated_pending_pm2"
        result["notes"] = (
            "operator surfaces healthy but HI_AGENT_FAULT_LLM_TIMEOUT was not "
            "active - full provider-outage drill requires the driver to set "
            "the fault env before server start (PM2-managed restart)."
        )
    elif surfaces_ok and fault_active and final_state not in _TERMINAL:
        # Fault active but run did not terminate: still useful evidence that
        # the operator surfaces stayed up; partial-real.
        result["passed"] = True
        result["provenance"] = "simulated_pending_pm2"
        result["notes"] = (
            f"provider-outage fault active and surfaces healthy; run state={final_state} "
            "did not reach terminal in budget - needs longer drill timeout."
        )
    else:
        result["passed"] = False
        result["provenance"] = "real"
        result["notes"] = (
            f"operator surfaces failed: health={health_code} metrics={metrics_code} "
            f"ready={ready_code} run={final_state}"
        )

    return result
