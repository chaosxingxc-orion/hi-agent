#!/usr/bin/env python3
"""W14-D5: pytest.mark.skip discipline gate.

Every `@pytest.mark.skip` and `@pytest.mark.skipif` must include an
`expiry_wave="Wave N"` argument to prevent permanent test silencing.

Exit 0: pass (all skips have expiry_wave).
Exit 1: fail (skips missing expiry_wave).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"

_SKIP_PATTERN = re.compile(
    r"@pytest\.mark\.skip(?:if)?\s*\(",
    re.IGNORECASE,
)
_EXPIRY_ARG = re.compile(r'expiry_wave\s*=\s*["\']Wave\s*\d+', re.IGNORECASE)


def _scan_file(path: pathlib.Path) -> list[dict]:
    issues = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues

    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        if not _SKIP_PATTERN.search(line):
            continue
        # Check the skip call (may span up to 3 lines)
        snippet = "\n".join(lines[i - 1 : min(i + 3, len(lines))])
        if not _EXPIRY_ARG.search(snippet):
            issues.append({
                "file": str(path.relative_to(ROOT)),
                "line": i,
                "content": line.strip()[:120],
                "issue": "pytest.mark.skip missing expiry_wave argument",
            })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="pytest skip discipline gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    all_issues: list[dict] = []
    if TESTS_DIR.exists():
        for py_file in sorted(TESTS_DIR.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            all_issues.extend(_scan_file(py_file))

    status = "pass" if not all_issues else "fail"
    result = {
        "status": status,
        "check": "pytest_skip_discipline",
        "skips_without_expiry": len(all_issues),
        "issues": all_issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in all_issues:
            print(f"FAIL {issue['file']}:{issue['line']}: {issue['issue']}", file=sys.stderr)
        if not all_issues:
            print("PASS: all pytest.mark.skip decorators have expiry_wave argument")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
