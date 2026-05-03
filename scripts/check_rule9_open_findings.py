#!/usr/bin/env python3
"""W32-D D.6: Rule 9 open-findings gate.

Per CLAUDE.md Rule 9, an open finding in a ship-blocking category MUST block
delivery. A self-audit / incident-log entry that lists an unresolved defect
under one of the six ship-blocking categories is treated as an open finding;
its presence at HEAD blocks the release.

Source of truth: ``docs/rules-incident-log.md``.

Convention enforced by this gate
--------------------------------
A "finding" is an entry of the form ::

    - Status: OPEN — <category> — <description>
    - Status: CLOSED — <category> — <description>

…inside a section whose heading names a Rule (``### Rule N — …``) or a
free-text section (``### Open Findings — …``). The status marker is matched
case-sensitively to discourage accidental drift; the category token is matched
case-insensitively against the ship-blocking-category vocabulary.

Ship-blocking categories (per CLAUDE.md Rule 9):
  - LLM path (gateway, adapter, streaming, async lifetime, retry, rate-limit)
  - Run lifecycle (stage, state machine, cancellation, resume, watchdog)
  - HTTP contract (path, method, body, status, auth)
  - Security boundary (path traversal, shell=True, auth bypass, tenant-scope escape)
  - Resource lifetime (async clients, file handles, subprocesses, background tasks)
  - Observability (missing metric, log, or health signal for a failure path)

Exit codes
----------
  0 — pass: no OPEN findings in any ship-blocking category, or the log carries
           no findings at all.
  1 — fail: at least one OPEN finding in a ship-blocking category.
  2 — deferred: ``docs/rules-incident-log.md`` is missing.

Status values: pass | fail | not_applicable | deferred
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "docs" / "rules-incident-log.md"

# Vocabulary the gate recognises as "ship-blocking" (per Rule 9).
# Each tuple: (canonical-name, regex of accepted aliases on the right of
# Status: OPEN — <category-token> —). Aliases are matched case-insensitively
# and tolerate whitespace around the separator.
_SHIP_BLOCKING_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("LLM path", re.compile(r"^\s*llm[\s_-]?path\b", re.IGNORECASE)),
    ("Run lifecycle", re.compile(r"^\s*run[\s_-]?lifecycle\b", re.IGNORECASE)),
    ("HTTP contract", re.compile(r"^\s*http[\s_-]?contract\b", re.IGNORECASE)),
    ("Security boundary", re.compile(r"^\s*security[\s_-]?boundary\b", re.IGNORECASE)),
    ("Resource lifetime", re.compile(r"^\s*resource[\s_-]?lifetime\b", re.IGNORECASE)),
    ("Observability", re.compile(r"^\s*observability\b", re.IGNORECASE)),
)

# Match a finding line: bullet + Status: OPEN/CLOSED <sep> <category> <sep> <text>.
# We tolerate em-dash (U+2014), en-dash (U+2013), single hyphen, or double
# hyphen as separators. The unicode dash characters are constructed via chr()
# so the source file stays ASCII-clean (avoids RUF001/RUF003 ambiguous-dash
# warnings) while still matching the actual unicode separators downstream
# operators put in markdown.
_EM_DASH = chr(0x2014)  # em dash
_EN_DASH = chr(0x2013)  # en dash
_SEP = r"\s*(?:" + _EM_DASH + "|" + _EN_DASH + r"|-|--)\s*"
_FINDING_RE = re.compile(
    r"^\s*[-*]\s*Status\s*:\s*(?P<status>OPEN|CLOSED)" + _SEP +
    r"(?P<category>[^" + _EM_DASH + _EN_DASH + r"\-]+?)" + _SEP +
    r"(?P<description>.+?)\s*$"
)


def _classify_category(category_token: str) -> str | None:
    """Return the canonical ship-blocking name for ``category_token`` or None."""
    for name, pat in _SHIP_BLOCKING_CATEGORIES:
        if pat.search(category_token):
            return name
    return None


def _scan(text: str) -> list[dict]:
    """Return all OPEN findings in ship-blocking categories.

    Each finding is reported as ``{"line": int, "category": str, "text": str}``.
    Non-blocking categories and CLOSED findings are skipped.
    """
    open_blocking: list[dict] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        m = _FINDING_RE.match(raw)
        if not m:
            continue
        status = m.group("status")
        category_token = m.group("category").strip()
        description = m.group("description").strip()
        if status != "OPEN":
            continue
        canonical = _classify_category(category_token)
        if canonical is None:
            continue  # non-blocking category — Rule 9 does not gate on it
        open_blocking.append({
            "line": lineno,
            "category": canonical,
            "category_token": category_token,
            "description": description,
        })
    return open_blocking


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rule 9 open-findings gate.",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--log-path",
        type=pathlib.Path,
        default=LOG_PATH,
        help="Path to the rules-incident-log.md file (default: docs/rules-incident-log.md)",
    )
    args = parser.parse_args(argv)

    log_path: pathlib.Path = args.log_path
    if not log_path.exists():
        result = {
            "check": "rule9_open_findings",
            "status": "deferred",
            "reason": f"log file not found at {log_path}",
            "open_blocking_total": 0,
            "open_findings": [],
        }
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"DEFERRED rule9_open_findings: log file not found at {log_path}",
                file=sys.stderr,
            )
        return 2

    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        result = {
            "check": "rule9_open_findings",
            "status": "fail",
            "reason": f"cannot read {log_path}: {exc}",
            "open_blocking_total": 0,
            "open_findings": [],
        }
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            print(f"FAIL rule9_open_findings: cannot read log file: {exc}", file=sys.stderr)
        return 1

    findings = _scan(text)
    status = "fail" if findings else "pass"
    result = {
        "check": "rule9_open_findings",
        "status": status,
        "log_path": str(log_path.relative_to(ROOT) if log_path.is_relative_to(ROOT) else log_path),
        "open_blocking_total": len(findings),
        "open_findings": findings,
        "ship_blocking_categories": [name for name, _pat in _SHIP_BLOCKING_CATEGORIES],
    }

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        if findings:
            count = len(findings)
            print(
                "FAIL rule9_open_findings: "
                f"{count} OPEN finding(s) in ship-blocking categories",
                file=sys.stderr,
            )
            for f in findings:
                print(
                    f"  {log_path.name}:{f['line']}: "
                    f"{f['category']} {_EM_DASH} {f['description']}",
                    file=sys.stderr,
                )
        else:
            print("PASS rule9_open_findings: 0 OPEN findings in ship-blocking categories")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
