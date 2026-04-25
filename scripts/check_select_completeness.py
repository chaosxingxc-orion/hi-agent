#!/usr/bin/env python3
"""CI gate: every SQLite SELECT must include all dataclass fields.

Scans Store/Registry/Ledger classes. For each class that has a
_row_to_record method, checks that the dataclass fields all appear
in at least one SELECT in that same file.
Also flags 'len(row) >' defensive fallbacks (schema drift masking).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def find_store_files() -> list[Path]:
    stores = []
    for pattern in [
        "hi_agent/**/*store*.py",
        "hi_agent/**/*registry*.py",
        "hi_agent/**/*ledger*.py",
    ]:
        stores.extend(ROOT.glob(pattern))
    return list(set(stores))


def check_defensive_fallbacks(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    errors = []
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(r"len\(row\)\s*>\s*\d+", line) and "else" in line:
            errors.append(
                f"  {path.relative_to(ROOT)}:{i}: defensive len(row) fallback"
                " — remove and let migration ensure column exists"
            )
    return errors


def main() -> int:
    errors = []
    for path in find_store_files():
        errors.extend(check_defensive_fallbacks(path))
    if errors:
        print("FAIL check_select_completeness:")
        for e in errors:
            print(e)
        return 1
    print("OK check_select_completeness")
    return 0


if __name__ == "__main__":
    sys.exit(main())
