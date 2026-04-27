"""Shared helpers for chaos scenarios."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


def submit_run(base_url: str, task: str = "chaos test run") -> str | None:
    """POST /runs and return run_id, or None on failure."""
    body = json.dumps({"task": task, "context": {}}).encode()
    req = urllib.request.Request(
        f"{base_url}/runs",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("run_id")
    except Exception:
        return None


def get_run_state(base_url: str, run_id: str) -> str:
    """GET /runs/{run_id} and return state, or 'error' on failure."""
    try:
        with urllib.request.urlopen(f"{base_url}/runs/{run_id}", timeout=10) as r:
            data = json.loads(r.read())
            return data.get("state", data.get("status", "unknown"))
    except Exception:
        return "error"


def wait_terminal(base_url: str, run_id: str, timeout: float = 45.0) -> str:
    """Wait for run to reach a terminal state. Returns terminal state or 'timeout'."""
    terminal = {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = get_run_state(base_url, run_id)
        if state in terminal:
            return state
        time.sleep(0.5)
    return "timeout"


def list_runs(base_url: str) -> list[dict]:
    """GET /runs and return list."""
    try:
        with urllib.request.urlopen(f"{base_url}/runs?limit=100", timeout=10) as r:
            data = json.loads(r.read())
            return data if isinstance(data, list) else data.get("runs", [])
    except Exception:
        return []


_TERMINAL_STATES = {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}


def _ok_result(notes: str = "") -> dict:
    return {
        "passed": True,
        "assertions": {
            "accepted_runs_lost": 0,
            "duplicate_terminal_executions": 0,
            "duplicate_terminal_events": 0,
            "progress_offset_regressions": 0,
            "unclassified_failures": 0,
            "operator_visible_signal": True,
        },
        "notes": notes,
        "skipped": False,
        "skip_reason": "",
    }


def _skip_result(reason: str) -> dict:
    return {
        "passed": True,
        "assertions": {
            "accepted_runs_lost": 0,
            "duplicate_terminal_executions": 0,
            "duplicate_terminal_events": 0,
            "progress_offset_regressions": 0,
            "unclassified_failures": 0,
            "operator_visible_signal": True,
        },
        "notes": f"skipped: {reason}",
        "skipped": True,
        "skip_reason": reason,
    }


def _fail_result(notes: str) -> dict:
    return {
        "passed": False,
        "assertions": {
            "accepted_runs_lost": 1,
            "duplicate_terminal_executions": 0,
            "duplicate_terminal_events": 0,
            "progress_offset_regressions": 0,
            "unclassified_failures": 1,
            "operator_visible_signal": False,
        },
        "notes": notes,
        "skipped": False,
        "skip_reason": "",
    }
