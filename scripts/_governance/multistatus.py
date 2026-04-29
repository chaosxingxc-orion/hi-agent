"""Shared multistatus exit helper for governance gate scripts.

Usage:
    from scripts._governance.multistatus import emit_and_exit

    emit_and_exit(status="pass", check="my_check", **result_fields)
    # or
    emit_and_exit(status="not_applicable", check="my_check",
                  reason="tests dir absent", strict=args.strict)
"""
from __future__ import annotations

import json
import sys


_EXIT_CODES = {
    "pass": 0,
    "fail": 1,
    "not_applicable": 2,
    "deferred": 3,
    "warn": 1,  # warn always fail unless caller explicitly handles
}


def emit_and_exit(
    *,
    status: str,
    check: str,
    json_output: bool = False,
    strict: bool = False,
    allow_warn: bool = False,
    **kwargs,
) -> None:
    """Emit result and exit.

    Args:
        status: One of pass/fail/not_applicable/deferred/warn.
        check: The gate check name.
        json_output: If True, print JSON to stdout.
        strict: If True, not_applicable exits 1 (fail) instead of 2.
        allow_warn: If True, warn exits 0 instead of 1.
        **kwargs: Extra fields merged into the result dict.
    """
    result = {"status": status, "check": check, **kwargs}
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        if status == "pass":
            print(f"PASS: {check}")
        elif status == "not_applicable":
            reason = kwargs.get("reason", "not applicable")
            print(f"not_applicable: {reason}")
        elif status == "deferred":
            reason = kwargs.get("reason", "deferred")
            print(f"deferred: {reason}")
        elif status == "warn":
            reason = kwargs.get("reason", "warn")
            print(f"WARN: {reason}", file=sys.stderr)
        else:
            reason = kwargs.get("reason", "failed")
            print(f"FAIL: {reason}", file=sys.stderr)

    exit_code = _EXIT_CODES.get(status, 1)
    if status == "not_applicable" and strict:
        exit_code = 1
    if status == "warn" and allow_warn:
        exit_code = 0
    sys.exit(exit_code)
