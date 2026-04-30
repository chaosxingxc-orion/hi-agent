#!/usr/bin/env python3
"""W14-D4: noqa and type: ignore discipline gate.

Every `noqa` and `type: ignore` comment MUST have an adjacent
`# expiry_wave: Wave N` comment on the same line OR the line immediately above.

Without expiry tracking, suppression comments silently accumulate and are never
cleaned up, masking real defects.

Exit 0: pass (all suppressions have expiry).
Exit 1: fail (suppressions missing expiry_wave).
Status values: pass | fail | not_applicable | deferred
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

_SUPPRESSION = re.compile(r"#\s*(?:noqa|type:\s*ignore)", re.IGNORECASE)
# Accept either form:
#   - comment-style: ``expiry_wave: Wave N`` (canonical)
#   - kwarg-style:   ``expiry_wave="Wave N"`` (used inside rule7-exempt
#                    annotations and other in-string contexts)
_EXPIRY = re.compile(
    r'expiry_wave\s*[:=\s]+["\']?Wave\s*\d+',
    re.IGNORECASE,
)

_SCAN_DIRS = ["hi_agent", "scripts", "tests"]
_EXEMPT_FILES = {
    pathlib.Path("hi_agent/artifacts/registry.py"),
    pathlib.Path("hi_agent/runtime/sync_bridge.py"),
    pathlib.Path("hi_agent/security/path_policy.py"),
    pathlib.Path("hi_agent/security/url_policy.py"),
    pathlib.Path("hi_agent/workflows/contracts.py"),
}


def _scan_file(path: pathlib.Path) -> list[dict]:
    issues = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return issues

    for i, line in enumerate(lines, 1):
        if not _SUPPRESSION.search(line):
            continue
        if _EXPIRY.search(line):
            continue
        if i >= 2 and _EXPIRY.search(lines[i - 2]):
            continue
        issues.append(
            {
                "file": str(path.relative_to(ROOT)),
                "line": i,
                "content": line.strip()[:120],
                "issue": "suppression missing expiry_wave comment",
            }
        )
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
            rel = py_file.relative_to(ROOT)
            if rel in _EXEMPT_FILES:
                continue
            all_issues.extend(_scan_file(py_file))

    status = "pass" if not all_issues else "fail"
    result = {
        "status": status,
        "check": "noqa_discipline",
        "suppressions_without_expiry": len(all_issues),
        "issues": all_issues[:50],
        "reason": "legacy suppressions lack expiry_wave; gate is fail mode" if all_issues else "",
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if all_issues:
            print(f"FAIL: {len(all_issues)} suppressions missing expiry_wave", file=sys.stderr)
        else:
            print("PASS: all noqa/type:ignore suppressions have expiry_wave")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())

