"""Standard JSON output schema for governance check scripts."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any

# Exit code table:
#   pass            -> 0
#   warn            -> 1 (unless allow_warn=True, then 0)
#   fail            -> 1
#   not_applicable  -> 2
#   deferred        -> 3
_EXIT_CODES: dict[str, int] = {
    "pass": 0,
    "warn": 1,
    "fail": 1,
    "not_applicable": 2,
    "deferred": 3,
}


def get_head_sha() -> str:
    """Return current git HEAD short SHA."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
            cwd=pathlib.Path(__file__).parent.parent,
        ).stdout.strip()
    except Exception:
        return "unknown"


def emit_result(
    check_name: str,
    status: str,  # "pass" | "fail" | "warn" | "not_applicable" | "deferred"
    violations: list[dict] | None = None,
    counts: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    *,
    allow_warn: bool = False,
) -> None:
    """Print JSON result to stdout and exit with appropriate code.

    Exit codes:
        pass           -> 0
        warn           -> 1, unless allow_warn=True then 0
        fail           -> 1
        not_applicable -> 2
        deferred       -> 3
    """
    result = {
        "check": check_name,
        "status": status,
        "violations": violations or [],
        "counts": counts or {},
        "head": get_head_sha(),
    }
    if extra:
        result.update(extra)
    print(json.dumps(result, indent=2))
    exit_code = _EXIT_CODES.get(status, 1)
    if status == "warn" and allow_warn:
        exit_code = 0
    sys.exit(exit_code)
