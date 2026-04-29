#!/usr/bin/env python3
"""CI gate: detect vacuous assertions in tests (AX-B B7).

Vacuous assertions provide false confidence:
  - `assert True` — always passes, tests nothing
  - `assert x in (200, 503)` — accepts failure status codes as success

Exit 0: PASS
Exit 1: FAIL
Exit 2: not_applicable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"

_ASSERT_TRUE = re.compile(r"\bassert\s+True\b")
# Accept-failure pattern: assert code in (2xx, 5xx) — 5xx is always a server error
_ACCEPT_FAILURE = re.compile(r"assert\s+\w+\.status_code\s+in\s+\([23]\d\d,\s*5\d\d\)")


def _scan_file(path: Path) -> list[dict]:
    issues = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues
    for i, line in enumerate(text.splitlines(), 1):
        if _ASSERT_TRUE.search(line) and "# Reason:" not in line:
            issues.append({
                "file": str(path.relative_to(ROOT)),
                "line": i,
                "pattern": "assert_true",
                "content": line.strip()[:100],
            })
        elif _ACCEPT_FAILURE.search(line):
            issues.append({
                "file": str(path.relative_to(ROOT)),
                "line": i,
                "pattern": "accept_failure_status",
                "content": line.strip()[:100],
            })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if not TESTS_DIR.exists():
        status = "fail" if args.strict else "not_applicable"
        r = {"status": status, "check": "vacuous_asserts", "reason": "tests dir absent"}
        if args.json:
            print(json.dumps(r, indent=2))
        else:
            print(f"{status}: tests dir absent")
        return 1 if status == "fail" else 2

    all_issues = []
    for py_file in sorted(TESTS_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        all_issues.extend(_scan_file(py_file))

    status = "fail" if all_issues else "pass"
    result = {
        "status": status,
        "check": "vacuous_asserts",
        "violations": len(all_issues),
        "issues": all_issues[:20],
        "reason": f"{len(all_issues)} vacuous assert(s) found" if all_issues else "",
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if all_issues:
            print(f"FAIL: {len(all_issues)} vacuous assertion(s):", file=sys.stderr)
            for iss in all_issues[:10]:
                print(f"  {iss['file']}:{iss['line']}: {iss['content']}", file=sys.stderr)
        else:
            print("PASS: no vacuous assertions found")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
