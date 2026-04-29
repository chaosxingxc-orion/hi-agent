#!/usr/bin/env python3
"""W14-D5: pytest.mark.skip discipline gate.

Every `@pytest.mark.skip` and `@pytest.mark.skipif` must include an
`expiry_wave="Wave N"` argument to prevent permanent test silencing,
OR be a condition-bounded skip without an expiry_wave (for permanent
environmental conditions like platform or external secrets).

Rules enforced:
1. If a skip has `expiry_wave="Wave N"` where N <= current_wave: FAIL
2. If a skip has no `expiry_wave` at all: FAIL (unless it is a condition-
   bounded skipif where the condition is clearly permanent)

Exit 0: pass (all skips either have future expiry_wave or are condition-bounded).
Exit 1: fail (skips with stale/expired expiry_wave, or unconditional skips missing expiry_wave).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
CURRENT_WAVE_FILE = ROOT / "docs" / "governance" / "current-wave.txt"

_SKIP_PATTERN = re.compile(
    r"@pytest\.mark\.skip(?:if)?\s*\(",
    re.IGNORECASE,
)
_EXPIRY_ARG = re.compile(r'expiry_wave\s*=\s*["\']Wave\s*(\d+)', re.IGNORECASE)
_SKIPIF_PATTERN = re.compile(r"@pytest\.mark\.skipif\s*\(", re.IGNORECASE)


def _read_current_wave() -> int:
    """Read current wave number from docs/governance/current-wave.txt."""
    try:
        return int(CURRENT_WAVE_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        # Default to a conservative value if file is missing
        return 0


def _scan_file(path: pathlib.Path, current_wave: int) -> list[dict]:
    issues = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues

    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        if not _SKIP_PATTERN.search(line):
            continue
        # Check the skip call (may span up to 15 lines for multi-line reason strings)
        snippet = "\n".join(lines[i - 1 : min(i + 15, len(lines))])

        m = _EXPIRY_ARG.search(snippet)
        if m:
            # Has expiry_wave — check if it's stale (wave <= current_wave)
            wave_num = int(m.group(1))
            if wave_num <= current_wave:
                issues.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": i,
                    "content": line.strip()[:120],
                    "issue": f"pytest.mark.skip has stale expiry_wave (Wave {wave_num} <= current Wave {current_wave}); "
                             "resolve: remove skip (Rule A), update to Wave N+1 (Rule B), or convert to condition-bounded skip (Rule C)",
                })
        else:
            # No expiry_wave — only acceptable for condition-bounded skipif
            # (unconditional @pytest.mark.skip without expiry is not acceptable)
            is_skipif = _SKIPIF_PATTERN.search(line) is not None
            if not is_skipif:
                issues.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": i,
                    "content": line.strip()[:120],
                    "issue": "pytest.mark.skip (unconditional) missing expiry_wave argument; add expiry_wave or convert to condition-bounded skipif",
                })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="pytest skip discipline gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    current_wave = _read_current_wave()

    # not_applicable when tests directory is absent (stripped bundle or CI shard with no tests)
    if not TESTS_DIR.exists():
        result = {
            "status": "not_applicable",
            "check": "pytest_skip_discipline",
            "reason": "tests directory not found",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("not_applicable: tests directory not found")
        return 0

    all_issues: list[dict] = []
    for py_file in sorted(TESTS_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        all_issues.extend(_scan_file(py_file, current_wave))

    status = "pass" if not all_issues else "fail"
    result = {
        "status": status,
        "check": "pytest_skip_discipline",
        "current_wave": current_wave,
        "skips_with_stale_or_missing_expiry": len(all_issues),
        "issues": all_issues,
        "reason": f"found {len(all_issues)} skip(s) with stale or missing expiry_wave (current wave: {current_wave})" if all_issues else "",
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if all_issues:
            print(f"FAIL: {len(all_issues)} skip(s) with stale/missing expiry_wave (current Wave {current_wave})", file=sys.stderr)
            for issue in all_issues[:20]:
                print(f"  {issue['file']}:{issue['line']}: {issue['issue']}", file=sys.stderr)
            if len(all_issues) > 20:
                print(f"  ... and {len(all_issues) - 20} more", file=sys.stderr)
        else:
            print(f"PASS: all pytest.mark.skip decorators are compliant (current Wave {current_wave})")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
