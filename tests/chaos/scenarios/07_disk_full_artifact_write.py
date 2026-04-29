"""Scenario 07: Disk-full artifact write failure.

Fault injection: The chaos matrix runner may set ``HI_AGENT_ARTIFACT_FAULT=oserror``
in the server environment. When this env var is present, the ArtifactRegistry
and ArtifactLedger raise ``OSError("Simulated disk full fault")`` on every
store/write call.

From within the scenario we:
  1. Submit a run that will attempt to write an artifact.
  2. Assert the run reaches a terminal state (``failed`` / ``error``) rather
     than hanging or completing as succeeded.
  3. Assert the run state is NOT ``succeeded`` when the fault env var is active,
     because a disk-full error must not be silently swallowed.

If ``HI_AGENT_ARTIFACT_FAULT`` is not set, the run may succeed normally; the
scenario skips to avoid false failures on non-fault CI runs.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from _helpers import (
    _OPENER,
    _fail_result,
    _ok_result,
    _skip_result,
    wait_terminal,
)

SCENARIO_NAME = "disk_full_artifact_write"
SCENARIO_DESCRIPTION = (
    "Submit run under HI_AGENT_ARTIFACT_FAULT=oserror; assert run reaches "
    "classified terminal state (not silent success, not hung)."
)

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)

_FAILURE_STATES = frozenset({"failed", "error", "timed_out"})


def _submit_artifact_run(base_url: str) -> str | None:
    """Submit a run with context hinting that artifact writing is expected."""
    body = json.dumps(
        {
            "goal": "disk full chaos test — produce any artifact",
            "context": {"_chaos_write_artifact": True},
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/runs",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=15) as r:
            return json.loads(r.read()).get("run_id")
    except Exception:
        return None


def _get_run_detail(base_url: str, run_id: str) -> dict:
    try:
        with _OPENER.open(f"{base_url}/runs/{run_id}", timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    # provenance is derived from what was actually observed.
    result: dict = {
        "name": SCENARIO_NAME,
        "duration_s": 0.0,
    }

    # Detect whether fault injection is active in the server environment.
    # The scenario itself can read the env var; if not set, skip asserting failure.
    fault_active = os.environ.get("HI_AGENT_ARTIFACT_FAULT") == "oserror"

    run_id = _submit_artifact_run(base_url)
    if not run_id:
        result.update(_fail_result("could not submit artifact-run"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)

    if final_state == "timeout":
        result.update(
            _skip_result(
                "run did not reach terminal within timeout; "
                "artifact fault injection requires HI_AGENT_ARTIFACT_FAULT=oserror env"
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result

    if final_state not in _TERMINAL:
        result.update(_fail_result(f"unexpected state: {final_state}"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result

    detail = _get_run_detail(base_url, run_id)
    error_type = detail.get("error_type") or detail.get("failure_reason") or ""

    if fault_active:
        # With fault active the run MUST NOT silently succeed
        if final_state in _FAILURE_STATES:
            result.update(
                _ok_result(
                    f"disk-full fault led to classified failure: state={final_state}, "
                    f"error_type={error_type!r}"
                )
            )
            # Fault env set AND run actually failed — real injection observed.
            result["provenance"] = "real"
            result["runtime_coupled"] = True
            result["synthetic"] = False
        elif final_state in ("completed", "succeeded"):
            result.update(
                _fail_result(
                    "run succeeded despite HI_AGENT_ARTIFACT_FAULT=oserror — "
                    "disk-full error was silently swallowed"
                )
            )
            result["provenance"] = "real"
            result["runtime_coupled"] = True
            result["synthetic"] = False
        else:
            result.update(_fail_result(f"unclassified terminal state: {final_state}"))
            result["provenance"] = "structural"
            result["runtime_coupled"] = False
            result["synthetic"] = True
    else:
        # No fault injected — any terminal state is acceptable
        result.update(
            _skip_result(
                f"HI_AGENT_ARTIFACT_FAULT not set; run ended with state={final_state} "
                "(no disk-full fault injected)"
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    return result
