"""Standard JSON output schema for governance check scripts."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any


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
    status: str,  # "pass" | "fail" | "warn"
    violations: list[dict] | None = None,
    counts: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Print JSON result to stdout and exit with appropriate code."""
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
    sys.exit(0 if status in ("pass", "warn") else 1)
