#!/usr/bin/env python3
"""W14-A8: Closure taxonomy gate.

Parses closure notices under docs/downstream-responses/ and fails when any
defect-closure row is missing a `level:` field from the closure-taxonomy enum:
  component_exists | wired_into_default_path | covered_by_default_path_e2e
  | verified_at_release_head | operationally_observable

Exit 0: pass (all closure rows carry valid level) or deferred (no notices found).
Exit 1: fail (missing or invalid level fields).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTICES_DIR = ROOT / "docs" / "downstream-responses"

_VALID_LEVELS = frozenset({
    "component_exists",
    "wired_into_default_path",
    "covered_by_default_path_e2e",
    "verified_at_release_head",
    "operationally_observable",
})

# Match closure rows like: | P0-1 | ... | CLOSED | level: verified_at_release_head |
_CLOSURE_PATTERN = re.compile(
    r"\|\s*(?:P\d+-\d+|DF-\d+|[A-Z0-9-]+)\s*\|[^|]*\|[^|]*(?:CLOSED|IN PROGRESS|OPEN)[^|]*\|([^|]*)\|",
    re.IGNORECASE,
)
_LEVEL_PATTERN = re.compile(r"level:\s*(\S+)", re.IGNORECASE)


_CLOSURE_LEVEL_ENUM = re.compile(
    r"level:\s*(?:" + "|".join(re.escape(l) for l in _VALID_LEVELS) + r")",
    re.IGNORECASE,
)


def _is_wave14_plus_notice(path: pathlib.Path, text: str) -> bool:
    """Return True if this notice is Wave 14 or later (must comply with level: requirement)."""
    # Check filename for wave number >= 14
    m = re.search(r"wave[-_]?(\d+)", path.name, re.IGNORECASE)
    if m and int(m.group(1)) >= 14:
        return True
    # Check if the notice explicitly uses the closure-level enum (opted-in to new taxonomy)
    if _CLOSURE_LEVEL_ENUM.search(text):
        return True
    return False


def _check_notice(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Skip template or draft notices
    if re.search(r"Status:.*(?:draft|template|superseded)", text, re.IGNORECASE):
        return []
    # Pre-Wave-14 notices without explicit level: fields are exempt
    if not _is_wave14_plus_notice(path, text):
        return []
    issues: list[str] = []
    for row_match in _CLOSURE_PATTERN.finditer(text):
        row_content = row_match.group(1)
        level_match = _LEVEL_PATTERN.search(row_content)
        if not level_match:
            line_no = text[: row_match.start()].count("\n") + 1
            issues.append(f"{path.name}:{line_no}: closure row missing 'level:' field")
            continue
        level = level_match.group(1).rstrip(".,|")
        if level not in _VALID_LEVELS:
            line_no = text[: row_match.start()].count("\n") + 1
            issues.append(
                f"{path.name}:{line_no}: invalid level {level!r} "
                f"(valid: {', '.join(sorted(_VALID_LEVELS))})"
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Closure taxonomy gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not NOTICES_DIR.exists():
        result = {"status": "not_applicable", "check": "closure_taxonomy",
                  "reason": "docs/downstream-responses/ not found"}
        if args.json:
            print(json.dumps(result, indent=2))
        return 0

    notices = [
        f for f in NOTICES_DIR.glob("*.md")
        if not f.name.startswith("_")
    ]
    if not notices:
        result = {"status": "not_applicable", "check": "closure_taxonomy",
                  "reason": "no closure notices found"}
        if args.json:
            print(json.dumps(result, indent=2))
        return 0

    all_issues: list[str] = []
    for notice in sorted(notices):
        all_issues.extend(_check_notice(notice))

    status = "pass" if not all_issues else "fail"
    result = {
        "status": status,
        "check": "closure_taxonomy",
        "notices_checked": len(notices),
        "issues": all_issues,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if all_issues:
            for issue in all_issues:
                print(f"FAIL: {issue}", file=sys.stderr)
        else:
            print(f"PASS: {len(notices)} notices checked, all closure rows have valid level fields")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
