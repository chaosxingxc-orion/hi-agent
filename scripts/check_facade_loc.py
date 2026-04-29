#!/usr/bin/env python
"""CI gate: fail if any agent_server/facade/*.py exceeds 200 LOC (R-AS-8).

Facade modules must be thin adapters, not business logic containers.

Usage: python scripts/check_facade_loc.py
Exit 0 = clean; 1 = violations.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FACADE_DIR = ROOT / "agent_server" / "facade"
MAX_LOC = 200


def count_loc(path: Path) -> int:
    """Count non-empty, non-comment lines."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0
    return sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))


def check() -> int:
    if not FACADE_DIR.exists():
        print("PASS (R-AS-8): agent_server/facade/ not yet created — skipping")
        return 0

    violations = []
    for py_file in sorted(FACADE_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts or py_file.name == "__init__.py":
            continue
        loc = count_loc(py_file)
        if loc > MAX_LOC:
            violations.append(f"  {py_file.relative_to(ROOT)}: {loc} LOC (max {MAX_LOC})")

    if violations:
        print(f"FAIL (R-AS-8): {len(violations)} facade module(s) exceed {MAX_LOC} LOC:")
        for v in violations:
            print(v)
        return 1
    print(f"PASS (R-AS-8): all facade modules within {MAX_LOC} LOC limit")
    return 0


if __name__ == "__main__":
    sys.exit(check())
