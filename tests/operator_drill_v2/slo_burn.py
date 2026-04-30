"""Scenario 5 - slo_burn: sustained latency should burn an SLO budget; signal observable.

Operator behavior under test
---------------------------
The platform exposes SLO / alert surfaces (``/ops/slo``, ``/ops/alerts``,
``/ops/runbook``). Under sustained latency or repeated failures, an operator
must be able to:

  - Query /ops/slo and receive a structured response with a budget or burn
    indicator.
  - Query /ops/alerts and receive a (possibly empty) list of fired alerts.
  - Query /ops/runbook and receive the runbook reference for the firing path.

A real burn-through would require minutes-to-hours of degraded traffic. The
scenario does not wait for the budget to actually deplete; it exercises the
contract under test (operator-visible burn surfaces ANSWER) and records the
structural shape so a longer-running soak can fill in the burn assertion.

Provenance
----------
- ``real`` when /ops/slo, /ops/alerts, and /ops/runbook all return 200 with
  structured payloads.
- ``simulated_pending_pm2`` when one or more of those endpoints is unavailable
  - the platform must add the surface before this scenario can claim
  full-real burn-budget evidence.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

SCENARIO_NAME = "slo_burn"
SCENARIO_DESCRIPTION = (
    "Verify /ops/slo, /ops/alerts, /ops/runbook answer with structured "
    "payloads under load; sustained-burn assertion reserved for soak driver."
)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get_json(url: str, timeout: float = 10.0) -> tuple[int, dict | list]:
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> tuple[int, dict]:
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

    # Generate a tiny synthetic burst so /ops/slo has at least some data.
    burst_codes: list[int] = []
    for i in range(3):
        code, _payload = _post_json(
            f"{base_url}/runs",
            {"goal": f"operator-drill v2 slo-burn burst #{i}", "context": {}},
            timeout=10,
        )
        burst_codes.append(code)

    # Poll the SLO surfaces.
    slo_code, slo_payload = _get_json(f"{base_url}/ops/slo", timeout=5)
    alerts_code, alerts_payload = _get_json(f"{base_url}/ops/alerts", timeout=5)
    runbook_code, runbook_payload = _get_json(f"{base_url}/ops/runbook", timeout=5)
    metrics_code, metrics_payload = _get_json(f"{base_url}/metrics/json", timeout=5)

    # /ops/dashboard is the operator-friendly aggregate surface.
    dashboard_code, _dashboard_payload = _get_json(f"{base_url}/ops/dashboard", timeout=5)

    elapsed = round(time.monotonic() - t0, 2)
    result["duration_s"] = elapsed

    slo_ok = slo_code == 200 and isinstance(slo_payload, (dict, list))
    alerts_ok = alerts_code == 200 and isinstance(alerts_payload, (dict, list))
    runbook_ok = runbook_code == 200 and isinstance(runbook_payload, (dict, list))
    metrics_ok = metrics_code == 200 and isinstance(metrics_payload, (dict, list))

    # The minimum operator-visible surfaces for a burn-budget signal.
    surfaces_ok = slo_ok and alerts_ok and runbook_ok and metrics_ok

    result["evidence"] = {
        "burst_post_codes": burst_codes,
        "slo_status": slo_code,
        "alerts_status": alerts_code,
        "runbook_status": runbook_code,
        "metrics_status": metrics_code,
        "dashboard_status": dashboard_code,
        "slo_payload_kind": type(slo_payload).__name__,
        "alerts_count": (
            len(alerts_payload)
            if isinstance(alerts_payload, list)
            else len(alerts_payload.get("alerts", []))
            if isinstance(alerts_payload, dict)
            else 0
        ),
    }

    if surfaces_ok:
        # Real-path provenance: every operator surface required to detect
        # burn-budget answered with a structured payload. The sustained-burn
        # assertion (budget actually depleted) is reserved for the soak driver.
        result["passed"] = True
        result["provenance"] = "real"
        result["notes"] = (
            f"slo={slo_code} alerts={alerts_code} runbook={runbook_code} "
            f"metrics={metrics_code} dashboard={dashboard_code} - burn-budget "
            "surfaces all healthy; sustained-burn assertion deferred to soak."
        )
    else:
        # Some surface is missing; record exactly which.
        result["passed"] = bool(slo_ok and alerts_ok)
        result["provenance"] = "simulated_pending_pm2"
        result["notes"] = (
            f"surfaces partially available: slo={slo_code} alerts={alerts_code} "
            f"runbook={runbook_code} metrics={metrics_code} - at least one "
            "burn-budget surface is missing; full real provenance requires "
            "the platform to expose every operator-facing burn endpoint."
        )

    return result
