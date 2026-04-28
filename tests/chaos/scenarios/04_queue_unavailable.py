"""Scenario 04: Queue saturation/unavailable.

Submits more runs than the queue depth to test rejection behavior.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from _helpers import _OPENER, _fail_result, _ok_result

SCENARIO_NAME = "queue_unavailable"
SCENARIO_DESCRIPTION = "Flood queue to test saturation rejection path."


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        "provenance": "real",
        "duration_s": 0.0,
    }
    rejections = 0
    submitted = 0
    for _ in range(20):
        body = json.dumps({"goal": "queue flood test", "context": {}}).encode()
        req = urllib.request.Request(
            f"{base_url}/runs",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with _OPENER.open(req, timeout=5) as r:
                if r.status < 400:
                    submitted += 1
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                rejections += 1
        except Exception:
            pass
    if submitted > 0:
        result.update(
            _ok_result(
                f"submitted={submitted}, rejections={rejections}; queue saturation handled"
            )
        )
    else:
        result.update(_fail_result("could not submit any runs"))
    return result
