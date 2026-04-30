#!/usr/bin/env python3
""" governance gate: enforce Rule 7 closure on owned LLM hot-path sites.

This gate verifies that the three Rule 7 closure sites in
``hi_agent/llm/http_gateway.py`` (event-bus publish swallow at the
LLM-call boundary; ``record_fallback`` failure swallow on the inner
failover branch; ``record_fallback`` failure swallow on the outer guard
branch) remain closed once  has merged.

Scope is intentionally narrow: only the sites Track B owns. Other
``rule7-exempt`` markers across the codebase are governed by
``scripts/check_silent_degradation.py``; line 489/642/666 in
``http_gateway.py`` are tracked as W24 follow-ups (same pattern, different
control-flow branches) — they are NOT in 's scope per the Track B
specification.

The gate fails-closed if any of the following appear:

* The literal ``# rule7-exempt`` annotation in ``HttpLLMGateway.complete``
  between lines covering the event-bus publish boundary.
* The literal ``"Rule 7 violation"`` substring in the inner / outer
  fallback-recording guards inside ``HttpLLMGateway.complete``.

Outputs multistatus JSON via ``scripts/_governance/multistatus.py`` so
this gate plays well with the  multistatus runner.
"""
# Status values: pass | fail | not_applicable
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# scripts/_governance/multistatus.py is the  canonical exit helper.
# Track B reuses it directly; the Track B fallback to plain JSON is no
# longer needed because multistatus.py is already on disk.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts._governance.multistatus import emit_and_exit

GATEWAY_PATH = _REPO_ROOT / "hi_agent" / "llm" / "http_gateway.py"

# Owned-site discovery: locate the start of ``HttpLLMGateway.complete``
# and the start of ``HttpLLMGateway._direct_complete`` (the next method).
# Anything between those two boundaries is 's owned scope. The
# remaining ``Rule 7 violation`` markers in ``_post`` (sync gateway
# retry-exhausted branch, ~line 489) and in ``HTTPGateway.complete``
# (async failover/outer guards, ~lines 642/666) are W24 follow-ups.
_COMPLETE_DEF_RE = re.compile(r"^\s*def complete\(self, request: LLMRequest\) -> LLMResponse:")
_DIRECT_COMPLETE_DEF_RE = re.compile(
    r"^\s*def _direct_complete\(self, request: LLMRequest\) -> LLMResponse:"
)
_RULE7_VIOLATION_LITERAL = "Rule 7 violation"
_RULE7_EXEMPT_LITERAL = "rule7-exempt"


def _find_owned_range(lines: list[str]) -> tuple[int, int] | None:
    """Return [start, end) line indices covering ``HttpLLMGateway.complete``.

    Returns None if either anchor is not found (not_applicable).
    """
    start: int | None = None
    end: int | None = None
    for idx, line in enumerate(lines):
        if start is None and _COMPLETE_DEF_RE.match(line):
            start = idx
            continue
        if start is not None and _DIRECT_COMPLETE_DEF_RE.match(line):
            end = idx
            break
    if start is None or end is None:
        return None
    return start, end


def _scan_owned_range(
    lines: list[str], start: int, end: int
) -> list[dict[str, object]]:
    """Return a list of violation dicts for owned-scope offending lines."""
    violations: list[dict[str, object]] = []
    for idx in range(start, end):
        text = lines[idx]
        # Site 1: rule7-exempt annotation in the event-bus publish branch.
        if _RULE7_EXEMPT_LITERAL in text:
            violations.append(
                {
                    "site": "event_bus_publish_swallow",
                    "file": str(GATEWAY_PATH.relative_to(_REPO_ROOT)),
                    "line": idx + 1,
                    "snippet": text.rstrip(),
                    "marker": _RULE7_EXEMPT_LITERAL,
                }
            )
        # Sites 2 & 3: explicit "Rule 7 violation" log message.
        if _RULE7_VIOLATION_LITERAL in text:
            violations.append(
                {
                    "site": "record_fallback_failure_swallow",
                    "file": str(GATEWAY_PATH.relative_to(_REPO_ROOT)),
                    "line": idx + 1,
                    "snippet": text.rstrip(),
                    "marker": _RULE7_VIOLATION_LITERAL,
                }
            )
    return violations


def main() -> None:
    """Run main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="emit multistatus JSON to stdout",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat not_applicable as fail",
    )
    args = parser.parse_args()

    if not GATEWAY_PATH.is_file():
        emit_and_exit(
            status="not_applicable",
            check="check_rule7_observability",
            json_output=args.json_output,
            strict=args.strict,
            reason=f"{GATEWAY_PATH} does not exist",
        )

    text = GATEWAY_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    owned = _find_owned_range(lines)
    if owned is None:
        emit_and_exit(
            status="not_applicable",
            check="check_rule7_observability",
            json_output=args.json_output,
            strict=args.strict,
            reason="HttpLLMGateway.complete or _direct_complete anchor not found",
        )

    start, end = owned
    violations = _scan_owned_range(lines, start, end)

    if violations:
        if args.json_output:
            print(
                json.dumps(
                    {
                        "status": "fail",
                        "check": "check_rule7_observability",
                        "owned_range": [start + 1, end + 1],
                        "violations": violations,
                    },
                    indent=2,
                )
            )
            sys.exit(1)
        emit_and_exit(
            status="fail",
            check="check_rule7_observability",
            json_output=False,
            strict=args.strict,
            reason=(
                f"{len(violations)} Rule 7 closure regression(s) inside "
                f"HttpLLMGateway.complete (lines {start + 1}-{end + 1}): "
                + ", ".join(f"line {v['line']} ({v['marker']})" for v in violations)
            ),
            violations=violations,
        )

    emit_and_exit(
        status="pass",
        check="check_rule7_observability",
        json_output=args.json_output,
        strict=args.strict,
        owned_range=[start + 1, end + 1],
        message=(
            "All three  Rule 7 closure sites in HttpLLMGateway.complete "
            "remain closed (event-bus publish; inner record_fallback guard; "
            "outer record_fallback guard)."
        ),
    )


if __name__ == "__main__":
    main()
