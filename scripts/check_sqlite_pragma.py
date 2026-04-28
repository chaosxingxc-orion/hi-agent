#!/usr/bin/env python3
"""Check that SQLite stores use WAL mode in prod posture."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def main() -> int:
    issues = []
    for f in ["hi_agent/server/event_store.py", "hi_agent/server/run_store.py"]:
        src = (ROOT / f).read_text(encoding="utf-8")
        if "WAL" not in src:
            issues.append(f"{f}: missing WAL pragma")
    result = {"status": "pass" if not issues else "fail", "issues": issues}
    print(json.dumps(result, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
