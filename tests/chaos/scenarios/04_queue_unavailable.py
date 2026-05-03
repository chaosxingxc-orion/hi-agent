"""Scenario 04: Queue saturation/unavailable.

Submits more runs than the queue depth to test rejection behavior.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from _helpers import _OPENER, _fail_result, _ok_result, _skip_result

SCENARIO_NAME = "queue_unavailable"
SCENARIO_DESCRIPTION = "Flood queue to test saturation rejection path."


def _finalize_provenance(result: dict, *, submitted: int, rejected: int) -> dict:
    """Compute provenance from observed counts.

    W32-C.1: provenance="real" requires both that we successfully submitted
    at least one run AND that we observed at least one rejection (the path
    being exercised).  If we only submitted runs (no rejections seen), the
    saturation path was not exercised so the evidence is structural at best.
    If we submitted nothing the scenario was skipped.
    """
    if submitted > 0 and rejected > 0:
        result["provenance"] = "real"
    elif submitted > 0:
        result["provenance"] = "structural"
    else:
        result["provenance"] = "skip"
    return result


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        # provenance is computed by _finalize_provenance below; default to
        # "skip" so a partial-execution path never claims real evidence.
        "provenance": "skip",
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
    if submitted > 0 and rejections > 0:
        result.update(
            _ok_result(
                f"submitted={submitted}, rejections={rejections}; queue saturation handled"
            )
        )
    elif submitted > 0:
        result.update(
            _skip_result(
                f"submitted={submitted}, rejections=0; queue saturation path not "
                "exercised (queue did not saturate within 20 attempts) — provenance "
                "downgraded to structural to avoid false 'real' claim"
            )
        )
    else:
        result.update(_fail_result("could not submit any runs"))
    return _finalize_provenance(result, submitted=submitted, rejected=rejections)
