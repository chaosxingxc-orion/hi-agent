#!/usr/bin/env python3
"""Check that SQLite stores use WAL mode in prod posture.

Exit 0: pass (WAL pragma found in all checked files).
Exit 1: fail (WAL pragma missing in one or more files).
Exit 2: not_applicable (checked files do not exist in this checkout).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

_CHECKED_FILES = [
    "hi_agent/server/event_store.py",
    "hi_agent/server/run_store.py",
]


def main() -> int:
    missing_files = [f for f in _CHECKED_FILES if not (ROOT / f).exists()]
    if len(missing_files) == len(_CHECKED_FILES):
        result = {
            "status": "not_applicable",
            "check": "sqlite_wal_pragma",
            "reason": "checked source files not found in checkout",
            "missing_files": missing_files,
            "issues": [],
        }
        print(json.dumps(result, indent=2))
        return 2

    issues = []
    for f in _CHECKED_FILES:
        path = ROOT / f
        if not path.exists():
            continue  # silently skip absent optional files
        src = path.read_text(encoding="utf-8")
        if "WAL" not in src:
            issues.append(f"{f}: missing WAL pragma")

    status = "pass" if not issues else "fail"
    result = {
        "status": status,
        "check": "sqlite_wal_pragma",
        "issues": issues,
    }
    print(json.dumps(result, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
