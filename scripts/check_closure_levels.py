#!/usr/bin/env python3
"""GOV-C / Rule 15: Closure-level enum gate.

Every defect row in closure notices must carry a valid Rule 15 level enum.
A 'closure notice' is any docs/downstream-responses/*notice*.md file.
A defect row is any markdown table row in such a file where a 'Level' column exists.

Valid levels (Rule 15):
  component_exists | wired_into_default_path | covered_by_default_path_e2e |
  verified_at_release_head | operationally_observable | in_progress | deferred

Exit 0: pass (all rows have valid levels, or no Level column found)
Exit 1: fail (one or more rows have missing or invalid level values)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
NOTICES_DIR = DOCS / "downstream-responses"

_VALID_LEVELS = frozenset({
    "component_exists",
    "wired_into_default_path",
    "covered_by_default_path_e2e",
    "verified_at_release_head",
    "operationally_observable",
    "in_progress",
    "deferred",
})
# Legacy Rule 13 levels (l0–l4) from pre-Rule-15 closure notices.
_LEGACY_LEVELS = frozenset({"l0", "l1", "l2", "l3", "l4"})


def _normalize_level(raw: str) -> str:
    """Strip markdown formatting and parenthetical qualifiers from a level value."""
    val = raw.strip().strip("`*").strip()
    # Drop parenthetical qualifiers like "l3 (post w3-a)"
    paren_idx = val.find("(")
    if paren_idx != -1:
        val = val[:paren_idx].strip()
    return val

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_SEP_ROW_RE = re.compile(r"^\|\s*[-:]+[-\s|:]*\|$")


def _check_notice(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [f"{path.name}: unreadable ({exc})"]

    header: list[str] = []
    level_col: int | None = None
    in_table = False

    for lineno, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not _TABLE_ROW_RE.match(line):
            # Reset table state when we leave a table block
            in_table = False
            header = []
            level_col = None
            continue

        if _SEP_ROW_RE.match(line):
            # Separator row — skip
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]

        if not in_table:
            # First non-separator row = header
            header = cells
            lower_headers = [h.lower() for h in header]
            if "level" in lower_headers:
                level_col = lower_headers.index("level")
            in_table = True
            continue

        # Data row
        if level_col is None:
            continue
        if level_col >= len(cells):
            violations.append(
                f"{path.name}:{lineno}: row has fewer columns than header "
                f"(expected Level at col {level_col})"
            )
            continue
        value = _normalize_level(cells[level_col].lower())
        if not value or value == "-":
            violations.append(
                f"{path.name}:{lineno}: missing level value in Level column"
            )
        elif value not in _VALID_LEVELS and value not in _LEGACY_LEVELS:
            violations.append(
                f"{path.name}:{lineno}: invalid level '{value}' "
                f"(valid: {', '.join(sorted(_VALID_LEVELS))})"
            )

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Closure-level enum gate (Rule 15).")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not NOTICES_DIR.exists():
        result = {
            "check": "closure_levels",
            "status": "not_applicable",
            "reason": "docs/downstream-responses/ not found",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 0

    all_violations: list[str] = []
    for notice_file in sorted(NOTICES_DIR.glob("*notice*.md")):
        all_violations.extend(_check_notice(notice_file))

    status = "pass" if not all_violations else "fail"
    result = {
        "check": "closure_levels",
        "status": status,
        "violations_count": len(all_violations),
        "violations": all_violations,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if all_violations:
            for v in all_violations:
                print(f"FAIL: {v}", file=sys.stderr)
        else:
            print("PASS: all closure notice Level columns have valid Rule 15 enum values")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
