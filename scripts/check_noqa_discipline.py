#!/usr/bin/env python3
"""W14-D4: noqa and type: ignore discipline gate.

Every `# noqa` and `# type: ignore` comment MUST have an adjacent
`# expiry_wave: Wave N` comment on the same line OR the line immediately above.

Without expiry tracking, suppression comments silently accumulate and are never
cleaned up, masking real defects.

Exit 0: pass (all suppressions have expiry).
Exit 1: fail (suppressions missing expiry_wave).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

_SUPPRESSION = re.compile(r"#\s*(?:noqa|type:\s*ignore)", re.IGNORECASE)
_EXPIRY = re.compile(r"expiry_wave\s*[:\s]+Wave\s*\d+", re.IGNORECASE)
_REASON = re.compile(r"#\s*reason\s*:", re.IGNORECASE)

_SCAN_DIRS = ["hi_agent", "scripts", "tests"]
_EXCLUDE_PATTERNS = ["__pycache__", ".git", "*.pyc"]


def _scan_file(path: pathlib.Path) -> list[dict]:
    issues = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return issues

    for i, line in enumerate(lines, 1):
        if not _SUPPRESSION.search(line):
            continue
        # Check same line for expiry_wave
        if _EXPIRY.search(line):
            continue
        # Check line immediately above
        if i >= 2 and _EXPIRY.search(lines[i - 2]):
            continue
        issues.append({
            "file": str(path.relative_to(ROOT)),
            "line": i,
            "content": line.strip()[:120],
            "issue": "suppression missing expiry_wave comment",
        })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="noqa/type:ignore discipline gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    all_issues: list[dict] = []
    for scan_dir in _SCAN_DIRS:
        d = ROOT / scan_dir
        if not d.exists():
            continue
        for py_file in sorted(d.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            all_issues.extend(_scan_file(py_file))

    status = "pass" if not all_issues else "fail"
    result = {
        "status": status,
        "check": "noqa_discipline",
        "suppressions_without_expiry": len(all_issues),
        "issues": all_issues[:50],  # truncate for JSON output
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in all_issues[:20]:
            print(f"FAIL {issue['file']}:{issue['line']}: {issue['issue']}", file=sys.stderr)
        if len(all_issues) > 20:
            print(f"  ... and {len(all_issues) - 20} more", file=sys.stderr)
        if not all_issues:
            print("PASS: all noqa/type:ignore suppressions have expiry_wave")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
